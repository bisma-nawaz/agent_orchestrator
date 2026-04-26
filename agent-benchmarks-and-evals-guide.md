# How to Set Up Benchmarks & Evals for AI Agents

A practical guide to evaluating AI agents — from coding agents to conversational systems — with Terminal-Bench (tbench.ai) as a reference implementation.

---

## Why Agent Evaluation Is Hard

Traditional software testing relies on deterministic inputs and outputs. AI agents break that model entirely. They operate over many turns, call tools, modify state, and adapt based on intermediate results. Mistakes compound across steps, and creative solutions can look like failures to rigid graders.

Without evals, teams fall into reactive loops — catching issues only in production, where fixing one failure creates others. Evals make problems and behavioral changes visible *before* they affect users. Their value compounds over the lifecycle of an agent:

- **Early stage:** Force the team to specify what success actually means
- **Growth stage:** Catch regressions before they ship; measure improvements quantitatively
- **At scale:** Enable rapid model upgrades (days instead of weeks) and serve as a communication bridge between product and research teams

---

## Core Terminology

| Term | Definition |
|------|------------|
| **Task** | A single test with defined inputs and success criteria |
| **Trial** | One attempt at a task. Run multiple trials because model outputs are non-deterministic |
| **Grader** | Logic that scores some aspect of the agent's performance |
| **Transcript / Trace** | The complete record of a trial — outputs, tool calls, reasoning, intermediate results |
| **Outcome** | The final state of the environment (e.g., database state), not just what the agent *said* it did |
| **Evaluation Harness** | Infrastructure that runs evals end-to-end: provides instructions/tools, runs tasks concurrently, records steps, grades outputs, aggregates results |
| **Agent Harness / Scaffold** | The system that enables a model to act as an agent: processes inputs, orchestrates tool calls, returns results |
| **Evaluation Suite** | A collection of tasks designed to measure specific capabilities or behaviors |

---

## Case Study: Terminal-Bench (tbench.ai)

Terminal-Bench is one of the best-designed agent benchmarks to study and learn from. It benchmarks terminal/coding agents with a clean, reproducible architecture.

### Architecture

```
┌─────────────────────────────────────────┐
│           Terminal-Bench CLI            │
│  (tb run --dataset ... --agent ...)     │
├─────────────────────────────────────────┤
│                                         │
│  ┌───────────┐   ┌──────────────────┐   │
│  │   Task    │   │  Docker Container │   │
│  │ Definition│──▶│  (Isolated Env)   │   │
│  └───────────┘   └──────────────────┘   │
│                          │              │
│                          ▼              │
│                  ┌──────────────┐       │
│                  │  Agent Runs  │       │
│                  │  Inside Env  │       │
│                  └──────┬───────┘       │
│                         │               │
│                         ▼               │
│                  ┌──────────────┐       │
│                  │  Test Script │       │
│                  │  (Grading)   │       │
│                  └──────────────┘       │
│                                         │
└─────────────────────────────────────────┘
```

### Key Design Choices

1. **Containerized environments:** Each task has a dedicated Docker environment, ensuring reproducibility
2. **Human-verified solutions:** Every task has a known-correct solution
3. **Deterministic grading:** Test scripts verify the outcome, not the conversation
4. **Registry model:** Other benchmarks (SWE-Bench, AppWorld, DevEval) can be adapted into the same harness
5. **Leaderboard:** Public accountability with 123+ entries across agents and models

### Running Terminal-Bench

```bash
# Install and list available benchmarks
tb datasets list

# Run a specific task
tb run \
  --dataset terminal-bench-core==head \
  --agent terminus \
  --model anthropic/claude-sonnet-4-20250514 \
  --task-id hello-world

# Run with a custom agent
tb run \
  --dataset terminal-bench-core==head \
  --agent-import-path path.to.your.agent:YourCustomAgent \
  --task-id hello-world

# Run multiple trials for reliability measurement
harbor run -d terminal-bench@2.0 -a "agent" -m "model" -k 5
```

### Task Coverage

Terminal-Bench Core covers diverse terminal use cases:

- Software engineering (build systems, debugging, refactoring)
- Scientific computing (ML training, data processing)
- System administration (network config, kernel compilation)
- Security (vulnerability remediation)
- Data analysis and API interactions

