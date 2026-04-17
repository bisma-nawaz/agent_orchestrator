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

    # Run orchestrator on first question as example
    orchestrator = ResearchOrchestrator(verbose=True)

    question = questions[0]
    print(f"\n{'='*60}")
    print(f"Research Question: {question}")
    print(f"{'='*60}\n")

    report = await orchestrator.orchestrate(
        question=question,
        output_file=f"reports/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    )

    print("\n" + "="*60)
    print("FINAL REPORT:")
    print("="*60)
    print(report[:1000] + "..." if len(report) > 1000 else report)


if __name__ == "__main__":
    asyncio.run(main())
