#!/usr/bin/env python3
"""
Quick setup script to verify environment and API key
"""

import os
from dotenv import load_dotenv

def check_setup():
    """Verify the setup is correct."""

    print("🔍 Checking setup...")

    # Load .env file
    load_dotenv()

    # Check for API key
    api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        print("❌ ANTHROPIC_API_KEY not found!")
        print("   Please create a .env file with your API key")
        print("   Example: ANTHROPIC_API_KEY=sk-ant-xxx")
        return False

    if api_key == "your-api-key-here":
        print("❌ API key not configured!")
        print("   Please replace 'your-api-key-here' with your actual API key in .env")
        return False

    print("✅ API key found")

    # Check for required packages
    try:
        import claude_agent_sdk
        print("✅ claude-agent-sdk installed")
    except ImportError:
        print("❌ claude-agent-sdk not installed. Run: pip install -r requirements.txt")
        return False

    try:
        import anthropic
        print("✅ anthropic installed")
    except ImportError:
        print("❌ anthropic not installed. Run: pip install -r requirements.txt")
        return False

    # Check for reports directory
    if not os.path.exists("reports"):
        os.makedirs("reports")
        print("✅ Created reports/ directory")
    else:
        print("✅ reports/ directory exists")

    print("\n✅ Setup complete! You can now run:")
    print("   python test_orchestrator.py")
    return True

if __name__ == "__main__":
    check_setup()