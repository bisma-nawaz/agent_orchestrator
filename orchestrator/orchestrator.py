"""
Multi-Agent Research Orchestrator
This module implements a research system that breaks down questions into subtasks,
delegates them to specialist agents, and synthesizes results into a coherent report.
"""

import asyncio
import json
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from dotenv import load_dotenv
from claude_agent_sdk import query, ClaudeAgentOptions
from anthropic import Anthropic

# Load environment variables from .env if present
load_dotenv()


DEFAULT_ORCHESTRATOR_CONFIG: Dict[str, Any] = {
    "version": 0,
    "planning": {
        "instruction_modifier": "",
        "num_agents": 3,
    },
    "agents": {
        "roles": ["technical_researcher", "practical_analyst", "domain_expert"],
        "max_turns": 10,
    },
    "synthesis": {
        "style": "comprehensive",
        "include_verification": False,
        "prompt_modifier": "",
    },
}


class ResearchOrchestrator:
    """
    Main orchestrator that manages the research process.
    Breaks down questions, spawns sub-agents, collects results, and synthesizes.

    Accepts an optional ``config`` dict that overrides any subset of
    DEFAULT_ORCHESTRATOR_CONFIG.  The autoresearch runner mutates this dict
    between experiments to discover improvements.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        verbose: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the orchestrator with an API key and optional config."""
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable must be set")

        # Initialize Anthropic client for planning and synthesis
        self.client = Anthropic(api_key=self.api_key)
        self.verbose = verbose

        # Merge provided config on top of defaults (shallow merge per section)
        self.config: Dict[str, Any] = {}
        for section, defaults in DEFAULT_ORCHESTRATOR_CONFIG.items():
            if isinstance(defaults, dict):
                self.config[section] = {**defaults, **(config or {}).get(section, {})}
            else:
                self.config[section] = (config or {}).get(section, defaults)

        # Load prompts from files
        self.prompts_dir = Path(__file__).parent / "prompts"
        self.prompts_dir.mkdir(exist_ok=True)

    def log(self, message: str, level: str = "INFO"):
        """Print progress messages if verbose mode is on."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [{level}] {message}")

    def _extract_json_array(self, raw_text: str) -> str:
        """
        Extract a JSON array payload from model output.
        Handles markdown code fences and extra explanatory text.
        """
        text = (raw_text or "").strip()

        if not text:
            raise ValueError("Planning response was empty")

        # Remove common markdown fences if present.
        if "```" in text:
            fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
            if fence_match:
                text = fence_match.group(1).strip()

        # If extra text exists, isolate the first JSON array-like region.
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]

        # Fallback: return original text so json.loads raises a useful error.
        return text

    def plan_research(self, question: str) -> List[Dict[str, str]]:
        """
        Break down a research question into subtasks driven by config.
        Number of subtasks and preferred roles come from self.config["planning"]
        and self.config["agents"].
        """
        self.log(f"Planning research for: {question}")

        num_agents = self.config["planning"].get("num_agents", 3)
        preferred_roles = self.config["agents"].get("roles", [])
        instruction_modifier = self.config["planning"].get("instruction_modifier", "")

        roles_hint = (
            f"\nPrefer these specialist roles (use them as the 'role' field): {preferred_roles}"
            if preferred_roles
            else ""
        )
        modifier_hint = f"\n\nAdditional instruction: {instruction_modifier}" if instruction_modifier else ""

        planning_prompt = (
            f"You are a research coordinator. Break down this research question into exactly "
            f"{num_agents} specific subtasks. Each subtask should be handled by a different "
            f"specialist agent.{roles_hint}"
            f"\n\nResearch Question: {question}"
            f"\n\nCreate subtasks that:"
            f"\n1. Cover different aspects of the question"
            f"\n2. Can be researched independently"
            f"\n3. Together form a comprehensive answer"
            f"{modifier_hint}"
            f"\n\nOutput JSON format:"
            f'\n['
            f'\n    {{'
            f'\n        "role": "technical_researcher",'
            f'\n        "task": "Research the technical implementation details...",'
            f'\n        "focus": "Focus on architecture, algorithms, and technical specifications"'
            f'\n    }},'
            f'\n    ...'
            f'\n]'
            f'\n\nReturn ONLY valid JSON, no other text.'
        )

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1000,
                messages=[{"role": "user", "content": planning_prompt}]
            )

            text_blocks = [
                block.text for block in response.content
                if getattr(block, "type", "") == "text" and hasattr(block, "text")
            ]
            combined_text = "\n".join(text_blocks).strip()
            json_payload = self._extract_json_array(combined_text)
            subtasks = json.loads(json_payload)

            self.log(f"Created {len(subtasks)} subtasks")
            for i, task in enumerate(subtasks, 1):
                self.log(f"  {i}. {task['role']}: {task['task'][:60]}...")

            return subtasks

        except Exception as e:
            self.log(f"Error in planning: {str(e)}", "ERROR")
            # Fallback to default subtasks using configured roles
            fallback_roles = preferred_roles or ["technical_researcher", "practical_analyst"]
            return [
                {
                    "role": role,
                    "task": f"Research aspects of: {question} from the {role.replace('_', ' ')} perspective",
                    "focus": f"Focus on your specialty as a {role.replace('_', ' ')}"
                }
                for role in fallback_roles[:num_agents]
            ]

    async def spawn_sub_agent(self, task: Dict[str, str]) -> Dict[str, Any]:
        """
        Spawn a sub-agent using Claude Agent SDK to handle a specific subtask.
        Each agent runs autonomously with tools for multiple turns.
        """
        role = task.get("role", "researcher")
        task_description = task.get("task", "")
        focus = task.get("focus", "")

        self.log(f"Spawning {role} agent...")

        # Load or create system prompt for this role
        system_prompt = self.get_agent_prompt(role, focus)

        max_turns = self.config["agents"].get("max_turns", 10)

        # Prepare the agent options
        agent_options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=["Read", "Bash", "WebSearch"],
            max_turns=max_turns,
        )

        result = {
            "role": role,
            "task": task_description,
            "output": "",
            "status": "pending",
            "error": None
        }

        try:
            # Run the agent asynchronously and collect output
            agent_output = ""
            async for msg in query(
                prompt=task_description,
                options=agent_options
            ):
                # Collect the agent's output
                if hasattr(msg, 'content'):
                    agent_output += str(msg.content) + "\n"
                    if self.verbose:
                        # Show what tools the agent is using
                        if "tool" in str(msg.content).lower():
                            self.log(f"  {role} is using tools...", "DEBUG")

            result["output"] = agent_output
            result["status"] = "completed"
            self.log(f"{role} agent completed successfully")

        except asyncio.TimeoutError:
            self.log(f"{role} agent timed out", "WARNING")
            result["status"] = "timeout"
            result["error"] = "Agent execution timed out"

        except Exception as e:
            self.log(f"{role} agent failed: {str(e)}", "ERROR")
            result["status"] = "failed"
            result["error"] = str(e)

        return result

    async def run_agents_concurrently(self, subtasks: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        Run all sub-agents concurrently and collect their results.
        Handles failures gracefully - if one agent fails, others continue.
        """
        self.log(f"Running {len(subtasks)} agents concurrently...")

        # Create asyncio tasks so we can preserve completed work on timeout.
        indexed_tasks = [
            (i, asyncio.create_task(self.spawn_sub_agent(task)))
            for i, task in enumerate(subtasks)
        ]

        # Wait for completion with an overall timeout.
        done, pending = await asyncio.wait(
            [task for _, task in indexed_tasks],
            timeout=120  # 2 minute overall timeout
        )

        if pending:
            self.log("Overall execution timeout reached", "WARNING")
            for pending_task in pending:
                pending_task.cancel()
            # Ensure cancellation is consumed and does not leak warnings.
            await asyncio.gather(*pending, return_exceptions=True)

        # Process results and handle exceptions/timeouts per task.
        processed_results = []
        task_lookup = {task_obj: idx for idx, task_obj in indexed_tasks}
        for task_obj in [task for _, task in indexed_tasks]:
            i = task_lookup[task_obj]
            subtask = subtasks[i]

            if task_obj in done:
                result = task_obj.result()
                if isinstance(result, Exception):
                    self.log(f"Agent {i+1} raised exception: {str(result)}", "ERROR")
                    processed_results.append({
                        "role": subtask["role"],
                        "task": subtask["task"],
                        "output": "",
                        "status": "failed",
                        "error": str(result)
                    })
                else:
                    processed_results.append(result)
            else:
                processed_results.append({
                    "role": subtask["role"],
                    "task": subtask["task"],
                    "output": "",
                    "status": "timeout",
                    "error": "Agent did not finish before overall timeout"
                })

        # Log summary
        successful = sum(1 for r in processed_results if r["status"] == "completed")
        self.log(f"Agents completed: {successful}/{len(processed_results)} successful")

        return processed_results

    def synthesize_results(self, question: str, agent_results: List[Dict[str, Any]]) -> str:
        """
        Combine all agent outputs into a coherent markdown report.
        Handles cases where some agents may have failed.
        Respects config: synthesis.style, synthesis.prompt_modifier,
        and synthesis.include_verification.
        """
        self.log("Synthesizing results into final report...")

        synthesis_cfg = self.config.get("synthesis", {})
        style = synthesis_cfg.get("style", "comprehensive")
        prompt_modifier = synthesis_cfg.get("prompt_modifier", "")
        include_verification = synthesis_cfg.get("include_verification", False)

        style_instructions = {
            "comprehensive": (
                "Create a comprehensive, in-depth report with detailed sections, "
                "concrete examples, and nuanced analysis."
            ),
            "executive": (
                "Create a concise executive-summary style report with key findings "
                "up front, structured bullet points, and a clear bottom line."
            ),
            "comparative": (
                "Structure the report as a systematic comparison: use tables or "
                "side-by-side sections to highlight tradeoffs between approaches."
            ),
        }.get(style, "Create a comprehensive markdown report.")

        context = f"Original Question: {question}\n\nAgent Research Results:\n\n"
        for result in agent_results:
            if result["status"] == "completed":
                context += f"### {result['role'].replace('_', ' ').title()}\n"
                context += f"Task: {result['task']}\n\n"
                context += f"{result['output'][:2000]}\n\n"
            else:
                context += f"### {result['role'].replace('_', ' ').title()}\n"
                context += f"Status: {result['status']}\n"
                if result["error"]:
                    context += f"Error: {result['error']}\n\n"

        modifier_section = f"\n\nAdditional requirement: {prompt_modifier}" if prompt_modifier else ""

        synthesis_prompt = (
            f"{context}\n\n"
            f"{style_instructions}\n\n"
            f"Requirements:\n"
            f"1. Directly answer the original question\n"
            f"2. Integrate findings from all successful agents\n"
            f"3. Use clear markdown sections (title, summary, body, conclusion)\n"
            f"4. Include specific named tools, papers, projects, and quantitative data\n"
            f"5. Acknowledge any gaps if agents failed\n"
            f"{modifier_section}\n\n"
            f"Create the report now."
        )

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4000,
                messages=[{"role": "user", "content": synthesis_prompt}]
            )

            report = response.content[0].text
            self.log("Synthesis completed successfully")

            if include_verification:
                report = self._verify_report(question, report)

            return report

        except Exception as e:
            self.log(f"Synthesis failed: {str(e)}", "ERROR")
            report = f"# Research Report: {question}\n\n"
            report += "## Summary\n\nPartial results available due to synthesis error.\n\n"
            for result in agent_results:
                if result["status"] == "completed":
                    report += f"## {result['role'].replace('_', ' ').title()}\n\n"
                    report += f"{result['output'][:1000]}\n\n"
            return report

    def _verify_report(self, question: str, report: str) -> str:
        """
        Optional verification pass: a second LLM call reviews the report for
        factual gaps and appends a corrections / caveats section.
        Activated when config synthesis.include_verification is True.
        """
        self.log("Running verification pass on report...")
        verification_prompt = (
            f"You are a fact-checker reviewing the following research report.\n\n"
            f"Original question: {question}\n\n"
            f"Report:\n{report[:3000]}\n\n"
            f"Identify any vague claims, missing concrete examples, or unsupported "
            f"assertions. Then rewrite the report with these improvements incorporated. "
            f"Preserve the original structure; add specifics where they were missing. "
            f"Return ONLY the improved full report in markdown."
        )
        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4000,
                messages=[{"role": "user", "content": verification_prompt}]
            )
            verified = response.content[0].text
            self.log("Verification pass completed")
            return verified
        except Exception as e:
            self.log(f"Verification pass failed (using original): {e}", "WARNING")
            return report

    def get_agent_prompt(self, role: str, focus: str) -> str:
        """
        Get or create a system prompt for a specific agent role.
        Loads from file if exists, otherwise creates a default.
        """
        prompt_file = self.prompts_dir / f"{role}.txt"

        if prompt_file.exists():
            with open(prompt_file, 'r') as f:
                return f.read()

        # Default prompt template
        default_prompt = f"""You are a specialized {role.replace('_', ' ')} agent.
            Your role is to conduct thorough research using available tools.

            {focus}

            Guidelines:
            - Use WebSearch to find current information
            - Use Read to examine files if needed
            - Use Bash for technical validation if applicable
            - Provide specific, detailed findings
            - Include real examples and data points
            - Cite sources when possible
            - Be thorough but concise

            Focus on accuracy and depth rather than breadth."""

        # Save for future use
        with open(prompt_file, 'w') as f:
            f.write(default_prompt)

        return default_prompt

    async def orchestrate(self, question: str, output_file: str = None) -> str:
        """
        Main orchestration method that runs the complete research process.
        """
        self.log(f"Starting orchestration for: {question}")
        start_time = datetime.now()

        # Step 1: Plan - break down the question
        subtasks = self.plan_research(question)

        # Step 2: Delegate - spawn sub-agents concurrently
        agent_results = await self.run_agents_concurrently(subtasks)

        # Step 3: Synthesize - combine results into a report
        final_report = self.synthesize_results(question, agent_results)

        # Step 4: Output - save to file
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(final_report)
            self.log(f"Report saved to: {output_file}")

        # Log completion
        elapsed = (datetime.now() - start_time).total_seconds()
        self.log(f"Orchestration completed in {elapsed:.1f} seconds")

        return final_report