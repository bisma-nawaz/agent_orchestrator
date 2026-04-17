# Multi-Agent Research Orchestrator

A Python project with two layers: a **research orchestrator** that delegates subtasks to Claude Agent SDK workers, and an **autoresearch loop** that proposes configuration changes, scores reports with an LLM-as-judge, and keeps or discards each experiment.

## Architecture

### Layer 1: Research orchestrator

| Step | Role |
|------|------|
| **Plan** | LLM breaks the question into `N` subtasks (default `N=3`, configurable 2–4) with roles from `orchestrator/prompts/*.txt`. |
| **Delegate** | Each subtask runs as a real sub-agent via `claude_agent_sdk.query` with `Read`, `Bash`, `WebSearch` and multiple turns. |
| **Collect** | Sub-agents run concurrently; failures and timeouts are recorded; synthesis still runs with partial results. |
| **Synthesize** | A separate Anthropic Messages call merges agent outputs into one markdown report (optional verification pass via config). |
| **Output** | Report written to a path you pass into `orchestrate(..., output_file=...)`. |

Core code: `orchestrator/orchestrator.py`. Prompts live in `orchestrator/prompts/` as separate files.

### Layer 2: Autoresearch loop

`autoresearch/runner.py` runs a fixed benchmark of **three questions** (same strings as the take-home spec), scores outputs with `autoresearch/grader.py`, and loops: **baseline → propose → apply → evaluate → keep or revert → append `results.tsv`**. The runner defaults to **5** iterations (`--iterations`).

Best-so-far config is saved to `autoresearch/orchestrator_config.json` when a change is kept.

## Prerequisites

- Python 3.10+
- Anthropic API key with access to the models you configure (orchestrator and grader default to Haiku-class models)

## Setup

```bash
cd project
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

Optional check:

```bash
python setup_env.py
```

On Windows (PowerShell), you can also set the key for the session:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

## How to run

Run these from the **project root** (`project/`) so `import orchestrator` resolves correctly.

| Command | Purpose |
|---------|---------|
| `python -m orchestrator` | Example: one research question, report under `reports/`. |
| `python orchestrator/main.py` | Same example (adds project root to `sys.path` automatically). |
| `python test_orchestrator.py` | All three benchmark questions; reports in `reports/`. |
| `python test_single_agent.py` | Smoke-test a single Claude Agent SDK run. |
| `python -m autoresearch.runner` | Full autoresearch loop (add `--iterations 5` or higher). |

Grader-only behavior is encapsulated in `autoresearch/grader.py` and invoked by the runner.

## Project layout

```
project/
├── orchestrator/
│   ├── __init__.py          # Exports ResearchOrchestrator, DEFAULT_ORCHESTRATOR_CONFIG
│   ├── __main__.py          # python -m orchestrator
│   ├── main.py              # Example CLI entry
│   ├── orchestrator.py        # Planning, agents, synthesis
│   └── prompts/             # Per-role system prompts (*.txt)
├── autoresearch/
│   ├── runner.py            # Experiment loop
│   ├── grader.py            # LLM-as-judge (four dimensions, 1–10)
│   ├── results.tsv          # Append-only experiment log (create/populate by running the loop)
│   └── orchestrator_config.json   # Written when a run “keeps” a better config
├── reports/                 # Generated markdown reports (orchestrator / tests)
├── requirements.txt
├── .env.example
└── README.md
```

## Grading metric

For each question, the grader scores **comprehensiveness**, **accuracy**, **structure**, and **specificity** (1–10 each). The run score is the **mean over all four dimensions and all three questions** (equivalently: average of the three per-report subscores). The grader uses a **dedicated system prompt** and is intended as a separate “reviewer” role from the orchestrator’s sub-agents.

## Design questions (take-home)

### Architecture: separation of orchestrator, sub-agents, and experiment loop

The **orchestrator** owns planning, concurrency, and synthesis; **sub-agents** are isolated SDK sessions with their own system prompts and tools; **autoresearch** only mutates a JSON-serializable config and calls the same `ResearchOrchestrator` API as production-style code. That keeps the benchmark honest (same code path as interactive use) and avoids entangling “trainer” logic with agent internals.

### Prompt design: researcher vs analyst

**Research-oriented** prompts emphasize tool use, sourcing, and breadth (what exists, how it works). **Analyst-oriented** prompts emphasize comparison, tradeoffs, and implications. Shared rules: require concrete names (tools, papers, vendors), avoid filler, and structure output so synthesis can merge without duplication.

### Grading: reliability and bias

LLM judges trend **lenient** and reward confident tone. Mitigations here: a **skeptical** grader system prompt, scoring **four separate dimensions**, and truncating reports so length is not a free win. **Calibration** in production would mix human spot checks, held-out questions, and pairwise ranking (A vs B) to fit scores to human judgments.

### Experiment design: what to look for after several iterations

Watch whether gains come from **substance** (clearer planner instructions, better role mix, verification) versus **format gaming**. The runner feeds recent history into the proposer to reduce duplicate suggestions; ties vs the best score are discarded so the loop does not drift sideways.

### Convergence: avoiding circles and grader gaming

**History-aware proposals**, **discard on non-improvement**, and instructions to avoid **format-only** changes reduce trivial cycles. Stronger options (not all required for the baseline) include periodic human review, a second judge model, or question rotation so the metric cannot be overfit to three fixed prompts.

## Troubleshooting

- **Import errors**: Run commands from the project root, or add the project root to `PYTHONPATH`.
- **Timeouts**: Overall agent wait is about **120 seconds** in `run_agents_concurrently`; adjust there if needed.
- **Rate limits / cost**: Fewer `--iterations`, cheaper models, or shorter `max_turns` are acceptable; note any changes in your submission.
