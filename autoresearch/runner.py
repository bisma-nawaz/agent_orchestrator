"""
Autoresearch experiment loop — Layer 2 of the Self-Improving Research Orchestrator.

Analogy to Karpathy's autoresearch / train.py:
  train.py hyperparameters  ↔  orchestrator_config.json
  val_bpb                   ↔  grader average score (1-10)
  keep / discard            ↔  same semantics
  results log               ↔  results.tsv

Loop structure (mirrors Karpathy's autoresearch loop):
  0. Baseline  — run orchestrator on 3 fixed questions, compute score
  1. Propose   — LLM suggests ONE config change
  2. Apply     — mutate a copy of the current config
  3. Evaluate  — run orchestrator with candidate config, score outputs
  4. Decide    — keep if score improved, otherwise revert
  5. Log       — append row to results.tsv
  6. Repeat    — go to 1

Anti-gaming safeguards:
  - The proposer receives the full experiment history so it can avoid re-trying
    previously failed changes.
  - The proposer is explicitly told NOT to suggest formatting-only changes.
  - The grader uses a skeptical system prompt with a different model than the
    orchestrator to prevent self-grading inflation.
  - Score ties (delta == 0) are treated as "discard" to avoid drifting sideways.
"""

import asyncio
import csv
import json
import os
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from anthropic import Anthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup — allow running as a script from the autoresearch/ directory
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent
_PROJECT_ROOT = _HERE.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from orchestrator.orchestrator import DEFAULT_ORCHESTRATOR_CONFIG, ResearchOrchestrator  # noqa: E402
from autoresearch.grader import GradeResult, Grader  # noqa: E402

load_dotenv()

# ---------------------------------------------------------------------------
# The three fixed benchmark questions (use these exactly as specified)
# ---------------------------------------------------------------------------
FIXED_QUESTIONS: List[str] = [
    "What are the tradeoffs between RAG and fine-tuning for enterprise knowledge bases?",
    "How do multi-agent systems handle failures and error recovery in production?",
    "What is MCP (Model Context Protocol) and how does it compare to direct API integrations?",
]

# ---------------------------------------------------------------------------
# LLM proposer — suggests config modifications to try
# ---------------------------------------------------------------------------
PROPOSER_SYSTEM_PROMPT = """\
You are an expert at improving multi-agent research systems.
Your job is to suggest ONE specific, substantive modification to the orchestrator
configuration that will measurably improve the quality (not just the appearance)
of its research reports.

The orchestrator pipeline:
  1. Planner   — breaks the question into N subtasks (roles + focus areas)
  2. Agents    — each role gets its own system prompt and runs for max_turns turns
  3. Synthesiser — merges agent outputs into a final markdown report
  4. (Optional) Verifier — second-pass LLM to patch gaps

Available agent roles (each has a tuned prompt file in orchestrator/prompts/):
  technical_researcher, practical_analyst, domain_expert,
  comparative_analyst, performance_analyst,
  cost_and_operations_analyst, security_and_compliance_researcher

Configurable levers:
  planning.num_agents          (int, 2–4)
  planning.instruction_modifier (str — appended to planner prompt)
  agents.roles                 (list of role names, length = num_agents)
  agents.max_turns             (int, 5–15)
  synthesis.style              ("comprehensive" | "executive" | "comparative")
  synthesis.prompt_modifier    (str — extra requirement added to synthesis prompt)
  synthesis.include_verification (bool)

Rules:
  - Suggest exactly ONE change per response.
  - Changes must target substance, not surface formatting.
  - Do NOT repeat a change that already appears in the experiment history.
  - Think about what is most likely to raise the grader's four dimensions:
    comprehensiveness, accuracy, structure, specificity.
"""