---

## Setting Up Your Own Agent Eval System

### Step 1: Define Success Criteria

Before writing any code, answer: **What does success look like for this agent?**

Be specific and measurable. Vague criteria like "helpful responses" aren't testable. Good criteria look like:

- "The agent correctly resolves the customer's ticket AND the database reflects the correct state"
- "The generated code passes all unit tests AND introduces no new lint warnings"
- "The agent completes the task in fewer than 10 tool calls AND under 60 seconds"

### Step 2: Choose Your Grader Types

Combine three types of graders for comprehensive coverage:

#### Code-Based Graders (Deterministic)

Best for: verifiable outcomes, structural checks, performance constraints

```python
# Example: Verify database state after agent interaction
def grade_outcome(env):
    order = env.db.get_order("ORD-12345")
    assert order.status == "cancelled"
    assert order.refund_amount == 49.99
    assert order.refund_method == "original_payment"
```

| Method | Use Case |
|--------|----------|
| Unit tests (pass/fail) | Code correctness, API behavior |
| String/regex matching | Output format validation |
| Static analysis (lint, type check) | Code quality |
| State verification | Database/environment outcome checks |
| Tool call verification | Correct tools used with correct params |
| Transcript metrics | Turn count, token usage, latency |

#### Model-Based Graders (LLM-as-Judge)

Best for: nuance, open-ended quality, subjective criteria

```python
# Example: LLM rubric for code quality
rubric = """
Score the agent's code on a 1-5 scale:
5 - Clean, idiomatic, well-documented, handles edge cases
4 - Correct and readable with minor style issues
3 - Functional but has readability or maintainability concerns
2 - Works but has significant quality issues
1 - Incorrect or unmaintainable
"""
```

**Critical:** Calibrate LLM judges against human evaluators before trusting them. Compare judge output against manual human annotations periodically.

#### Human Graders

Best for: establishing ground truth, calibrating automated graders, subjective UX quality

Use sparingly due to cost. Reserve for:
- Building initial golden datasets
- Periodic calibration of LLM judges
- Spot-checking production traces
- A/B testing major changes

### Step 3: Build Two Eval Suites

#### Capability Evals ("Quality Evals")

- **Question:** "What can this agent do well?"
- **Expected pass rate:** Low initially — target tasks the agent struggles with
- **Purpose:** Give the team a hill to climb

#### Regression Evals

- **Question:** "Does the agent still handle what it used to?"
- **Expected pass rate:** ~100%
- **Purpose:** Catch backsliding

**Graduation pattern:** As capability eval pass rates climb to near 100%, those tasks graduate into the regression suite. What once measured "Can we do this at all?" now measures "Can we still do this reliably?"

### Step 4: Design Tasks

#### Task Template

```yaml
task:
  id: "unique-task-id"
  description: "Clear description of what the agent should accomplish"
  
  environment:
    type: docker
    image: "your-base-image:latest"
    setup_script: "scripts/setup_task.sh"
  
  inputs:
    instruction: "Fix the authentication bypass vulnerability in src/auth.py"
    files:
      - "src/auth.py"
      - "tests/test_auth.py"
  
  graders:
    # Deterministic: Does the code pass tests?
    - type: unit_tests
      required:
        - test_empty_password_rejected
        - test_null_password_rejected
        - test_valid_password_accepted
    
    # Deterministic: Code quality checks
    - type: static_analysis
      tools: [ruff, mypy, bandit]
    
    # Model-based: Overall quality
    - type: llm_rubric
      rubric_file: "rubrics/code_quality.md"
      threshold: 4.0
    
    # Deterministic: Tool usage patterns
    - type: tool_calls
      required:
        - {tool: read_file, params: {path: "src/auth/*"}}
        - {tool: edit_file}
        - {tool: run_tests}
  
  metrics:
    - n_turns
    - n_tool_calls
    - total_tokens
    - wall_clock_time
  
  trials: 5  # Run 5 times for reliability measurement
```

#### Task Design Principles

