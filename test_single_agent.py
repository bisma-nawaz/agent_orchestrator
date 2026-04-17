#!/usr/bin/env python3
"""
Test a single agent to verify Claude Agent SDK is working
"""

import asyncio
import os
from claude_agent_sdk import query, ClaudeAgentOptions
from dotenv import load_dotenv

async def test_single_agent():
    """Test a single agent execution."""

    load_dotenv()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not found")
        return

    print("Testing single agent execution...")

    agent_options = ClaudeAgentOptions(
        system_prompt="You are a helpful research assistant.",
        allowed_tools=["WebSearch"],  # Simple tool for testing
        max_turns=3,
        temperature=0.7
    )

    prompt = "What is the latest version of Python and its main features?"

    print(f"Prompt: {prompt}")
    print("-" * 50)

    try:
        output = []
        async for msg in query(prompt=prompt, options=agent_options):
            # Collect different types of messages
            if hasattr(msg, 'text'):
                output.append(msg.text)
                print(f"Text: {msg.text[:100]}...")
            elif hasattr(msg, 'content'):
                output.append(str(msg.content))
                print(f"Content: {str(msg.content)[:100]}...")
            else:
                print(f"Message type: {type(msg)}")

        print("-" * 50)
        print("Final output collected:")
        print("\n".join(output)[:500])

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_single_agent())