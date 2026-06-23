# Multi-Agent Research Orchestrator

A fully agent-based research system with two layers: a **research orchestrator** where every step is a real Claude Agent SDK agent, and an **autoresearch loop** that proposes config changes, scores reports with an LLM-as-judge, and keeps or discards each experiment.

---

## Architecture

### Layer 1: Research orchestrator pipeline

Every step uses `claude_agent_sdk.query` — there are no raw `client.messages.create` calls inside the orchestrator.

| Step | Agent | Tools | Config key |
|------|-------|-------|------------|
| **0a. Classify** | `question_classifier` | none | `input.classify_question` |
| **0b. Context** | `context_gatherer` | WebSearch | `input.gather_context` |
| **1. Plan** | `planner` | WebSearch | `planning.*` |
| **2. Delegate** | specialist agents (parallel) | Read, Bash, WebSearch, MCP | `agents.*` |
| **3. Synthesise** | `synthesizer` | none | `synthesis.style` |
| **4. Review** | `quality_reviewer` | none | `synthesis.quality_review` |

**Step 0a — Question classifier**: determines whether the input is a researchable question. If not, returns immediately with a clear explanation. If yes, refines the wording for clarity.

**Step 0b — Context gatherer**: sprints ahead with WebSearch to assemble key terms, named tools/frameworks, and dominant approaches before the planner or agents see the question. This context is injected into downstream prompts.

**Step 1 — Planner**: decomposes the question into N subtasks, assigns each a specialist role, and when `planning.dynamic_turns=True`, sets a per-agent `max_turns` budget based on task complexity.

**Step 2 — Specialist agents** run concurrently. Each gets:
- A role-specific system prompt from `orchestrator/prompts/<role>.txt` with `{{placeholder}}` variables filled at runtime
- Tools: `Read`, `Bash`, `WebSearch` (plus MCP if configured)
- Per-task `max_turns` (set by planner or config fallback)
- Automatic retry with partial-output context if the agent fails (`agents.retry_failed`)

**Step 3 — Synthesiser**: merges all agent findings into a structured markdown report. Style is configurable: `comprehensive`, `executive`, or `comparative`.

**Step 4 — Quality reviewer**: evaluates the report on the same 4 dimensions as the grader (comprehensiveness, accuracy, structure, specificity). If any score < 6/10 it triggers one revision pass using the synthesiser.

### Layer 2: Autoresearch loop

`autoresearch/runner.py` runs the fixed benchmark of three questions, scores outputs with `autoresearch/grader.py`, and loops: **baseline → propose → apply → evaluate → keep or revert → append `results.tsv`**.

- **Proposer**: SDK agent (no raw API) — receives full config + experiment history and suggests ONE config lever change
- **Grader**: intentionally uses raw API with a separate skeptical system prompt (by design — required evaluator separation per challenge spec)
- Best config saved to `autoresearch/orchestrator_config.json` when a change is kept

---

## Prerequisites

- Python 3.10+
- Anthropic API key
- Node.js 18+ (only if using Google Drive MCP)

---

## Setup

```bash
cd project
pip install -r requirements.txt
cp .env.example .env   # then edit .env and set ANTHROPIC_API_KEY
```

Optional environment check:

```bash
python setup_env.py
```

---

## How to run

Run from the **project root** (`project/`) so `import orchestrator` resolves correctly.

| Command | Purpose |
|---------|---------|
| `python orchestrator/main.py` | Single example question, report saved under `orchestrator/reports/` |
| `python test_orchestrator.py` | All three benchmark questions; reports in `reports/` |
| `python test_single_agent.py` | Smoke-test a single SDK agent call |
| `python -m autoresearch.runner` | Full autoresearch loop (default 5 iterations) |
| `python -m autoresearch.runner --iterations 8` | More iterations |

---

## Google Drive MCP setup (optional)

Sub-agents can retrieve documents from your Google Drive when `agents.mcp_servers` is configured.

### 1. Create Google Cloud credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a project → **Enable "Google Drive API"**
3. **Credentials** → Create OAuth 2.0 client → Desktop app → download JSON
4. Note `client_id` and `client_secret`

### 2. Run the OAuth helper

```bash
# Add to .env first:
# GDRIVE_CLIENT_ID=your-client-id.apps.googleusercontent.com
# GDRIVE_CLIENT_SECRET=your-client-secret

python setup_gdrive_mcp.py
```

Follow the browser prompt. A `.gdrive_oauth.json` file is created in the project root.

> **Security:** `.gdrive_oauth.json` holds your live OAuth `client_secret` and refresh token. It is git-ignored and must **never** be committed. Each user generates their own locally by running the helper above.

### 3. Enable in config

The helper prints the exact MCP entry to add. Either:

**Option A — autoresearch config file** (`autoresearch/orchestrator_config.json`):
```json
{
  "agents": {
    "mcp_servers": [
      {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-gdrive"],
        "env": {"GDRIVE_OAUTH_PATH": "/absolute/path/to/.gdrive_oauth.json"}
      }
    ]
  }
}
```

**Option B — programmatic**:
```python
from orchestrator import ResearchOrchestrator

orchestrator = ResearchOrchestrator(config={
    "agents": {
        "mcp_servers": [{
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-gdrive"],
            "env": {"GDRIVE_OAUTH_PATH": ".gdrive_oauth.json"},
        }]
    }
})
```

Once configured, sub-agents will have access to Google Drive search and file reading tools automatically.

---

## Project layout

