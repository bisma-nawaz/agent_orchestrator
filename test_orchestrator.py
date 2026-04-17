"""
Test script for the Research Orchestrator (Layer 1)
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Project root on path (orchestrator is a proper package with __init__.py)
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from orchestrator import ResearchOrchestrator

# Load environment variables
load_dotenv()


async def test_orchestrator():
    """Test the orchestrator with the three fixed research questions."""

    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not found in environment")
        print("Please create a .env file with your API key")
        print("See .env.example for format")
        return

    # The three fixed research questions for evaluation
    questions = [
        "What are the tradeoffs between RAG and fine-tuning for enterprise knowledge bases?",
        "How do multi-agent systems handle failures and error recovery in production?",
        "What is MCP (Model Context Protocol) and how does it compare to direct API integrations?"
    ]

    # Create reports directory
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    # Initialize orchestrator
    orchestrator = ResearchOrchestrator(verbose=True)

    # Process each question
    for i, question in enumerate(questions, 1):
        print(f"\n{'='*80}")
        print(f"QUESTION {i}/3")
        print(f"{'='*80}")
        print(f"Research Question: {question}\n")

        # Generate timestamp for unique filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = reports_dir / f"report_q{i}_{timestamp}.md"

        try:
            # Run orchestrator
            report = await orchestrator.orchestrate(
                question=question,
                output_file=str(output_file)
            )

            print(f"\nReport Preview (first 500 chars):")
            print("-" * 40)
            print(report[:500] + "..." if len(report) > 500 else report)
            print("-" * 40)
            print(f"Full report saved to: {output_file}")

        except Exception as e:
            print(f"Error processing question {i}: {str(e)}")
            continue

    print(f"\n{'='*80}")
    print("TESTING COMPLETE")
    print(f"Reports saved in: {reports_dir.absolute()}")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(test_orchestrator())