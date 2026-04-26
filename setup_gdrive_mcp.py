"""
Google Drive MCP Server Setup Helper
======================================
Run this script ONCE to complete the Google Drive OAuth flow and save
credentials so sub-agents can access your Google Drive via MCP.

Prerequisites:
  1. Node.js 18+ installed  (https://nodejs.org)
  2. A Google Cloud project with the Drive API enabled
     - Go to https://console.cloud.google.com
     - Create a project → Enable "Google Drive API"
     - Create OAuth 2.0 credentials (Desktop app type)
     - Download the credentials JSON and note Client ID + Secret

  3. Environment variables set (add to your .env file):
       GDRIVE_CLIENT_ID=your-client-id.apps.googleusercontent.com
       GDRIVE_CLIENT_SECRET=your-client-secret
       GDRIVE_REDIRECT_URI=urn:ietf:wg:oauth:2.0:oob

Usage:
    python setup_gdrive_mcp.py

After running, a .gdrive_oauth.json file is created in the project root.
That file is referenced by the MCP server config in orchestrator_config.json.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

OAUTH_FILE = Path(__file__).parent / ".gdrive_oauth.json"
SCOPES = "https://www.googleapis.com/auth/drive.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main():
    client_id = os.getenv("GDRIVE_CLIENT_ID")
    client_secret = os.getenv("GDRIVE_CLIENT_SECRET")
    redirect_uri = os.getenv("GDRIVE_REDIRECT_URI", "urn:ietf:wg:oauth:2.0:oob")

    if not client_id or not client_secret:
        print(
            "ERROR: GDRIVE_CLIENT_ID and GDRIVE_CLIENT_SECRET must be set in your .env file.\n"
            "See the prerequisites at the top of this script."
        )
        sys.exit(1)

    # ── Step 1: Build authorisation URL ──────────────────────────────────
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)

    print("\n=== Google Drive MCP OAuth Setup ===\n")
    print("Step 1: Open this URL in your browser and authorise access:\n")
    print(f"  {auth_url}\n")

    # ── Step 2: Exchange auth code for tokens ─────────────────────────────
    code = input("Step 2: Paste the authorisation code here: ").strip()
    if not code:
        print("No code entered. Aborting.")
        sys.exit(1)

    token_data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()

    req = urllib.request.Request(TOKEN_URL, data=token_data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
    except Exception as exc:
        print(f"ERROR exchanging code for tokens: {exc}")
        sys.exit(1)

    if "error" in tokens:
        print(f"OAuth error: {tokens}")
        sys.exit(1)

    # ── Step 3: Save to .gdrive_oauth.json ───────────────────────────────
    oauth_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_type": tokens.get("token_type", "Bearer"),
        "scope": tokens.get("scope", SCOPES),
    }
    OAUTH_FILE.write_text(json.dumps(oauth_data, indent=2), encoding="utf-8")
    print(f"\nCredentials saved to: {OAUTH_FILE}")

    # ── Step 4: Print the MCP config snippet ─────────────────────────────
    mcp_entry = {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gdrive"],
        "env": {"GDRIVE_OAUTH_PATH": str(OAUTH_FILE.resolve())},
    }
    print("\nAdd this entry to the 'agents.mcp_servers' list in your config:")
    print(json.dumps(mcp_entry, indent=2))

    print(
        "\nTo enable Google Drive for sub-agents, either:\n"
        "  a) Run the autoresearch loop — it will persist config to autoresearch/orchestrator_config.json\n"
        "  b) Manually add the entry above to autoresearch/orchestrator_config.json\n"
        "  c) Pass it via ResearchOrchestrator(config={'agents': {'mcp_servers': [<entry>]}})\n"
    )

    print("Setup complete!")


if __name__ == "__main__":
    main()
