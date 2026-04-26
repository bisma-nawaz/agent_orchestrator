# How to Make Claude Code Faster (Without Breaking What Makes It Good)

**Based on:** "Dive into Claude Code" research paper by Liu et al. (2026) — a deep dive into how Claude Code actually works under the hood. [arXiv:2604.14228v1](https://arxiv.org/abs/2604.14228v1)

---

## What Claude Code Actually Does Under the Hood

- Claude Code looks simple from the outside — you give it a task, it figures out what to do, runs commands, edits files, and keeps going until the job is done
- Under the hood, it's a **loop**. It calls the AI model, the model says "run this tool," the system checks if that's allowed, runs the tool, feeds the result back, and repeats. That's the whole thing — a while-loop
- But here's the twist: that simple loop is only about 1.6% of the code. The other 98.4% is everything around it — safety checks, context management, permission systems, memory, session handling. That surrounding infrastructure is where the slowness comes from, and also where we can speed things up

---

## Where the Time Goes

Think of every "turn" (one cycle of the loop) like a relay race with six legs. Some legs are way slower than others:

- **Calling the AI model** eats up 60–70% of the time. This is the big one — sending the prompt, waiting for the model to think, getting the response back
- **Compressing old context** takes 10–15%. The system has to shrink the conversation history so it fits in the model's memory window before every single call
- **Running tools** (shell commands, file reads, etc.) takes 8–12%
- **Checking permissions** ("is this tool allowed to run?") takes 5–8%
- **Assembling the context** (gathering all the instructions, memory files, tool definitions) takes 3–5%

The model call dominates everything. But every other step adds up, especially because the loop runs many times per task.

---

## The Six Places We Can Speed Things Up

### 1. Make the Model Calls Cheaper

The model call is the biggest cost, so even small improvements here have outsized impact.

- **Use a lighter model for simple stuff.** Not every step needs the full-power model. Reading a file to find a function name? Running a test to see if it passes? Those are routine — a faster, lighter model can handle them. The architecture already has a setting for this (`effort` parameter) — it just needs smarter routing to decide when to use it
- **Cache the boring parts of the prompt.** Every time Claude Code calls the model, it sends the same system instructions, the same project rules, the same tool definitions. If those stay identical across turns, the API can cache and skip reprocessing them. That means structuring the prompt so the unchanging parts come first and the conversation-specific parts come last
- **Start doing the next thing before being told to.** If Claude Code just read a file, it's very likely about to edit that file. If it just ran a test, it's probably about to read the error output. Instead of waiting for the model to explicitly ask, the system could start loading that file or preparing that shell session in advance. The paper calls this "speculative pre-execution" and references a technique called PASTE that does exactly this

### 2. Avoid the Expensive Compression Step

Before every model call, Claude Code runs five compression steps to keep the conversation history small enough to fit in the model's context window. Four of them are cheap. The fifth one — called "auto-compact" — is expensive because it literally makes another full model call just to summarize the conversation so far. When this kicks in, that single turn takes roughly twice as long.

- **Make the cheap steps work harder.** If the first four compression steps remove more aggressively (like capping how much output a single command can dump into the context), auto-compact triggers less often
- **Prefer "context collapse" over auto-compact.** Context collapse is one of the cheaper steps — it creates a simplified view of the conversation without actually calling the model. Using it more aggressively means auto-compact rarely needs to fire
- **Do compression in the background.** Instead of compressing right before the model call (blocking everything), do it between turns while the user is typing their next message

### 3. Stop Waiting for Permission Clicks

Every time Claude Code wants to run a tool, it checks a permission system. In default mode, it asks the user "is this okay?" for most operations. The research found that users click "yes" 93% of the time — meaning the system is pausing and waiting for a human confirmation that almost never adds value.

- **Switch to `acceptEdits` mode** if you're working in a git repo. This auto-approves file edits and common commands like `mkdir`, `rm`, `cp`. Since everything is version-controlled, you can always undo. This single change removes the biggest human-caused delay
- **Expand the auto-classifier.** Claude Code already has an ML classifier that can auto-approve safe bash commands. Right now it only works for shell commands — extending it to file edits and other tools would cut more wait time
- **Remember what was already approved.** If the user approved `npm test` once in a session, don't re-evaluate the full permission pipeline the next five times the same command runs. Cache it

### 4. Run Tools in Parallel Instead of One-by-One

Claude Code already runs some tools in parallel — but only read-only ones. Anything involving the shell gets serialized (run one at a time).

- **Treat read-only shell commands as parallel-safe.** Commands like `grep`, `cat`, `find`, `git log`, and `git diff` don't change anything — they just read. Running three of these at the same time instead of one after another would cut that portion of turn time significantly
- **Keep shell sessions alive.** Right now, every shell command starts a brand new process. If Claude Code kept a shell open and reused it, it would skip the startup cost each time
- **Don't kill everything when one thing fails.** Currently, if one shell command fails, all other running tools get killed immediately. That's too aggressive — a failed `grep` shouldn't cancel an unrelated file read. Group related tools together and only cancel within the group

### 5. Send Less Stuff to the Model Each Time

The model's context window is like a fixed-size desk. The more stuff piled on it, the slower it processes and the sooner it needs to compress things (triggering that expensive auto-compact). Keeping the desk clean means everything runs faster.

- **Don't load all 54+ tool definitions upfront.** Most tasks only use a handful of tools. Load the full definitions for the 8–10 most common ones, and only load the rest if the model specifically asks for them
- **Keep subagent reports tight.** When Claude Code delegates work to a sub-agent (a separate instance that runs independently), the sub-agent sends back a summary. If that summary is a concise list of findings instead of a paragraph of prose, it takes up less space in the parent's context
- **Only load relevant project instructions.** Claude Code reads CLAUDE.md files at four levels (system, user, project, local). Not all of those instructions are relevant to every task. Loading only the ones that match the current task would trim the context

### 6. Be Smarter About Starting and Preparing

- **Warm up before the user types.** When resuming a session, pre-load the previous context, reconnect to external services, and rebuild the tool list. Don't wait for the first prompt to start doing setup
- **Pre-fetch things the user will probably need.** If the user says "fix the tests," start running the tests in the background before the model even decides to. If git shows modified files, pre-load their contents. This turns sequential work into parallel work
- **Delegate exploration to sub-agents.** Searching the codebase, running diagnostic commands, understanding error messages — these are exploratory tasks that can be handled by a sub-agent with its own context. The parent agent stays focused on the actual fix, and the sub-agent reports back just the key finding

---

## The Biggest Win: Finish in Fewer Steps

All the optimizations above make each step faster. But the single most impactful thing is **doing fewer steps total**. Every eliminated loop cycle saves a model call + compression + permission check + tool run.

- **Write better CLAUDE.md files.** Tell Claude Code your project's build command, test command, directory structure, and coding conventions. This prevents it from guessing wrong and wasting 3–4 turns figuring out what you could've told it upfront. This is the highest-impact, lowest-effort optimization — it's just writing a config file
- **Batch operations.** Prompt the model to read multiple files or run multiple commands in a single response instead of doing them one at a time across multiple turns
- **Set up failure detection hooks.** Claude Code has a hook system that can watch for patterns like "the same test failed three times in a row after three different edits." A hook can catch this and inject guidance ("try a different approach") or stop early instead of letting the agent spin for 10 more turns

---

## What Not to Touch

- The **deny-first safety rule** must stay. Deny rules always override allow rules — this is the foundation of the security model. No speed optimization should weaken this
- **Seven independent safety layers** exist. Any one of them can block a dangerous action. Speed improvements should work within these layers, not around them
- **Irreversible operations** (deleting files outside version control, making network requests, modifying production systems) should never get fast-tracked. Speed optimizations apply to reversible, read-only, or version-controlled work

---

## Quick Priority List

Starting from "do this today" to "this takes real engineering":

1. **Write good CLAUDE.md files** — free, huge impact, no code changes
2. **Switch to `acceptEdits` mode in git repos** — one setting change, removes human-wait time
3. **Structure prompts for caching** — keep static instructions at the front of the context
4. **Encourage multi-tool batching** — prompt engineering, no code changes
5. **Tighten tool output size limits** — delays expensive compression
6. **Parallelize read-only shell commands** — moderate code change, good payoff
7. **Add effort-tiered model routing** — needs a routing heuristic, high payoff
8. **Delegate more to sub-agents** — tuning delegation thresholds
9. **Build speculative pre-execution** — most complex, but hides the biggest bottleneck
10. **Add background prefetching** — needs invalidation logic, solid payoff

---

*All findings traced to the source-level architecture documented in arXiv:2604.14228v1 by Liu, Zhao, Shang & Shen (2026).*
