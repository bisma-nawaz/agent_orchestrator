"""
LLM-as-Judge grading system for evaluating research reports.

Uses a *separate* LLM call with a dedicated evaluation system prompt, as
recommended by Anthropic's "Demystifying Evals for AI Agents" post.

Key design choices:
- Uses a cheaper/faster model (claude-haiku) so grading doesn't dominate cost.
- The GRADER_SYSTEM_PROMPT is intentionally skeptical to counteract the
  positivity bias that LLM judges tend to exhibit.
- Four orthogonal dimensions prevent a single strong axis from hiding weaknesses.
- Falls back to a neutral (5.0) score on parse failure so the loop stays alive.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Tuple

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Grader system prompt (intentionally separate from any orchestrator prompt)
# ---------------------------------------------------------------------------
GRADER_SYSTEM_PROMPT = """\
You are a strict academic peer-reviewer assessing AI-generated research reports.
Your only job is critical evaluation — you did NOT write these reports.

Scoring philosophy:
- Be skeptical. Most AI reports are mediocre (5–6/10). Reserve 8+ for genuinely excellent work.
- Penalise vague statements like "AI is transforming X" with no specifics.
- Penalise missing named tools, projects, papers, or real companies.
- Reward concrete numbers, specific tradeoffs, named benchmarks, and nuanced analysis.
- Do NOT reward length alone — a concise, precise report beats a verbose vague one.

Bias awareness:
- Do not inflate scores because the report "sounds confident".
- Do not penalise unconventional structure if the content is strong.
- Score each dimension independently; a well-structured but shallow report should
  score high on Structure and low on Specificity.
"""


@dataclass
class GradeResult:
    """Scores for a single report across four independent dimensions (1–10 each)."""

    comprehensiveness: float  # Covers all key aspects of the question
    accuracy: float           # Claims are plausible and grounded in real facts
    structure: float          # Well-organised, clear sections, logical flow
    specificity: float        # Concrete examples, named tools, numbers, tradeoffs
    reasoning: str = field(default="", repr=False)

    @property
    def total(self) -> float:
        """Average score across all four dimensions."""
        return (
            self.comprehensiveness + self.accuracy + self.structure + self.specificity
        ) / 4.0

    def __str__(self) -> str:
        return (
            f"C={self.comprehensiveness:.1f} A={self.accuracy:.1f} "
            f"S={self.structure:.1f} Sp={self.specificity:.1f} => {self.total:.2f}"
        )


class Grader:
    """
    Wraps an Anthropic client and provides report-scoring functionality.

    Deliberately uses a different model and system prompt from the orchestrator
    sub-agents to avoid self-grading bias.
    """

    GRADING_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set for the grader")
        self.client = Anthropic(api_key=self.api_key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def grade_report(self, question: str, report: str) -> GradeResult:
        """
        Score a single report against the original question.

        Truncates the report to 3 000 chars so the grader stays within token
        budgets and focuses on the substance rather than sheer length.
        """
        truncated = report[:3000]
        if len(report) > 3000:
            truncated += "\n\n[... report truncated for evaluation ...]"

        prompt = (
            f"**Research question:** {question}\n\n"
            f"**Report to evaluate:**\n{truncated}\n\n"
            f"Score this report on each of the four dimensions from 1 to 10.\n\n"
            f"Dimension definitions:\n"
            f"1. **Comprehensiveness** — Does it cover ALL key aspects of the question "
            f"   (not just the easy parts)?\n"
            f"2. **Accuracy** — Are claims plausible and grounded in real tools, "
            f"   papers, or documented behaviour? Fabricated facts = 1.\n"
            f"3. **Structure** — Clear title, logical section order, easy to navigate? "
            f"   Wall-of-text = 1.\n"
            f"4. **Specificity** — Named tools, concrete numbers, real tradeoffs? "
            f"   Generic waffle = 1.\n\n"
            f"Respond with ONLY a JSON object — no markdown fences:\n"
            f'{{"comprehensiveness": <1-10>, "accuracy": <1-10>, '
            f'"structure": <1-10>, "specificity": <1-10>, '
            f'"reasoning": "<one sentence per dimension>"}}'
        )

        response = self.client.messages.create(
            model=self.GRADING_MODEL,
            max_tokens=400,
            system=GRADER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        return self._parse_grade(response.content[0].text)

    def grade_run(
        self,
        questions: List[str],
        reports: List[str],
    ) -> Tuple[float, List[GradeResult]]:
        """
        Grade a full set of reports (one per question).

        Returns:
            (average_score, list_of_GradeResult)

        average_score is the single comparable scalar used by the runner to
        decide keep/discard — analogous to val_bpb in Karpathy's train.py.
        """
        grades: List[GradeResult] = []
        for question, report in zip(questions, reports):
            try:
                grade = self.grade_report(question, report)
                grades.append(grade)
                print(
                    f"  [Grader] {question[:55]}... => {grade}"
                )
            except Exception as exc:
                print(f"  [Grader] ERROR grading report: {exc}. Using neutral 5.0.")
                grades.append(GradeResult(5.0, 5.0, 5.0, 5.0, reasoning="parse error"))

        avg = sum(g.total for g in grades) / len(grades) if grades else 0.0
        return avg, grades

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_grade(self, raw: str) -> GradeResult:
        """Extract a GradeResult from the raw model response."""
        text = raw.strip()

        # Strip markdown fences if the model wrapped its output
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()

        # Isolate the JSON object
        obj_match = re.search(r"\{[\s\S]*\}", text)
        if not obj_match:
            raise ValueError(f"No JSON object found in grader response: {raw[:200]}")

        data = json.loads(obj_match.group())

        def _clamp(v, lo=1.0, hi=10.0) -> float:
            return max(lo, min(hi, float(v)))

        return GradeResult(
            comprehensiveness=_clamp(data.get("comprehensiveness", 5)),
            accuracy=_clamp(data.get("accuracy", 5)),
            structure=_clamp(data.get("structure", 5)),
            specificity=_clamp(data.get("specificity", 5)),
            reasoning=str(data.get("reasoning", "")),
        )