1. **Isolate the environment.** Use Docker containers so each run starts clean
2. **Make tasks verifiable.** Grade on *outcomes* (database state, file contents, test results), not on what the agent says it did
3. **Run multiple trials.** Single runs are unreliable. Use metrics like pass^k (pass rate across k trials) to measure consistency
4. **Cover diverse difficulty.** Include easy (sanity checks), medium (core functionality), and hard (edge cases, multi-step reasoning) tasks
5. **Include ground truth.** Human-verified solutions for every task, as Terminal-Bench does

### Step 5: Simulating Users (for Conversational Agents)

If your agent interacts with humans, you need an LLM-based user simulator:

```python
# User simulator setup (inspired by τ-bench)
user_simulator = {
    "model": "claude-sonnet-4-20250514",
    "temperature": 1.0,  # High for diverse, realistic user behavior
    "system_prompt": """
    You are simulating a customer who wants to change their flight 
    reservation to a different destination. You are somewhat impatient 
    and provide information only when asked.
    
    Your details:
    - Booking: FLT-98765
    - Current destination: Chicago
    - Desired destination: Denver
    - Budget: flexible but wants to avoid fees
    """
}

agent_config = {
    "model": "claude-sonnet-4-20250514",
    "temperature": 0.0,  # Low for reproducible agent behavior
    "tools": [search_flights, modify_booking, check_policy],
    "policy_document": "airline_policy.md"
}
```

**Grading multi-turn conversations** requires multiple dimensions:
- **Task completion:** Did the ticket get resolved? (state check)
- **Efficiency:** Did it finish in <10 turns? (transcript constraint)
- **Quality:** Was the tone appropriate? Did it follow policy? (LLM rubric)

### Step 6: Run Multiple Trials & Measure Reliability

Because LLMs are non-deterministic, single-run pass rates are misleading.

**pass^k** measures: "Does the agent pass *all* k trials of a task?" This captures reliability — an agent that passes 90% of the time but fails unpredictably is worse than one that passes 80% consistently for the same tasks.

```python
import numpy as np

def pass_k(results_per_task: dict[str, list[bool]], k: int) -> float:
    """
    results_per_task: {task_id: [True, False, True, True, ...]}
    Returns the fraction of tasks where ALL k trials passed.
    """
    pass_count = 0
    for task_id, trials in results_per_task.items():
        assert len(trials) >= k
        if all(trials[:k]):
            pass_count += 1
    return pass_count / len(results_per_task)
```

### Step 7: Operationalize

Integrate evals into your CI/CD pipeline so they run automatically:

```yaml
# Example: GitHub Actions integration
name: Agent Eval Suite
on:
  pull_request:
    branches: [main]

jobs:
  regression-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run regression suite
        run: |
          python run_evals.py \
            --suite regression \
            --trials 3 \
            --fail-threshold 0.95
      
      - name: Run capability suite
        run: |
          python run_evals.py \
            --suite capability \
            --trials 3 \
            --report-only  # Don't block, just report
      
      - name: Post results to PR
        run: python post_eval_results.py
```

**Track over time:**
- Pass rates (overall and per-task)
- Average turns / tool calls per task
- Token usage and cost per task
- Latency (time to first action, total wall clock)
- Failure mode distribution

---

## Recommended Tools & Frameworks

| Tool | Best For | Type |
|------|----------|------|
| **Terminal-Bench (tbench.ai)** | Terminal/coding agents; unified benchmark registry | Open-source |
| **SWE-Bench Verified** | GitHub issue resolution in Python repos | Open-source |
| **τ-bench / τ2-bench** | Conversational agents with tool use and policy following | Open-source |
| **DeepEval** | Pre-built metrics (plan quality, tool correctness, task completion) | Open-source |
| **Braintrust** | Tracing, scoring, CI/CD integration | Commercial |
| **Arize Phoenix** | Observability + eval workflows | Open-source core |
| **LangSmith** | Tracing and evaluation for LangChain agents | Commercial |

---

## Common Pitfalls

1. **Grading the transcript instead of the outcome.** An agent might take an unexpected path but still produce the correct result. Always check the final state first.

2. **Running single trials.** Non-determinism means one run proves little. Run at least 3-5 trials per task.

3. **Overfitting to the eval.** If your eval suite is small or narrow, prompt tuning against it will produce false confidence. Keep eval sets diverse and growing.

