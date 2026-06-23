"""
Multi-Agent Research Orchestrator
==================================
All orchestration steps (classify, context-gather, plan, synthesise, review)
run as real Claude Agent SDK agents — no raw Anthropic API calls in the
orchestration pipeline.

Pipeline (each step is optional via config):
  1. _classify_question  — validates & refines the input question
  2. _gather_context     — pre-research context sprint (WebSearch)
  3. plan_research       — SDK planner agent → subtasks with per-agent max_turns
  4. run_agents_concurrently — parallel specialist SDK agents (with MCP + retry)
  5. synthesize_results  — SDK synthesiser agent → markdown report
  6. _quality_review     — SDK reviewer → optional revision pass
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from claude_agent_sdk import ClaudeAgentOptions, query
from dotenv import load_dotenv

load_dotenv()

# Project root (parent of `orchestrator/`) — used for Google Drive MCP OAuth path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GDRIVE_OAUTH_PATH = str(_PROJECT_ROOT / ".gdrive_oauth.json")

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_ORCHESTRATOR_CONFIG: Dict[str, Any] = {
    "version": 0,
    # ── Input validation & pre-research ────────────────────────────────────
    "input": {
        "classify_question": True,   # run classifier agent before anything else
        "gather_context": True,      # run context-gathering agent before planning
    },
    # ── Planning ────────────────────────────────────────────────────────────
    "planning": {
        "num_agents": 3,
        "instruction_modifier": "",  # appended verbatim to planner prompt
        "dynamic_turns": True,       # let planner decide max_turns per agent
    },
    # ── Sub-agents ──────────────────────────────────────────────────────────
    "agents": {
        "roles": ["technical_researcher", "practical_analyst", "domain_expert"],
        "max_turns": 10,             # fallback when dynamic_turns=False
        "retry_failed": True,        # re-spawn failed agent with partial context
        "max_retries": 1,
        # MCP server configs passed directly to ClaudeAgentOptions (sub-agents).
        # Google Drive: requires `npx`, OAuth file from setup_gdrive_mcp.py / .gdrive_oauth.json
        "mcp_servers": [
            {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-gdrive"],
                "env": {"GDRIVE_OAUTH_PATH": _GDRIVE_OAUTH_PATH},
            }
        ],
    },
    # ── Synthesis & review ──────────────────────────────────────────────────
    "synthesis": {
        "style": "comprehensive",        # "comprehensive" | "executive" | "comparative"
        "prompt_modifier": "",           # extra requirement injected into synthesiser
        "include_verification": False,   # legacy key — kept for back-compat
        "quality_review": True,          # run quality-reviewer agent after synthesis
        "max_review_iterations": 1,      # max revision loops (bounded)
    },
}

# Style → instruction text injected into synthesizer prompt
_STYLE_INSTRUCTIONS: Dict[str, str] = {
    "comprehensive": (
        "Create a comprehensive, in-depth report with detailed sections, "
        "concrete examples, and nuanced analysis."
    ),
    "executive": (
        "Create a concise executive-summary style report: key findings up front, "
        "structured bullet points, clear bottom-line recommendation."
    ),
    "comparative": (
        "Structure the report as a systematic comparison: use a markdown table to "
        "highlight tradeoffs between the main approaches, then explain each row."
    ),
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class ResearchOrchestrator:
    """
    Multi-agent research orchestrator.

    Every step in the pipeline is implemented as a real Claude Agent SDK agent.
    The only external Anthropic calls that remain raw API calls are in
    autoresearch/grader.py — which is intentionally a separate evaluator.

    Pass an optional ``config`` dict to override any subset of
    DEFAULT_ORCHESTRATOR_CONFIG. The autoresearch runner mutates this between
    experiments to discover improvements.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        verbose: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable must be set")

        # Set API key for the SDK (it reads from env)
        os.environ["ANTHROPIC_API_KEY"] = self.api_key

        self.verbose = verbose

        # Deep-merge provided config on top of defaults (per-section)
        self.config: Dict[str, Any] = {}
        for section, defaults in DEFAULT_ORCHESTRATOR_CONFIG.items():
            if isinstance(defaults, dict):
                self.config[section] = {**defaults, **(config or {}).get(section, {})}
            else:
                self.config[section] = (config or {}).get(section, defaults)

        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompts_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, message: str, level: str = "INFO") -> None:
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] [{level}] {message}")

    def _log_sdk_stderr(self, line: str) -> None:
        """Surface Claude SDK subprocess stderr lines in orchestrator logs."""
        if line:
            self.log(f"[SDK STDERR] {line}", "ERROR")

    # ------------------------------------------------------------------
    # Core SDK helper — ALL orchestrator LLM calls go through here
    # ------------------------------------------------------------------

    async def _run_sdk_agent(
        self,
        prompt: str,
        system_prompt: str,
        tools: Optional[List[str]] = None,
        max_turns: int = 1,
        mcp_servers: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Run a single-purpose SDK agent and return its accumulated text output.

        This is the single choke-point that replaces all raw
        client.messages.create() calls inside the orchestrator.
        """
        options_kwargs: Dict[str, Any] = {
            "system_prompt": system_prompt,
            "allowed_tools": tools or [],
            "max_turns": max_turns,
            "stderr": self._log_sdk_stderr,
        }
        if mcp_servers:
            options_kwargs["mcp_servers"] = mcp_servers

        options = ClaudeAgentOptions(**options_kwargs)

        output_parts: List[str] = []
        async for msg in query(prompt=prompt, options=options):
            if hasattr(msg, "content") and msg.content:
                content_str = str(msg.content)
                output_parts.append(content_str)
                if self.verbose and "tool" in content_str.lower():
                    self.log(f"  [SDK] tool use detected", "DEBUG")

        return "\n".join(output_parts).strip()

    # ------------------------------------------------------------------
    # JSON extraction helper (reused from original)
    # ------------------------------------------------------------------

    def _extract_json_array(self, raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            raise ValueError("Response was empty")
        if "```" in text:
            fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
            if fence:
                text = fence.group(1).strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return text

    def _extract_json_object(self, raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if "```" in text:
            fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
            if fence:
                text = fence.group(1).strip()
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError(f"No JSON object found in: {text[:200]}")
        return json.loads(match.group())

    # ------------------------------------------------------------------
    # Step 0a: Question classifier
    # ------------------------------------------------------------------

    async def _classify_question(self, question: str) -> Dict[str, Any]:
        """
        Validate that the input is a researchable question and refine its wording.

        Returns:
            {"is_research": bool, "refined_question": str, "reason": str}
        """
        self.log("Classifying question...")
        system = self.get_agent_prompt("question_classifier", "")
        raw = await self._run_sdk_agent(question, system, tools=[], max_turns=1)
        try:
            result = self._extract_json_object(raw)
            result.setdefault("is_research", True)
            result.setdefault("refined_question", question)
            result.setdefault("reason", "")
            self.log(
                f"Classifier: is_research={result['is_research']}  "
                f"refined='{result['refined_question'][:70]}'"
            )
            return result
        except Exception as exc:
            self.log(f"Classifier parse error ({exc}), treating as research question", "WARNING")
            return {"is_research": True, "refined_question": question, "reason": "parse error"}

    # ------------------------------------------------------------------
    # Step 0b: Context gatherer
    # ------------------------------------------------------------------

    async def _gather_context(self, question: str) -> str:
        """
        Run a pre-research context sprint from Google Drive/MCP sources.
        Returns a structured context block (markdown) injected into downstream prompts.
        """
        self.log("Gathering pre-research context...")
        system = self.get_agent_prompt("context_gatherer", "")
        mcp_cfg = self.config["agents"].get("mcp_servers") or None
        context = await self._run_sdk_agent(
            question,
            system,
            tools=["Read"],
            max_turns=3,
            mcp_servers=mcp_cfg,
        )
        self.log(f"Context gathered ({len(context)} chars)")
        return context

    # ------------------------------------------------------------------
    # Step 1: Orchestrator-native planning (no planner agent)
    # ------------------------------------------------------------------

    def plan_research(
        self, question: str, context: str = ""
    ) -> List[Dict[str, str]]:
        """
        Synchronous wrapper — calls the async planner internally via asyncio.
        Returns a list of subtask dicts: role, task, focus, max_turns.
        """
        return asyncio.get_event_loop().run_until_complete(
            self._plan_research_async(question, context)
        )

    async def _plan_research_async(
        self, question: str, context: str = ""
    ) -> List[Dict[str, Any]]:
        self.log(f"Planning research for: {question}")
        num_agents = int(self.config["planning"].get("num_agents", 3))
        preferred_roles = self.config["agents"].get("roles", [])
        role_pool = preferred_roles or [
            "technical_researcher",
            "practical_analyst",
            "domain_expert",
        ]
        roles = role_pool[:num_agents]

        subtasks: List[Dict[str, Any]] = []
        for idx, role in enumerate(roles):
            task, focus = self._build_subtask_for_role(question, role, context)
            max_turns = self._decide_task_max_turns(question, role, task, context)
            subtasks.append(
                {
                    "role": role,
                    "task": task,
                    "focus": focus,
                    "max_turns": max_turns,
                }
            )

        self.log(f"Created {len(subtasks)} subtasks")
        for i, t in enumerate(subtasks, 1):
            self.log(f"  {i}. {t['role']} (turns={t['max_turns']}): {t['task'][:60]}...")
        return subtasks

    def _build_subtask_for_role(self, question: str, role: str, context: str = "") -> tuple[str, str]:
        """Top-level orchestrator assigns role-specific subtasks (no planner agent)."""
        context_hint = " Use the gathered context to prioritize named systems and benchmarks." if context else ""
        role_map: Dict[str, Dict[str, str]] = {
            "technical_researcher": {
                "focus": "Architecture, mechanisms, implementation details, and technical constraints",
                "task": (
                    f"Analyze the technical foundations of this question: {question}. "
                    f"Cover architecture patterns, system behavior, and implementation tradeoffs.{context_hint}"
                ),
            },
            "practical_analyst": {
                "focus": "Production practices, adoption patterns, and real-world deployment lessons",
                "task": (
                    f"Investigate practical real-world implementation lessons for: {question}. "
                    f"Highlight case studies, common pitfalls, and operational guidance.{context_hint}"
                ),
            },
            "domain_expert": {
                "focus": "Domain landscape, market trends, policy/regulatory implications",
                "task": (
                    f"Assess the domain and strategic context for: {question}. "
                    f"Cover ecosystem trends, major players, and regulatory or governance considerations.{context_hint}"
                ),
            },
            "comparative_analyst": {
                "focus": "Direct comparison framework, evaluation criteria, and decision matrix",
                "task": (
                    f"Build a structured comparison for: {question}. "
                    f"Compare options side-by-side with explicit tradeoffs and selection guidance.{context_hint}"
                ),
            },
            "performance_analyst": {
                "focus": "Benchmarks, latency/throughput/scalability behavior, and performance bottlenecks",
                "task": (
                    f"Research performance evidence relevant to: {question}. "
                    f"Prioritize benchmark data, scaling behavior, and measurable bottlenecks.{context_hint}"
                ),
            },
            "cost_and_operations_analyst": {
                "focus": "Cost model, operational burden, and total cost of ownership",
                "task": (
                    f"Evaluate cost and operations considerations for: {question}. "
                    f"Include pricing drivers, maintenance overhead, and reliability operations.{context_hint}"
                ),
            },
            "security_and_compliance_researcher": {
                "focus": "Security risks, controls, and compliance obligations",
                "task": (
                    f"Analyze security and compliance implications for: {question}. "
                    f"Identify key risks, mitigations, and likely compliance requirements.{context_hint}"
                ),
            },
        }
        default_task = (
            f"Research this question from the {role.replace('_', ' ')} perspective: {question}. "
            f"Provide specific findings, tradeoffs, and implementation implications.{context_hint}"
        )
        details = role_map.get(
            role,
            {
                "focus": f"Specialist analysis as a {role.replace('_', ' ')}",
                "task": default_task,
            },
        )
        return details["task"], details["focus"]

    def _decide_task_max_turns(
        self, question: str, role: str, task: str, context: str = ""
    ) -> int:
        """
        Orchestrator-owned turn budgeting.
        - If planning.dynamic_turns is disabled, use agents.max_turns.
        - Otherwise compute a bounded role/complexity-aware budget.
        """
        fallback = int(self.config["agents"].get("max_turns", 10))
        if not self.config["planning"].get("dynamic_turns", True):
            return max(3, min(15, fallback))

        text = f"{question} {task}".lower()
        complexity = 0
        if any(k in text for k in ("compare", "tradeoff", "vs", "versus")):
            complexity += 1
        if any(k in text for k in ("architecture", "distributed", "failure", "recovery", "scalability")):
            complexity += 1
        if any(k in text for k in ("security", "compliance", "regulation", "risk")):
            complexity += 1
        if context:
            complexity += 1

        role_base: Dict[str, int] = {
            "technical_researcher": 9,
            "practical_analyst": 8,
            "domain_expert": 8,
            "comparative_analyst": 9,
            "performance_analyst": 10,
            "cost_and_operations_analyst": 8,
            "security_and_compliance_researcher": 10,
        }
        base = role_base.get(role, 8)
        budget = base + complexity
        return max(3, min(15, budget))

    # ------------------------------------------------------------------
    # Step 2: Sub-agent execution (with per-task turns + retry + MCP)
    # ------------------------------------------------------------------

    async def spawn_sub_agent(
        self,
        task: Dict[str, Any],
        context: str = "",
        retry_count: int = 0,
        partial_output: str = "",
    ) -> Dict[str, Any]:
        """
        Spawn a specialist sub-agent via the Claude Agent SDK.

        Supports:
        - Per-task max_turns (set by the planner or config fallback)
        - MCP server injection for Google Drive / PDF retrieval
        - Retry with partial-output context on failure
        """
        role = task.get("role", "researcher")
        task_description = task.get("task", "")
        focus = task.get("focus", "")
        # Dynamic turns: task-level first, then config fallback
        max_turns = int(
            task.get("max_turns") or self.config["agents"].get("max_turns", 10)
        )

        if retry_count > 0:
            self.log(f"Retrying {role} agent (attempt {retry_count + 1})...")
            prompt = (
                f"RECOVERY — previous attempt produced partial results.\n\n"
                f"Partial output so far:\n{partial_output or '(none)'}\n\n"
                f"Continue where it left off. Original task:\n{task_description}"
            )
        else:
            self.log(f"Spawning {role} agent (max_turns={max_turns})...")
            prompt = task_description

        variables = {
            "question": task_description,
            "focus": focus,
            "context": context[:500] if context else "",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        system = self.get_agent_prompt(role, focus, variables=variables)
        mcp_cfg = self.config["agents"].get("mcp_servers") or None

        result: Dict[str, Any] = {
            "role": role,
            "task": task_description,
            "output": "",
            "status": "pending",
            "error": None,
        }

        try:
            raw = await self._run_sdk_agent(
                prompt,
                system,
                tools=["Read", "Bash", "WebSearch"],
                max_turns=max_turns,
                mcp_servers=mcp_cfg,
            )
            result["output"] = raw
            result["status"] = "completed"
            self.log(f"{role} agent completed ({len(raw)} chars)")

        except asyncio.TimeoutError:
            self.log(f"{role} agent timed out", "WARNING")
            result["status"] = "timeout"
            result["error"] = "Agent execution timed out"

        except Exception as exc:
            self.log(f"{role} agent failed: {exc}", "ERROR")
            result["status"] = "failed"
            result["error"] = str(exc)

        return result

    async def run_agents_concurrently(
        self, subtasks: List[Dict[str, Any]], context: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Run all specialist agents concurrently.
        Failed/timed-out agents are retried once with their partial output as context.
        """
        self.log(f"Running {len(subtasks)} agents concurrently...")
        retry_cfg = self.config["agents"]
        retry_failed = retry_cfg.get("retry_failed", True)
        max_retries = int(retry_cfg.get("max_retries", 1))

        # Build initial tasks
        indexed = [
            (i, asyncio.create_task(self.spawn_sub_agent(task, context=context)))
            for i, task in enumerate(subtasks)
        ]

        done, pending = await asyncio.wait(
            [t for _, t in indexed], timeout=180
        )
        if pending:
            self.log("Overall timeout reached — cancelling stragglers", "WARNING")
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        task_lookup = {t: i for i, t in indexed}
        results: List[Optional[Dict[str, Any]]] = [None] * len(subtasks)

        for task_obj, idx in task_lookup.items():
            if task_obj in done:
                res = task_obj.result()
                results[idx] = res if not isinstance(res, Exception) else {
                    "role": subtasks[idx]["role"],
                    "task": subtasks[idx]["task"],
                    "output": "",
                    "status": "failed",
                    "error": str(res),
                }
            else:
                results[idx] = {
                    "role": subtasks[idx]["role"],
                    "task": subtasks[idx]["task"],
                    "output": "",
                    "status": "timeout",
                    "error": "Did not finish before overall timeout",
                }

        # ── Retry / respawn passes ───────────────────────────────────────
        if retry_failed and max_retries > 0:
            for retry_attempt in range(1, max_retries + 1):
                retry_tasks = []
                for idx, res in enumerate(results):
                    if res and res["status"] in ("failed", "timeout"):
                        self.log(
                            f"Respawning {res['role']} for slot {idx + 1} "
                            f"(attempt {retry_attempt + 1}/{max_retries + 1})..."
                        )
                        retry_tasks.append(
                            (
                                idx,
                                asyncio.create_task(
                                    self.spawn_sub_agent(
                                        subtasks[idx],
                                        context=context,
                                        retry_count=retry_attempt,
                                        partial_output=res.get("output", ""),
                                    )
                                ),
                            )
                        )

                if not retry_tasks:
                    break

                done2, pending2 = await asyncio.wait(
                    [t for _, t in retry_tasks], timeout=180
                )
                for t2 in pending2:
                    t2.cancel()
                await asyncio.gather(*pending2, return_exceptions=True)

                for idx, task_obj2 in retry_tasks:
                    if task_obj2 in done2:
                        retry_res = task_obj2.result()
                        if not isinstance(retry_res, Exception):
                            results[idx] = retry_res

        successful = sum(1 for r in results if r and r["status"] == "completed")
        self.log(f"Agents completed: {successful}/{len(results)} successful")
        return [r for r in results if r is not None]

    # ------------------------------------------------------------------
    # Step 3: Synthesiser (SDK agent, replaces raw API)
    # ------------------------------------------------------------------

    async def synthesize_results(
        self,
        question: str,
        agent_results: List[Dict[str, Any]],
        context: str = "",
    ) -> str:
        """Merge all agent outputs into a coherent markdown report via SDK agent."""
        self.log("Synthesising results into final report...")

        synthesis_cfg = self.config.get("synthesis", {})
        style = synthesis_cfg.get("style", "comprehensive")
        prompt_modifier = synthesis_cfg.get("prompt_modifier", "") or ""
        style_instruction = _STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS["comprehensive"])

        # Build the findings block
        findings = f"**Original question:** {question}\n\n**Agent findings:**\n\n"
        for res in agent_results:
            header = res["role"].replace("_", " ").title()
            if res["status"] == "completed":
                findings += f"### {header}\nTask: {res['task']}\n\n{res['output'][:2500]}\n\n"
            else:
                findings += (
                    f"### {header}\nStatus: {res['status']}"
                    + (f" — {res['error']}" if res["error"] else "")
                    + "\n\n"
                )

        system = self.get_agent_prompt(
            "synthesizer",
            "",
            variables={
                "style_instruction": style_instruction,
                "prompt_modifier": prompt_modifier or "None.",
                "context": context or "No pre-research context available.",
            },
        )

        report = await self._run_sdk_agent(
            findings, system, tools=[], max_turns=3
        )
        self.log(f"Synthesis complete ({len(report)} chars)")
        return report

    # ------------------------------------------------------------------
    # Step 4: Quality reviewer (SDK agent, replaces _verify_report)
    # ------------------------------------------------------------------

    async def _quality_review(
        self, question: str, report: str, iteration: int = 0
    ) -> str:
        """
        Review the report and optionally trigger a revision pass.
        Bounded by synthesis.max_review_iterations.
        """
        max_iters = int(
            self.config.get("synthesis", {}).get("max_review_iterations", 1)
        )
        if iteration >= max_iters:
            return report

        self.log(f"Quality review (iteration {iteration + 1}/{max_iters})...")

        system = self.get_agent_prompt("quality_reviewer", "")
        review_prompt = (
            f"**Original research question:** {question}\n\n"
            f"**Report to review:**\n{report[:4000]}"
        )
        raw = await self._run_sdk_agent(
            review_prompt, system, tools=[], max_turns=2
        )

        try:
            review = self._extract_json_object(raw)
        except Exception as exc:
            self.log(f"Quality reviewer parse error ({exc}), skipping revision", "WARNING")
            return report

        scores = review.get("scores", {})
        score_str = "  ".join(f"{k}={v}" for k, v in scores.items())
        self.log(f"Review scores: {score_str}")

        if not review.get("needs_revision", False):
            self.log("Quality reviewer: report is good — no revision needed")
            return report

        self.log(f"Quality reviewer: revision requested — {review.get('critique', '')[:120]}")

        # Build revision prompt from critique + missing aspects
        missing = review.get("missing_aspects", [])
        revision_request = (
            f"The report needs improvement. Critique:\n{review.get('critique', '')}\n\n"
            f"Missing aspects to add: {', '.join(missing) if missing else 'see critique'}\n\n"
            f"Please revise the report to address these gaps. "
            f"Preserve all correct existing content — only add/fix what is flagged.\n\n"
            f"**Report to revise:**\n{report}"
        )

        synthesis_cfg = self.config.get("synthesis", {})
        style = synthesis_cfg.get("style", "comprehensive")
        style_instruction = _STYLE_INSTRUCTIONS.get(style, _STYLE_INSTRUCTIONS["comprehensive"])
        system_rev = self.get_agent_prompt(
            "synthesizer",
            "",
            variables={
                "style_instruction": style_instruction,
                "prompt_modifier": "Focus on addressing the reviewer's critique.",
                "context": "",
            },
        )

        revised = await self._run_sdk_agent(
            revision_request, system_rev, tools=[], max_turns=3
        )
        if not revised.strip():
            self.log("Revision returned empty — keeping original", "WARNING")
            return report

        self.log(f"Revision complete ({len(revised)} chars)")
        # Recurse for next iteration if still below max
        return await self._quality_review(question, revised, iteration + 1)

    # ------------------------------------------------------------------
    # Prompt loading with placeholder variable substitution
    # ------------------------------------------------------------------

    def get_agent_prompt(
        self,
        role: str,
        focus: str,
        variables: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Load a system prompt from `prompts/<role>.txt`.

        Substitutes {{key}} placeholders with values from `variables`.
        Standard automatic variables: {{focus}}, {{date}}.
        Falls back to a generic template if the file does not exist.
        """
        prompt_file = self.prompts_dir / f"{role}.txt"

        if prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as fh:
                prompt = fh.read()
        else:
            prompt = (
                f"You are a specialised {role.replace('_', ' ')} agent.\n"
                f"Your role is to conduct thorough research using available tools.\n\n"
                f"{{{{focus}}}}\n\n"
                f"Guidelines:\n"
                f"- Use WebSearch to find current information\n"
                f"- Use Read to examine files if needed\n"
                f"- Use Bash for technical validation if applicable\n"
                f"- Provide specific, detailed findings with named tools and real data\n"
                f"- Cite sources when possible\n\n"
                f"Research date: {{{{date}}}}"
            )
            # Persist so the autoresearch loop can tune it
            with open(prompt_file, "w", encoding="utf-8") as fh:
                fh.write(prompt)

        # Apply variable substitutions
        all_vars = {
            "focus": focus,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        if variables:
            all_vars.update(variables)

        for key, val in all_vars.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", str(val))

        return prompt

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def orchestrate(
        self, question: str, output_file: Optional[str] = None
    ) -> str:
        """
        Run the full research pipeline for one question.

        Returns the final markdown report string.
        """
        self.log(f"=== Orchestrating: {question[:80]} ===")
        start = datetime.now()
        context = ""

        # ── Step 0a: Classify & refine ────────────────────────────────────
        input_cfg = self.config.get("input", {})
        if input_cfg.get("classify_question", True):
            classification = await self._classify_question(question)
            if not classification.get("is_research", True):
                reason = classification.get("reason", "")
                self.log(f"Not a research question: {reason}", "WARNING")
                report = (
                    f"# Input Not Classified as a Research Question\n\n"
                    f"**Input:** {question}\n\n"
                    f"**Reason:** {reason}\n\n"
                    f"Please provide an open-ended research question to get a full report."
                )
                if output_file:
                    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_file).write_text(report, encoding="utf-8")
                return report
            question = classification.get("refined_question", question)

        # ── Step 0b: Gather context ───────────────────────────────────────
        if input_cfg.get("gather_context", True):
            try:
                context = await self._gather_context(question)
            except Exception as exc:
                self.log(f"Context gathering failed ({exc}), continuing without", "WARNING")

        # ── Step 1: Plan ──────────────────────────────────────────────────
        subtasks = await self._plan_research_async(question, context)

        # ── Step 2: Delegate ──────────────────────────────────────────────
        agent_results = await self.run_agents_concurrently(subtasks, context=context)

        # ── Step 3: Synthesise ────────────────────────────────────────────
        report = await self.synthesize_results(question, agent_results, context)

        # ── Step 4: Quality review ────────────────────────────────────────
        synthesis_cfg = self.config.get("synthesis", {})
        if synthesis_cfg.get("quality_review", True):
            try:
                report = await self._quality_review(question, report)
            except Exception as exc:
                self.log(f"Quality review failed ({exc}), using unreviewed report", "WARNING")

        # ── Output ────────────────────────────────────────────────────────
        if output_file:
            out = Path(output_file)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(report, encoding="utf-8")
            self.log(f"Report saved to: {output_file}")

        elapsed = (datetime.now() - start).total_seconds()
        self.log(f"Orchestration complete in {elapsed:.1f}s")
        return report