```
project/
├── orchestrator/
│   ├── __init__.py              # Exports ResearchOrchestrator, DEFAULT_ORCHESTRATOR_CONFIG
│   ├── __main__.py              # python -m orchestrator
│   ├── main.py                  # Example CLI entry
│   ├── orchestrator.py          # Full pipeline — all steps are SDK agents
│   └── prompts/                 # Per-role system prompts (*.txt) with {{placeholder}} support
│       ├── planner.txt                        # NEW: planning agent
│       ├── question_classifier.txt            # NEW: input validation
│       ├── context_gatherer.txt               # NEW: pre-research context sprint
│       ├── synthesizer.txt                    # NEW: synthesis agent
│       ├── quality_reviewer.txt               # NEW: post-synthesis review
│       ├── technical_researcher.txt
│       ├── practical_analyst.txt
│       ├── domain_expert.txt
│       ├── comparative_analyst.txt
│       ├── performance_analyst.txt
│       ├── cost_and_operations_analyst.txt
│       └── security_and_compliance_researcher.txt
├── autoresearch/
│   ├── runner.py                # Experiment loop (proposer uses SDK)
│   ├── grader.py                # LLM-as-judge (raw API, intentionally separate)
│   ├── results.tsv              # Append-only experiment log
│   └── orchestrator_config.json # Written when a run "keeps" a better config
├── reports/                     # Generated markdown reports
├── setup_gdrive_mcp.py          # NEW: Google Drive OAuth helper
├── requirements.txt
├── .env.example
└── README.md
```

---

## Configuration reference

All keys live in `DEFAULT_ORCHESTRATOR_CONFIG` (see `orchestrator/orchestrator.py`) and can be overridden:

```python
# Full default config
{
  "version": 0,
  "input": {
    "classify_question": True,   # validate & refine input before pipeline
    "gather_context": True,      # pre-research WebSearch context sprint
  },
  "planning": {
    "num_agents": 3,
    "instruction_modifier": "",  # extra text appended to planner prompt
    "dynamic_turns": True,       # planner assigns per-agent max_turns
  },
  "agents": {
    "roles": ["technical_researcher", "practical_analyst", "domain_expert"],
    "max_turns": 10,             # fallback when dynamic_turns=False
    "retry_failed": True,        # retry failed agents with partial context
    "max_retries": 1,
    "mcp_servers": [],           # MCP server configs (see Google Drive MCP section)
  },
  "synthesis": {
    "style": "comprehensive",    # "comprehensive" | "executive" | "comparative"
    "prompt_modifier": "",       # extra requirement for the synthesiser
    "quality_review": True,      # post-synthesis quality review + optional revision
    "max_review_iterations": 1,
  },
}
```

### Prompt placeholder variables

Prompt files in `orchestrator/prompts/` support `{{variable}}` substitution. Available variables:

| Variable | Value |
|----------|-------|
| `{{question}}` | The research question for this subtask |
| `{{focus}}` | The focus field assigned by the planner |
| `{{context}}` | Pre-research context (first 500 chars) |
| `{{date}}` | Today's UTC date (YYYY-MM-DD) |
| `{{num_agents}}` | Number of agents (planner prompt only) |
| `{{context_block}}` | Full context + role hints (planner prompt only) |

---

## Grading metric

For each question, the grader scores **comprehensiveness**, **accuracy**, **structure**, and **specificity** (1–10 each). The run score is the mean over all four dimensions and all three questions. The grader uses a dedicated skeptical system prompt and a raw API call — intentionally separate from the orchestrator pipeline.

---

## Design questions (take-home)

### Architecture: separation of orchestrator, sub-agents, and experiment loop

The **orchestrator** owns the pipeline coordination (classify → context → plan → delegate → synthesise → review); **sub-agents** are fully isolated SDK sessions with their own system prompts, tools, and turn budgets; **autoresearch** only mutates a JSON-serializable config and calls the same `ResearchOrchestrator` API as interactive code. The grader is kept as a raw API call to maintain the evaluator/generator separation required by the challenge spec.

### Prompt design: researcher vs analyst

**Research-oriented** prompts (`technical_researcher`, `context_gatherer`) emphasise tool use, sourcing, and breadth. **Analyst-oriented** prompts (`comparative_analyst`, `quality_reviewer`) emphasise evaluation, comparison, and tradeoffs. All prompts share: require concrete names (tools, papers, vendors), avoid filler, structure output so the synthesiser can merge without duplication. Prompts use `{{placeholder}}` variables so the autoresearch loop can tune them via `planning.instruction_modifier` and `synthesis.prompt_modifier` without touching file content.

### Grading: reliability and bias

LLM judges trend lenient and reward confident tone. Mitigations: **skeptical** grader system prompt ("most AI reports are mediocre, 5–6/10"), **four separate dimensions** (a well-structured but shallow report scores high on Structure and low on Specificity), **3 000-char truncation** so length is not a free win. Calibration in production would mix human spot-checks, held-out questions, and pairwise ranking (A vs B) to fit scores to human judgments.

### Experiment design: what to look for after several iterations

Watch whether gains come from **substance** (better role mix, pre-research context, verification) versus **format gaming**. The runner feeds recent history to the proposer to reduce duplicate suggestions; ties vs the best score are discarded so the loop does not drift sideways.

### Convergence: avoiding circles and grader gaming

History-aware proposals, discard on non-improvement, and instructions to avoid format-only changes reduce trivial cycles. Stronger options include periodic human review, a second judge model, or question rotation so the metric cannot be overfit to the three fixed prompts.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ImportError: cannot import name 'ResearchOrchestrator'` | Run from project root, or add project root to `PYTHONPATH` |
| Agents timeout | Increase `timeout=180` in `run_agents_concurrently`; reduce `agents.max_turns` |
| Rate limit errors | Reduce `--iterations`, set `agents.max_turns` to 5, or use cheaper model |
| MCP not connecting | Ensure Node.js 18+ is installed; verify `.gdrive_oauth.json` path |
| Quality reviewer triggers infinite revision | Set `synthesis.max_review_iterations=1` (already default) |