4. **Ignoring eval maintenance.** As evals approach saturation (>95% pass rate), only the hardest tasks remain. Small score changes can mask large capability improvements. Refresh your suite regularly.

5. **Skipping human calibration.** LLM judges drift. Periodically compare automated scores against expert human judgments and recalibrate.

6. **Not tracking cost alongside quality.** An agent that scores 5% higher but costs 3x more per task may not be the right tradeoff. Track tokens and latency as first-class metrics.

---

## End-to-End Example: Evaluating an E-Commerce Support Agent

This section walks through a **complete, concrete example** — building an eval system for a customer support agent that handles order returns and refunds for an online store. Use this as a template for your own agent.

### The Scenario

**Agent:** "ShopBot" — a conversational AI agent that helps customers with order issues (returns, refunds, exchanges, order tracking). It has access to tools (database lookups, refund processing, shipping APIs) and must follow company policy.

**The problem we're solving:** ShopBot is in production but the team is flying blind. Sometimes it refunds items that aren't eligible, sometimes it asks too many unnecessary questions, and nobody knows if last week's prompt change broke anything.

---

### Phase 1: Define the Agent, Tools, and Policy

First, define what ShopBot can do:

```python
# agent/tools.py — The tools ShopBot has access to

def lookup_order(order_id: str) -> dict:
    """Look up an order by ID. Returns order details."""
    # In eval: hits a mock DB seeded with test data
    return db.query("SELECT * FROM orders WHERE id = ?", order_id)

def lookup_customer(customer_id: str) -> dict:
    """Look up customer profile and history."""
    return db.query("SELECT * FROM customers WHERE id = ?", customer_id)

def process_refund(order_id: str, amount: float, method: str, reason: str) -> dict:
    """Process a refund. Method: 'original_payment' or 'store_credit'."""
    return refund_service.process(order_id, amount, method, reason)

def create_return_label(order_id: str, carrier: str = "ups") -> dict:
    """Generate a return shipping label."""
    return shipping_service.create_label(order_id, carrier)

def escalate_to_human(reason: str) -> dict:
    """Escalate the conversation to a human agent."""
    return {"status": "escalated", "reason": reason}
```

And the policy document ShopBot must follow:

```markdown
# ShopBot Return & Refund Policy

## Eligibility
- Items can be returned within 30 days of delivery
- Electronics have a 15-day return window
- Final sale items (marked "FINAL SALE") cannot be returned
- Items must be unused and in original packaging

## Refund Rules
- Refunds go to the original payment method by default
- If original payment method is expired, use store credit
- Refund amount = item price + tax. Never refund shipping.
- Orders over $500 require manager approval → escalate to human

## Process
1. Verify customer identity (ask for order ID + email on file)
2. Check return eligibility against policy
3. If eligible: generate return label, then process refund
4. If ineligible: explain why, offer alternatives
5. Always confirm the final action with the customer before executing
```

---

### Phase 2: Seed a Test Database

Create a mock database with known data so grading is deterministic:

```python
# eval/test_database.py — Seed data for eval environment

TEST_ORDERS = [
    {
        "id": "ORD-1001",
        "customer_id": "CUST-501",
        "customer_email": "alice@example.com",
        "items": [
            {"name": "Wireless Headphones", "category": "electronics",
             "price": 79.99, "tax": 6.40}
        ],
        "shipping_cost": 5.99,
        "total": 92.38,
        "delivered_date": "2026-04-10",   # 14 days ago — within 15-day window
        "status": "delivered",
        "payment_method": "visa_ending_4242",
        "payment_method_expired": False
    },
    {
        "id": "ORD-1002",
        "customer_id": "CUST-502",
        "customer_email": "bob@example.com",
        "items": [
            {"name": "Designer Jacket", "category": "apparel",
             "price": 299.99, "tax": 24.00, "tags": ["FINAL SALE"]}
        ],
        "shipping_cost": 0.00,
        "total": 323.99,
        "delivered_date": "2026-04-01",
        "status": "delivered",
        "payment_method": "mastercard_ending_8888",
        "payment_method_expired": False
    },
    {
        "id": "ORD-1003",
        "customer_id": "CUST-503",
        "customer_email": "carol@example.com",
        "items": [
            {"name": "Smart TV 55-inch", "category": "electronics",
             "price": 649.99, "tax": 52.00}
        ],
        "shipping_cost": 0.00,
        "total": 701.99,
        "delivered_date": "2026-04-20",
        "status": "delivered",
        "payment_method": "visa_ending_1111",
        "payment_method_expired": True   # Card expired!
    },
]
```

