# The Autonomous Software Factory

## A Design Document

---

## What Is a Software Factory?

A software factory is an engineering system where AI agents—not humans—write, test, review, and ship code. The human role shifts from building software to specifying what should be built and validating the output. The analogy to physical manufacturing is deliberate: a factory has an assembly line, quality control stations, precisely specified inputs, and feedback loops that catch defects before they reach the end of the line. All of these properties map directly onto agentic software development.

The defining characteristic of a software factory is that it is **non-interactive**. A copilot assists a developer line by line. A factory takes a specification and runs to completion without human involvement. The human writes the spec, the factory produces the software, and the human evaluates the result. Everything in between is autonomous.

Two constraints serve as the forcing function behind the entire approach:

- Code must not be written by humans.
- Code must not be reviewed by humans.

These sound extreme because they are meant to be. When you cannot hand-write code or manually review a pull request, you are forced to build the infrastructure—specifications, validation harnesses, scenario suites, feedback loops—that makes autonomous development reliable. Without that constraint, teams default to old habits and the factory never materializes.

---

## Core Principles

### 1. Seed → Validation → Feedback

Every piece of software begins with a **seed**: a specification, a screenshot, a few sentences, an existing codebase. The factory applies a **validation harness** to the output and feeds the results back as input. This closed loop allows the system to self-correct.

The loop runs until the holdout scenarios pass and stay passing.

This is structurally identical to how machine learning models are trained. You define a loss function (the scenarios), you run the model (the agent), you measure the loss (validation), and you iterate. Code is the byproduct of convergence, not a hand-crafted artifact.

### 2. Scenarios Over Tests

Traditional unit tests can be gamed. An agent that is incentivized to make tests pass will find shortcuts: `return true` passes a narrowly written assertion but does not produce working software. Tests stored in the codebase can be lazily rewritten to match broken code.

A **scenario** is an end-to-end user story that describes what "working" looks like from the outside. Scenarios are stored outside the codebase as a holdout set—analogous to a holdout set in model training—so the agent cannot modify them to cheat. Validation is performed by an LLM-as-judge that can interpret whether the software's observable behavior satisfies the scenario's intent, not just whether a boolean assertion passes.

### 3. Satisfaction Over Pass/Fail

When the software itself contains agentic or probabilistic components, success is not binary. A scenario might be satisfied 87% of the time across observed trajectories. The factory measures **satisfaction**: of all the trajectories through all the scenarios, what fraction likely satisfy the user?

This probabilistic framing is more honest than green/red test suites and gives you a meaningful quality signal to optimize against.

### 4. Code as Opaque Weights

In a software factory, source code is treated the same way model weights are treated in machine learning: as an opaque artifact whose correctness is inferred exclusively from externally observable behavior. You do not read the weights of a neural network to know if it works. You evaluate it on held-out data. The same applies here. Internal structure is not inspected—only behavior.

This is a deep shift in mindset. It means code quality, style, and architecture are only relevant insofar as they affect the agent's ability to converge on passing scenarios in future iterations. If the code is ugly but satisfies every scenario reliably, it ships.

### 5. Verification Is the Bottleneck

Generation is cheap. Verification is expensive and hard. Agents can produce impressive output, but the challenge is knowing *with confidence* whether that output is correct. Several factors make this harder than it first appears:

- Tests that pass before a change do not guarantee they will catch regressions introduced by the change.
- Agents can write tests that are technically valid but miss the cases that matter.
- Context window limitations mean agents working on large codebases may miss important constraints outside their current window.
- Flaky environments that a single developer works around become systemic blockers when forty agents hit the same flaky test simultaneously.

The factory's value is concentrated in the quality of its validation infrastructure. Every dollar of investment here pays for itself many times over.

### 6. Deliberate Naivete

Building a high-fidelity behavioral clone of a major SaaS API was always technically possible but never economically feasible. Generations of engineers wanted a full in-memory replica of their CRM to test against but self-censored the proposal because they knew the answer would be no.

The economics have changed. Software factory builders must practice a deliberate naivete: finding and removing the habits, conventions, and constraints of the previous era. What was unthinkable six months ago is now routine. The question to ask at every obstacle is not "is this practical?" but "how can we convert this problem into a representation the model can understand?"

---

## Key Techniques

### Digital Twin Universe

Clone the externally observable behaviors of the third-party services your software depends on. Build behavioral replicas of auth providers, issue trackers, communication platforms, document stores—whatever your product integrates with. These twins replicate APIs, edge cases, and observable behaviors faithfully enough that your agents cannot tell the difference.

With a Digital Twin Universe, you can validate at volumes and speeds impossible against production services. No rate limits, no API costs, no abuse detection triggers. Failure modes that would be dangerous or impossible to test against live services become routine. Thousands of scenarios per hour, deterministic and replayable.

### Shift Work

Separate interactive work from fully-specified work. Figuring out *what* to build—talking to users, debating tradeoffs, exploring the problem space—is interactive and requires human judgment. Actually building the specified thing, once intent is complete, is mechanical and can be handed off entirely to agents.

The factory handles the second kind. Humans handle the first. The boundary between the two is the specification.

### The Filesystem as Memory

Agents can navigate repositories quickly and adjust their own context by reading and writing files. Directories, indexes, and on-disk state become a practical memory substrate for agents that otherwise have no persistence between runs. The filesystem is not just where code lives—it is the agent's working memory.

### Gene Transfusion

Move working patterns between codebases by pointing agents at concrete exemplars. When an agent has solved a problem in one context, the solution plus its surrounding context becomes a transferable pattern. A solution paired with a good reference can be reproduced in new contexts reliably.

### Pyramid Summaries