class AutoresearchRunner:
    """
    Autonomous experiment loop that improves the orchestrator configuration.

    Usage:
        runner = AutoresearchRunner()
        asyncio.run(runner.run_loop(n_iterations=5))
    """

    PROPOSER_MODEL = "claude-haiku-4-5"

    def __init__(
        self,
        api_key: Optional[str] = None,
        results_file: Optional[str] = None,
        reports_dir: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set")

        self.client = Anthropic(api_key=self.api_key)
        self.grader = Grader(api_key=self.api_key)

        self.results_file = Path(results_file or _HERE / "results.tsv")
        self.config_file = _HERE / "orchestrator_config.json"
        self.reports_dir = Path(reports_dir or _HERE / "reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # In-memory history fed back to the proposer
        self.experiment_history: List[Dict[str, Any]] = []

        self._ensure_results_file()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_loop(self, n_iterations: int = 5) -> Tuple[float, Dict[str, Any]]:
        """
        Run the full autoresearch loop for ``n_iterations`` experiments.

        Returns (best_score, best_config).
        """
        self._header(f"AUTORESEARCH LOOP — {n_iterations} iterations")

        current_config = self._load_config()

        # ── Step 0: Baseline ────────────────────────────────────────────
        self._section("Step 0: Baseline")
        baseline_reports = await self._run_orchestrator(current_config, tag="baseline")
        baseline_score, baseline_grades = self.grader.grade_run(
            FIXED_QUESTIONS, baseline_reports
        )
        self._print_grades(baseline_grades, baseline_score)
        self._log(
            attempt=0,
            score=baseline_score,
            delta=0.0,
            status="baseline",
            mod_type="baseline",
            description="Initial baseline — no changes",
            config=current_config,
        )
        self.experiment_history.append(
            {
                "attempt": 0,
                "score": baseline_score,
                "status": "baseline",
                "description": "baseline",
            }
        )
        best_score = baseline_score

        # ── Steps 1–N: Experiment loop ───────────────────────────────────
        for iteration in range(1, n_iterations + 1):
            self._section(f"Iteration {iteration}/{n_iterations}")

            # Step 1: Propose
            print("[Propose]")
            try:
                modification = self._propose(current_config, best_score)
                print(f"  Type:  {modification['type']}")
                print(f"  Why:   {modification['description']}")
                print(f"  Changes: {json.dumps(modification['changes'])}")
            except Exception as exc:
                print(f"  Proposal failed: {exc} — skipping iteration.")
                continue

            # Step 2: Apply
            print("[Apply]")
            candidate_config = self._apply(current_config, modification)

            # Step 3: Evaluate
            print("[Evaluate]")
            try:
                candidate_reports = await self._run_orchestrator(
                    candidate_config, tag=f"iter{iteration}"
                )
                candidate_score, candidate_grades = self.grader.grade_run(
                    FIXED_QUESTIONS, candidate_reports
                )
                self._print_grades(candidate_grades, candidate_score)
            except Exception as exc:
                print(f"  Evaluation crashed: {exc}")
                self._log(
                    attempt=iteration,
                    score=best_score,
                    delta=0.0,
                    status="error",
                    mod_type=modification.get("type", "?"),
                    description=f"EVAL ERROR: {modification['description']}",
                    config=candidate_config,
                )
                self.experiment_history.append(
                    {
                        "attempt": iteration,
                        "score": best_score,
                        "status": "error",
                        "description": modification["description"],
                    }
                )
                continue

            # Step 4: Decide
            delta = candidate_score - best_score
            if delta > 0:
                status = "keep"
                current_config = candidate_config
                best_score = candidate_score
                self._save_config(current_config)
                print(f"[Decide] KEEP  delta={delta:+.3f}  new best={best_score:.3f}")
            else:
                status = "discard"
                print(
                    f"[Decide] DISCARD  delta={delta:+.3f}  "
                    f"(best stays at {best_score:.3f})"
                )

            # Step 5: Log
            self._log(
                attempt=iteration,
                score=candidate_score,
                delta=delta,
                status=status,
                mod_type=modification.get("type", "?"),
                description=modification["description"],
                config=candidate_config,
            )
            self.experiment_history.append(
                {
                    "attempt": iteration,
                    "score": candidate_score,
                    "status": status,
                    "description": modification["description"],
                }
            )

        # ── Final summary ────────────────────────────────────────────────
        self._header("AUTORESEARCH COMPLETE")
        print(f"Baseline score : {baseline_score:.3f}")
        print(f"Final best     : {best_score:.3f}")
        print(f"Total gain     : {best_score - baseline_score:+.3f}")
        print(f"Results saved  : {self.results_file}")
        print(f"Best config    : {self.config_file}")

        return best_score, current_config

    # ------------------------------------------------------------------
    # Orchestrator runner
    # ------------------------------------------------------------------

    async def _run_orchestrator(
        self, config: Dict[str, Any], tag: str = ""
    ) -> List[str]:
        """Run the orchestrator on all three benchmark questions."""
        reports: List[str] = []
        orchestrator = ResearchOrchestrator(
            api_key=self.api_key,
            verbose=False,
            config=config,
        )

        for idx, question in enumerate(FIXED_QUESTIONS, 1):
            print(f"  [{idx}/3] {question[:65]}...")
            try:
                # Save each report to disk for manual inspection
                out_file = (
                    self.reports_dir
                    / f"{tag}_q{idx}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                )
                report = await orchestrator.orchestrate(
                    question=question,
                    output_file=str(out_file),
                )
                reports.append(report)
                print(f"       done ({len(report):,} chars) → {out_file.name}")
            except Exception as exc:
                print(f"       FAILED: {exc}")
                reports.append(
                    f"# Error\n\nReport generation failed for: {question}\n\nError: {exc}"
                )

        return reports

    # ------------------------------------------------------------------
    # Proposer
    # ------------------------------------------------------------------

    def _propose(
        self, current_config: Dict[str, Any], best_score: float
    ) -> Dict[str, Any]:
        """Ask the LLM to suggest ONE config change."""
        history_lines = "\n".join(
            f"  #{e['attempt']:02d} [{e['status']:7s}] score={e['score']:.3f} — {e['description']}"
            for e in self.experiment_history[-8:]
        ) or "  (none yet)"

        prompt = (
            f"Current best config:\n{json.dumps(current_config, indent=2)}\n\n"
            f"Current best score: {best_score:.3f} / 10.0\n"
            f"(Score = average of comprehensiveness, accuracy, structure, specificity)\n\n"
            f"Recent experiment history (avoid repeating these):\n{history_lines}\n\n"
            f"Suggest ONE change. Respond with ONLY valid JSON — no markdown fences:\n"
            f'{{"type": "<lever name>", '
            f'"description": "<what you change and WHY it will help>", '
            f'"changes": {{<dot-path-key>: <new-value>, ...}}}}'
        )

        response = self.client.messages.create(
            model=self.PROPOSER_MODEL,
            max_tokens=500,
            system=PROPOSER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
        if fence:
            raw = fence.group(1).strip()

        obj_match = re.search(r"\{[\s\S]*\}", raw)
        if not obj_match:
            raise ValueError(f"No JSON found in proposer response: {raw[:300]}")

        return json.loads(obj_match.group())

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    def _apply(
        self, config: Dict[str, Any], modification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Return a new config with the proposed ``changes`` applied.
        Uses dot-notation keys, e.g. "agents.max_turns" → config["agents"]["max_turns"].
        """
        new_cfg = deepcopy(config)
        new_cfg["version"] = config.get("version", 0) + 1

        for dot_path, value in modification.get("changes", {}).items():
            parts = dot_path.split(".")
            target = new_cfg
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

        return new_cfg

    def _load_config(self) -> Dict[str, Any]:
        """Load saved config, falling back to the default."""
        if self.config_file.exists():
            with open(self.config_file, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            print(f"[Config] Loaded existing config v{loaded.get('version', '?')} from {self.config_file}")
            return loaded
        print("[Config] No saved config found — using defaults.")
        return deepcopy(DEFAULT_ORCHESTRATOR_CONFIG)

    def _save_config(self, config: Dict[str, Any]) -> None:
        """Persist the current best config."""
        with open(self.config_file, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
        print(f"[Config] Saved v{config.get('version', '?')} → {self.config_file}")

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _ensure_results_file(self) -> None:
        if not self.results_file.exists():
            with open(self.results_file, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh, delimiter="\t")
                writer.writerow(
                    [
                        "attempt",
                        "timestamp",
                        "score",
                        "delta",
                        "status",
                        "modification_type",
                        "description",
                        "config_snapshot",
                    ]
                )

    def _log(
        self,
        attempt: int,
        score: float,
        delta: float,
        status: str,
        mod_type: str,
        description: str,
        config: Dict[str, Any],
    ) -> None:
        with open(self.results_file, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(
                [
                    attempt,
                    datetime.now().isoformat(timespec="seconds"),
                    f"{score:.4f}",
                    f"{delta:+.4f}",
                    status,
                    mod_type,
                    description,
                    json.dumps(config, separators=(",", ":")),
                ]
            )

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _header(self, title: str) -> None:
        print(f"\n{'='*65}")
        print(f"  {title}")
        print(f"{'='*65}")

    def _section(self, title: str) -> None:
        print(f"\n{'─'*65}")
        print(f"  {title}")
        print(f"{'─'*65}")

    def _print_grades(
        self, grades: List[GradeResult], avg: float
    ) -> None:
        for idx, (q, g) in enumerate(zip(FIXED_QUESTIONS, grades), 1):
            print(f"  Q{idx}: {g}  | {q[:55]}...")
        print(f"  ─── Average: {avg:.3f} / 10.0")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the autoresearch loop to improve the orchestrator."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Number of experiment iterations (default: 5)",
    )
    parser.add_argument(
        "--results",
        type=str,
        default=None,
        help="Path to results TSV file (default: autoresearch/results.tsv)",
    )
    args = parser.parse_args()

    runner = AutoresearchRunner(results_file=args.results)
    await runner.run_loop(n_iterations=args.iterations)


if __name__ == "__main__":
    asyncio.run(main())