---

### Phase 3: Write Eval Tasks

Each task defines what the simulated user wants, what the expected outcome is, and how to grade it.

#### Task 1 — Simple Return (Easy, Happy Path)

```yaml
# eval/tasks/task_001_simple_return.yaml

task:
  id: "simple-electronics-return"
  description: >
    Customer wants to return wireless headphones purchased 14 days ago.
    Within the 15-day electronics return window. Agent should verify
    identity, confirm eligibility, generate return label, process refund.

  difficulty: easy
  category: returns

  user_scenario:
    persona: "Polite, straightforward customer"
    goal: "Return wireless headphones from order ORD-1001"
    info_to_provide:
      - order_id: "ORD-1001"
      - email: "alice@example.com"
      - reason: "Sound quality not as expected"
    info_to_withhold_until_asked:
      - email   # Only provide if agent asks for verification

  expected_outcome:
    orders:
      ORD-1001:
        status: "return_initiated"
        refund_amount: 86.39             # 79.99 + 6.40 tax, NO shipping
        refund_method: "visa_ending_4242"
    return_labels:
      - order_id: "ORD-1001"
        exists: true

  graders:
    # 1. Did the right thing happen in the database?
    - type: state_check
      weight: 50
      checks:
        - field: "orders.ORD-1001.refund_amount"
          expected: 86.39
          tolerance: 0.01
        - field: "orders.ORD-1001.refund_method"
          expected: "visa_ending_4242"
        - field: "return_labels.ORD-1001"
          expected_exists: true

    # 2. Did the agent use the correct tools?
    - type: tool_calls
      weight: 20
      required_sequence:
        - tool: lookup_order
        - tool: lookup_customer
        - tool: create_return_label
        - tool: process_refund
      forbidden:
        - tool: escalate_to_human

    # 3. Was the conversation quality good?
    - type: llm_rubric
      weight: 20
      model: "claude-sonnet-4-20250514"
      rubric: |
        Score 1-5 on each dimension:

        POLICY_COMPLIANCE: Did the agent follow return policy correctly?
        - Verified identity before processing?
        - Calculated refund correctly? (item + tax, no shipping)
        - Confirmed action with customer before executing?

        COMMUNICATION: Clear and professional interaction?
        - Explained steps? Appropriate tone? No unnecessary questions?

    # 4. Efficiency
    - type: transcript_metrics
      weight: 10
      thresholds:
        max_turns: 8
        max_tool_calls: 6
        max_tokens: 4000

  trials: 5
```

#### Task 2 — FINAL SALE Rejection (Policy Enforcement)

```yaml
# eval/tasks/task_002_ineligible_return.yaml

task:
  id: "final-sale-rejection"
  description: >
    Customer wants to return a FINAL SALE jacket.
    Agent should politely decline and NOT process any refund.

  difficulty: easy
  category: policy-enforcement

  user_scenario:
    persona: "Frustrated customer, will push back once"
    goal: "Return designer jacket from order ORD-1002"
    info_to_provide:
      - order_id: "ORD-1002"
      - email: "bob@example.com"
    behavior: >
      After being told item is final sale, push back:
      "But I just bought it two weeks ago, that's not fair!"
      Then accept the decision.

  expected_outcome:
    orders:
      ORD-1002:
        status: "delivered"      # Status should NOT change
        refund_amount: null      # No refund processed

  graders:
    - type: state_check
      weight: 50
      checks:
        - field: "orders.ORD-1002.status"
          expected: "delivered"
        - field: "orders.ORD-1002.refund_amount"
          expected: null

    - type: tool_calls
      weight: 25
      forbidden:
        - tool: process_refund
        - tool: create_return_label

    - type: llm_rubric
      weight: 25
      rubric: |
        Score 1-5:
        CORRECT_REJECTION: Identified FINAL SALE and declined?
        EMPATHY: Acknowledged frustration while holding firm?
        ALTERNATIVES: Offered any alternatives (store credit, exchange)?

  trials: 5
```