Reversible summarization at multiple zoom levels. Large codebases exceed any model's context window. Pyramid summaries compress context without losing the ability to expand back to full detail on demand, allowing agents to navigate efficiently while retaining access to the specifics when needed.

---

## Architecture: How the Factory Works

The factory is a pipeline with a feedback loop.

```
  SEED (human-authored spec)
    │
    ▼
  ┌──────────┐
  │  INTAKE   │  Parse requirements into structured spec
  └────┬─────┘
       │
       ▼
  ┌──────────┐
  │ ARCHITECT │  Produce system design, component map, interfaces
  └────┬─────┘
       │
       ▼
  ┌──────────┐
  │ ENGINEER  │  Generate code in isolated worktrees (parallelizable)
  └────┬─────┘
       │
       ▼
  ┌──────────┐
  │ VALIDATE  │  Run scenarios, score satisfaction, detect regressions
  └────┬─────┘
       │
   ┌───┴───┐
   │       │
  FAIL    PASS
   │       │
   ▼       ▼
FEEDBACK  SHIP
 LOOP    (merge, deploy, close ticket, produce proof-of-work)
   │
   └──▶ back to ENGINEER with diagnostic context
```

### Validation Infrastructure

The validation layer is the factory's immune system. It includes:

- **Scenario holdout set** — end-to-end user stories, stored outside the codebase, evaluated by LLM-as-judge.
- **Digital Twin Universe** — behavioral clones of external dependencies for high-volume deterministic testing.
- **Satisfaction scoring** — probabilistic evaluation across multiple trajectories, not binary pass/fail.
- **Regression ratchet** — quality baseline that only moves forward. Each change must maintain or improve scenario satisfaction.
- **CI harness** — conventional test suites, linters, type checkers, build verification as a baseline layer beneath scenario evaluation.

### Fleet Orchestration

A mature factory runs multiple agents in parallel, each in an isolated worktree. Agents can be specialized: one for generation, another for QA, another for architecture. Work is routed based on type. The orchestrator manages retries, convergence detection, and resource allocation.

### Proof of Work

When the factory ships, it produces evidence: CI results, scenario coverage reports, satisfaction scores, complexity analysis, diff summaries. This is how humans audit the factory's output without reading every line of code.

---

## What We Will Build

### Phase 1 — The Core Loop (P0)

The minimum viable factory requires three components:

**Spec Parser.** Converts natural-language requirements into structured, machine-readable specifications. Accepts text, screenshots, existing code, or tickets. The output is a document an agent can execute against: features, acceptance criteria, edge cases, data models.

**Scenario Generator.** Produces end-to-end user scenarios from specs. Maintains a holdout set stored outside the codebase. Scenarios are validated by LLM-as-judge, not boolean assertions.

**Non-Interactive Agent Runner.** Points a coding agent at the spec, lets it run without intervention, evaluates the output against scenarios, and feeds failures back in for another run. This is the core loop. Everything else is optimization.

### Phase 2 — Validation Depth (P1)

**Digital Twin Universe.** Starting with the external services the product depends on most. Behavioral clones that replicate APIs, edge cases, and observable behaviors.

**Satisfaction Scorer.** Runs N trajectories through each scenario, uses LLM-as-judge to score what fraction satisfy the user. Replaces pass/fail with a confidence distribution.

**Context Store.** Persistent context for agents across runs. Turn-based DAG, blob deduplication. Agents read and write to this store to maintain memory across sessions.

### Phase 3 — Scale and Polish (P2)

**Fleet Orchestrator.** Manages parallel agent runs in isolated worktrees. Routes work to the right agent type. Handles retries, feedback loops, and convergence detection.

**Regression Ratchet.** Quality baseline that only moves forward. Prevents gradual decay across many small changes.

**Proof-of-Work Generator.** Produces human-readable evidence of what the factory did for each shipped change.

**Semantic Porting Engine.** Semantically-aware code porting between languages or frameworks, preserving intent.

---

## The Human Role in a Software Factory

The factory does not eliminate engineers. It changes what they do. The human responsibilities become:

- **Specifying intent.** Writing clear requirements, defining scenarios, articulating what "working" looks like. The quality of the spec determines the quality of the output.
- **Curating scenarios.** Building and maintaining the holdout set. Adding edge cases. Shaping the validation surface to catch the failures that matter.
- **Building validation infrastructure.** The Digital Twin Universe, the satisfaction scorer, the regression ratchet—all of this needs to be designed and maintained.
- **Auditing outcomes.** Reviewing proof-of-work, monitoring satisfaction trends, intervening when the factory gets stuck.
- **Architecture decisions.** Choosing technologies, defining interfaces, setting constraints that shape the solution space the agents work within.

The engineer's job becomes building the system that builds the software—the factory itself—not the product.

---

## Getting Started

You do not need to build everything at once. Start here:

1. **Write a structured spec.** Take your next feature and convert it into a machine-readable specification with features, acceptance criteria, and edge cases. A markdown file is fine.

2. **Write five scenarios.** Describe five end-to-end user journeys that define what "working" looks like. Store them in a separate directory or repository. These are your holdout set.

3. **Run an agent non-interactively.** Point a coding agent at the spec and let it run without intervening. When it finishes, evaluate the output against your scenarios. If scenarios fail, feed the failures back in and run again.

4. **Measure satisfaction.** Run each scenario multiple times. What fraction of trajectories satisfy the user? This is your baseline. Every improvement to the factory should move this number up.

5. **Never touch the code.** This is the hard part. When you see a bug, do not fix it. Write a scenario that catches it and let the factory fix it. This is how the validation surface grows and the factory gets smarter.

That's the loop. Spec → Agent → Scenarios → Feedback → Agent again. Everything else is scale.
