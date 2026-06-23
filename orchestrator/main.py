import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Project root on path so this file works when run as `python orchestrator/main.py`
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from orchestrator import ResearchOrchestrator


async def main():
    """Example usage of the orchestrator."""

    # Ensure API key is set
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Please set it with: export ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    # Example research questions
    questions = [
        "What are the tradeoffs between RAG and fine-tuning for enterprise knowledge bases?",
        "How do multi-agent systems handle failures and error recovery in production?",
        "What is MCP (Model Context Protocol) and how does it compare to direct API integrations?"
    ]

    orchestrator = ResearchOrchestrator(verbose=True)
    reports_dir = _ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for i, question in enumerate(questions, start=1):
        print(f"\n{'='*60}")
        print(f"Question {i}/{len(questions)}")
        print(f"Research Question: {question}")
        print(f"{'='*60}\n")

        out_path = reports_dir / f"report_q{i}_{stamp}.md"
        report = await orchestrator.orchestrate(
            question=question,
            output_file=str(out_path),
        )

        print("\n" + "="*60)
        print(f"FINAL REPORT (Q{i}) — saved to {out_path}")
        print("="*60)
        print(report[:1000] + "..." if len(report) > 1000 else report)


if __name__ == "__main__":
    asyncio.run(main())