#### Task 3 — High-Value Escalation (Hard, Multi-Condition)

```yaml
# eval/tasks/task_003_high_value_escalation.yaml

task:
  id: "high-value-escalation"
  description: >
    Customer wants to return a $649.99 TV (total > $500).
    Per policy: requires manager approval → agent must escalate.
    Also, customer's card is expired → refund should be store credit.
    Agent should identify BOTH issues.

  difficulty: hard
  category: escalation

  user_scenario:
    persona: "Calm, cooperative customer"
    goal: "Return Smart TV from order ORD-1003"
    info_to_provide:
      - order_id: "ORD-1003"
      - email: "carol@example.com"
      - reason: "TV has a dead pixel in the corner"

  expected_outcome:
    escalations:
      - order_id: "ORD-1003"
        reason_contains: ["over $500", "manager approval"]

  graders:
    - type: state_check
      weight: 40
      checks:
        - field: "escalations"
          contains:
            order_id: "ORD-1003"

    - type: tool_calls
      weight: 30
      required:
        - tool: lookup_order
        - tool: escalate_to_human
      forbidden:
        - tool: process_refund

    - type: llm_rubric
      weight: 30
      rubric: |
        Score 1-5:
        ESCALATION_REASONING: Identified order > $500 threshold?
        EXPIRED_CARD: Noticed expired payment and mentioned store credit?
        COMMUNICATION: Explained escalation and set expectations?

  trials: 5
```

---

### Phase 4: Build the Eval Harness

The code that ties everything together — loads tasks, runs the agent, simulates users, and grades results:

```python
# eval/harness.py — Simplified eval harness

import json, yaml
from dataclasses import dataclass
from anthropic import Anthropic

client = Anthropic()

@dataclass
class TrialResult:
    task_id: str
    trial_num: int
    passed: bool
    scores: dict            # {grader_name: score}
    transcript: list        # Full message history
    tool_calls: list        # All tools the agent called
    final_db_state: dict    # Database state after agent ran
    metrics: dict           # {turns, tokens, latency}


def run_user_simulator(scenario: dict, agent_message: str) -> str:
    """Use an LLM to simulate the customer."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        temperature=1.0,   # High temp → diverse, realistic user behavior
        system=f"""You are simulating a customer in a support chat.

Persona: {scenario['persona']}
Goal: {scenario['goal']}
Info to provide: {json.dumps(scenario['info_to_provide'])}
Behavior notes: {scenario.get('behavior', 'Be natural and cooperative.')}

Respond as the customer would. Stay in character.
If your goal is accomplished or clearly denied, say "DONE".""",
        messages=[{"role": "user", "content": f"Agent says: {agent_message}"}]
    )
    return response.content[0].text


# ─── GRADERS ───────────────────────────────────────────────

def grade_state_check(db_state: dict, checks: list) -> float:
    """Does the database match the expected outcome?"""
    passed = 0
    for check in checks:
        actual = get_nested(db_state, check["field"])
        expected = check.get("expected")
        tolerance = check.get("tolerance", 0)

        if expected is None:
            passed += 1 if actual is None else 0
        elif isinstance(expected, (int, float)):
            passed += 1 if abs(actual - expected) <= tolerance else 0
        else:
            passed += 1 if actual == expected else 0

    return passed / len(checks)


def grade_tool_calls(actual_calls: list, config: dict) -> float:
    """Did the agent use the right tools (and avoid forbidden ones)?"""
    actual_names = [c["tool"] for c in actual_calls]
    score = 1.0

    for req in config.get("required", []):
        if req["tool"] not in actual_names:
            score -= 1.0 / max(len(config.get("required", [1])), 1)

    for forbidden in config.get("forbidden", []):
        if forbidden["tool"] in actual_names:
            score = 0.0   # Instant fail

    return max(score, 0.0)


def grade_llm_rubric(transcript: list, rubric: str) -> float:
    """LLM judge scores conversation quality."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        temperature=0.0,
        system="""Score the agent based on the rubric.
Return ONLY JSON: {"scores": {"DIM": 4, ...}, "average": 3.5, "reasoning": "..."}""",
        messages=[{
            "role": "user",
            "content": f"RUBRIC:\n{rubric}\n\nTRANSCRIPT:\n{json.dumps(transcript)}"
        }]
    )
    result = json.loads(response.content[0].text)
    return result["average"] / 5.0   # Normalize to 0–1


# ─── MAIN LOOP ─────────────────────────────────────────────

def run_single_trial(task: dict, trial_num: int) -> TrialResult:
    """Run one trial of one task."""
    db = create_test_database()   # Fresh copy every trial
    transcript = []
    tool_calls_log = []

    # First user message
    scenario = task["user_scenario"]
    user_msg = f"Hi, I need help. {scenario['goal']}."
    transcript.append({"role": "user", "content": user_msg})

    # Agent ↔ User loop
    for turn in range(20):
        agent_response = run_agent(transcript, db, tool_calls_log)
        transcript.append({"role": "assistant", "content": agent_response})

        if is_conversation_complete(agent_response):
            break

        user_response = run_user_simulator(scenario, agent_response)
        if "DONE" in user_response:
            break
        transcript.append({"role": "user", "content": user_response})

    # Grade
    scores = {}
    for grader in task["graders"]:
        if grader["type"] == "state_check":
            scores["state_check"] = grade_state_check(db.snapshot(), grader["checks"])
        elif grader["type"] == "tool_calls":
            scores["tool_calls"] = grade_tool_calls(tool_calls_log, grader)
        elif grader["type"] == "llm_rubric":
            scores["llm_rubric"] = grade_llm_rubric(transcript, grader["rubric"])

    # Weighted score
    weighted = sum(scores[g["type"]] * g["weight"] for g in task["graders"] if g["type"] in scores)
    total_weight = sum(g["weight"] for g in task["graders"])
    overall = weighted / total_weight

    return TrialResult(
        task_id=task["id"], trial_num=trial_num,
        passed=overall >= 0.7,
        scores=scores, transcript=transcript,
        tool_calls=tool_calls_log, final_db_state=db.snapshot(),
        metrics={"turns": len([m for m in transcript if m["role"] == "assistant"]),
                 "tool_calls": len(tool_calls_log)}
    )


def run_eval_suite(tasks_dir: str, num_trials: int = 5):
    """Run all tasks with multiple trials."""
    tasks = load_tasks(tasks_dir)
    all_results = {}

    for task in tasks:
        results = []
        for trial in range(num_trials):
            result = run_single_trial(task, trial)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"  {task['id']} | Trial {trial+1}/{num_trials} | {status}")
        all_results[task["id"]] = results

    print_report(all_results, num_trials)
```

---

### Phase 5: Run and Read the Results

```bash
python -m eval.harness --tasks eval/tasks/ --trials 5 --output results/
```

Example output:

```
═══════════════════════════════════════════════════════════════
                    SHOPBOT EVAL REPORT
                    2026-04-24 | 5 trials per task
═══════════════════════════════════════════════════════════════

TASK RESULTS
─────────────────────────────────────────────────────────────

✅ simple-electronics-return          pass^5: 5/5 (100%)
   ├─ state_check:        1.00  1.00  1.00  1.00  1.00
   ├─ tool_calls:         1.00  1.00  1.00  0.75  1.00
   ├─ llm_rubric:         0.90  0.85  0.88  0.92  0.87
   └─ avg turns: 5.2 | avg tool calls: 4.0

⚠️  final-sale-rejection              pass^5: 3/5 (60%)
   ├─ state_check:        1.00  1.00  1.00  0.00  1.00
   │                                        ^^^^
   │                      TRIAL 4: Agent refunded a FINAL SALE item
   │                      after customer pushed back
   ├─ tool_calls:         1.00  1.00  1.00  0.00  1.00
   ├─ llm_rubric:         0.82  0.78  0.80  0.60  0.85
   └─ avg turns: 6.4 | avg tool calls: 3.2

❌ high-value-escalation              pass^5: 1/5 (20%)
   ├─ state_check:        1.00  0.00  0.00  1.00  0.00
   │                      Agent processes refund directly instead
   │                      of escalating for orders > $500
   ├─ tool_calls:         1.00  0.00  0.00  1.00  0.00
   ├─ llm_rubric:         0.70  0.55  0.60  0.72  0.50
   └─ avg turns: 7.8 | avg tool calls: 5.4

─────────────────────────────────────────────────────────────
SUMMARY
─────────────────────────────────────────────────────────────
pass^1 rate:     3/3  (100%)   ← "Can it pass at least once?"
pass^5 rate:     1/3  (33%)    ← "Can it pass ALL 5 times?"
                                   ^^^ This is the reliability metric

TOP FAILURE MODES:
1. Policy override under pressure (task 2, trial 4)
   → Agent caved when customer pushed back on FINAL SALE
2. Missing escalation rule (task 3, trials 2,3,5)
   → Agent ignores the $500 escalation threshold
3. Expired card not detected (task 3, trials 2,3,5)
   → Agent doesn't check payment method validity
═══════════════════════════════════════════════════════════════
```

---

### Phase 6: Fix → Re-run → Verify

The report tells you exactly what to fix:

| Finding | Root Cause | Fix |
|---------|-----------|-----|
| Agent caves on FINAL SALE when user pushes back | Prompt doesn't emphasize firmness | Add: *"FINAL SALE items are never returnable regardless of customer objections. Be empathetic but firm."* |
| Agent skips $500 escalation rule | Rule is buried in policy doc | Move to system prompt as a hard constraint. Add a pre-check tool. |
| Agent ignores expired payment method | Doesn't inspect the field | Add: *"Before any refund, check if payment method is expired. If expired → store credit."* |

After fixing, re-run:

```
═══════════════════════════════════════════════════════════════
✅ simple-electronics-return    pass^5: 5/5 (100%)  ← Still works ✓
✅ final-sale-rejection          pass^5: 5/5 (100%)  ← Fixed ✓
⚠️  high-value-escalation       pass^5: 3/5 (60%)   ← Better, not reliable yet
═══════════════════════════════════════════════════════════════
```

Iterate until pass^5 reaches your quality bar, then graduate passing tasks into the regression suite.

---

### What This Example Demonstrates

| Concept | Where It Shows Up |
|---------|-------------------|
| **Task definition** | Three YAML task files with clear success criteria |
| **Deterministic grading** | `state_check` verifies database state (refund amount, order status) |
| **LLM-as-judge** | `llm_rubric` scores policy compliance and communication quality |
| **Tool call verification** | Checks required tools were used, forbidden tools were avoided |
| **User simulation** | LLM simulates different personas (polite, frustrated, calm) |
| **Multiple trials (pass^k)** | 5 trials per task reveal reliability issues (100% vs 60% vs 20%) |
| **Capability vs regression** | Hard tasks start low; easy tasks maintain 100% |
| **Actionable diagnostics** | Report pinpoints exact failure modes → clear fixes |
| **Iterative improvement** | Fix → re-run → verify fix didn't break other tasks |

---

## Getting Started Checklist

- [ ] Define 5-10 concrete success criteria for your agent
- [ ] Write 10-20 initial test tasks with ground truth outcomes
- [ ] Set up isolated environments (Docker) for reproducible runs
- [ ] Implement at least one deterministic grader (unit tests or state checks)
- [ ] Add one LLM-based rubric grader for qualitative assessment
- [ ] Configure multi-trial runs (k=3-5)
- [ ] Set up a regression suite with a >95% pass rate threshold
- [ ] Integrate into CI so evals run on every PR
- [ ] Schedule monthly human calibration of LLM judges
- [ ] Track metrics over time in a dashboard

---

## Further Reading

- [Anthropic — Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Terminal-Bench Documentation](https://www.tbench.ai/docs/first-steps)
- [τ-bench Paper (arXiv:2406.12045)](https://arxiv.org/abs/2406.12045)
- [Google Cloud — A Methodical Approach to Agent Evaluation](https://cloud.google.com/blog/topics/developers-practitioners/a-methodical-approach-to-agent-evaluation)
- [DeepEval Agent Evaluation Guide](https://deepeval.com/guides/guides-ai-agent-evaluation)
