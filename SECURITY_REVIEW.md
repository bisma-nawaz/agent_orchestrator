# OpenClaw Security & Design Review

10 issues found from a **user perspective** — things that are designed wrong, unsafe, or likely to cause unpleasant surprises.

---

## 1. `dangerously*` Config Options Silently Bypass All Sandbox Protection

**Files:** `src/agents/sandbox/config.ts`, `src/agents/sandbox/validate-sandbox-security.ts`

**What the issue is:**
OpenClaw sandboxes agents inside Docker containers so they can't touch the rest of your system. This is the primary safety boundary between the AI and your machine. However, there's a set of config options prefixed with `dangerously` — like `dangerouslyAllowExternalBindSources` and `dangerouslyAllowContainerNamespaceJoin` — that completely disable those protections.

The problem is that **none of this is visible to the user at runtime.** If you paste a config snippet from the internet that includes one of these flags, OpenClaw will start up normally with no warning, no banner, no confirmation dialog. The agent now has access to your real filesystem or host network, and you'd never know unless you read the config carefully.

**Why it matters to you:** You're trusting the sandbox to keep the AI contained. If that sandbox is silently off, you have no idea your files, SSH keys, or cloud credentials could be exposed.

---

## 2. Error Messages Leak Your Absolute File Paths

**Files:** `src/agents/path-policy.ts:19`, `src/infra/secret-file.ts`

**What the issue is:**
When something goes wrong — for example, an agent tries to access a file outside the workspace — OpenClaw throws an error that includes the **full absolute path** from your machine:

```
Path escapes workspace root (/home/alice/.openclaw/workspace): ../../etc/passwd
```

This reveals your username, your home directory structure, and the exact layout of your system. These error messages show up in the UI, in agent responses, and in logs.

**Why it matters to you:** If you share a session transcript, paste an error into a forum, or if an attacker can trigger an error remotely, they now know exactly where things live on your machine — which makes follow-on attacks easier. The fix is simple (show relative paths to users), which makes this particularly avoidable.

---

## 3. The Apply Patch Tool Has No Input Validation

**File:** `src/agents/apply-patch.ts:114`

**What the issue is:**
When an agent wants to edit your files, it uses a "patch" — a structured diff that describes what to change. OpenClaw accepts this patch and applies it without validating the format first. There are no checks for:

- How many files a single patch can touch
- Maximum file size in a patch
- Whether file paths in the patch use unusual or malformed encodings
- Whether the patch content is reasonable in size

The code calls `parsePatchText(input)` and immediately starts applying whatever comes back, trusting the format completely.

**Why it matters to you:** A runaway agent or a malformed patch can produce bizarre, hard-to-diagnose errors. More seriously, without size limits, an agent could craft a patch that modifies hundreds of files at once or writes enormous files — all in a single operation you approved as a simple "edit."

---

## 4. Web Fetch Silently Extracts Metadata From Every Page

**File:** `src/agents/tools/web-fetch.ts:105`

**What the issue is:**
When an agent fetches a web page, OpenClaw runs it through a "readability" extractor by default. This goes beyond just downloading the HTML — it parses the page and extracts structured metadata: author names, publish dates, schema.org structured data, article summaries, and more.

This happens **automatically on every fetch**, even when you just want the raw page content. The setting `readability: true` is the default and must be explicitly turned off.

**Why it matters to you:** The agent is receiving more information from pages than you may realize or intend. If you're using the agent to research something sensitive, it's quietly pulling in metadata you didn't ask for and feeding it into the model's context. You have no visibility into what extra data was extracted unless you go digging through logs.

---

## 5. The Gateway Password Must Be Stored as Plaintext at Startup

**File:** `src/gateway/auth.ts:230`

**What the issue is:**
OpenClaw has a secrets provider system designed to store sensitive values securely (passwords, API keys, etc.). However, the gateway's own password — the credential that protects access to OpenClaw itself — **cannot use the secrets provider**. It must be a plain string at startup time, because the secrets system hasn't initialized yet when the gateway boots.

This means your only options are:
1. Hardcode the password directly in your config file
2. Pass it via an environment variable like `OPENCLAW_GATEWAY_PASSWORD`

Environment variables are readable by anyone who can run `ps aux` on your machine, and config files with plaintext passwords are easy to accidentally commit to git.

**Why it matters to you:** The one credential that locks down everything else is the hardest one to store safely. The very system built to protect secrets can't protect this secret.

---

## 6. Session and Chat History Has No Pagination

**Files:** `src/acp/control-plane/manager.core.ts`, gateway session history endpoints

**What the issue is:**
When the UI or an API client requests your session history or message history, OpenClaw returns **everything at once** with no limit. After weeks or months of usage, a single history request could return tens of thousands of messages, gigabytes of transcript data, or thousands of sessions.

There is no `limit`, `offset`, or `page` parameter. You either get all of it or none of it.

**Why it matters to you:** The UI or API call will silently try to load all of it into memory. This can freeze the interface, cause the server to run out of memory, or cause timeouts that look like network errors. As a user, you'll just see a slow or broken UI with no explanation of why.

---

## 7. Individual Tool Calls Have No Rate Limiting

**Files:** `src/agents/tools/web-fetch.ts` and all other tool handlers

**What the issue is:**
OpenClaw rate-limits failed authentication attempts — so an attacker can't brute-force your password. But once authenticated, **there are no limits on how many tool calls an agent can make per minute**. An agent can call `web_fetch` 500 times in a second, run hundreds of bash commands back-to-back, or read thousands of files in a loop.

**Why it matters to you:** A buggy agent, a runaway loop, or a prompt injection attack that takes over the agent can consume all your bandwidth, max out your CPU, hammer external APIs (potentially getting your IP banned), or exhaust memory — all with no circuit breaker. You'd have to manually kill the process to stop it, and by then the damage may already be done.

---

## 8. HTTPS Downgrade Risk When Control UI Is Exposed on a Network

**Files:** `src/gateway/server-control-ui-root.ts`, `src/gateway/http-common.ts:15`

**What the issue is:**
HSTS (HTTP Strict Transport Security) is a browser security header that tells your browser "always use HTTPS for this site, never downgrade to HTTP." OpenClaw only sets this header when you explicitly configure it. There is no automatic HSTS when you expose the Control UI on your local network or Tailscale.

This is a common setup — many users run OpenClaw on a home server and access the UI from other devices on their network.

**Why it matters to you:** Without HSTS, an attacker on your network (or a misconfigured proxy) can intercept the connection and redirect your browser to an HTTP version of the page, stripping away encryption. Your session token gets sent in cleartext. OpenClaw gives no warning at startup that this combination (non-loopback binding + no HSTS) is risky.

---

## 9. Plugins Can Silently Inject Dangerous Config Without Any Warning

**File:** `src/plugins/runtime/index.ts`

**What the issue is:**
OpenClaw supports plugins, and plugins can contribute to the runtime configuration — including the `dangerously*` options from issue #1. When you install and load a plugin, its manifest is merged into the running config. There is no install-time audit, no permission screen, and no startup warning if a plugin is requesting dangerous permissions like disabling sandbox validation or allowing external bind sources.

**Why it matters to you:** You might install a plugin that says it's a "code formatter" or "database connector," not realizing it has also quietly enabled `dangerouslyAllowExternalBindSources` in its manifest. The agent now has access to parts of your filesystem you never intended to expose — and you'd have no way to know without manually reading the plugin's source code.

---

## 10. Agents Can Permanently Destroy Files Without a Confirmation Step

**Files:** `src/agents/bash-tools.exec.ts`, `src/agents/apply-patch.ts`

**What the issue is:**
Some dangerous shell commands (like `rm -rf`) do trigger an approval workflow where OpenClaw pauses and asks you to confirm. However, many destructive operations do **not** get a confirmation prompt:

- Overwriting files via `applyPatch` — the agent can silently replace the contents of any file in the workspace
- Bash commands that truncate or overwrite files without using `rm`
- Multi-file patch operations that touch dozens of files at once

The approval system is inconsistently applied: it catches some patterns but not others. From a user perspective, there's no reliable guarantee that "I approved one file edit" won't silently cascade into the agent rewriting half your project.

**Why it matters to you:** The most common way users lose work with AI coding tools is the agent confidently refactoring something they didn't intend to change. Without a predictable, consistent confirmation gate on all destructive writes, you're relying on the agent to be conservative — which it often isn't.

---

## Summary

| # | Issue | Risk |
|---|-------|------|
| 1 | `dangerously*` sandbox bypass with no warning | Agent escapes containment |
| 2 | Absolute paths leaked in error messages | Info disclosure |
| 3 | No patch format/size validation | Silent large-scale file changes |
| 4 | Readability extraction enabled by default | Unintended data in model context |
| 5 | Gateway password must be plaintext at startup | Credential exposure |
| 6 | No pagination on history endpoints | UI freeze / memory exhaustion |
| 7 | No per-tool rate limiting | Runaway agent, external API abuse |
| 8 | No automatic HSTS on LAN-exposed UI | Session token theft via MITM |
| 9 | Plugin manifests can inject dangerous config silently | Covert permission escalation |
| 10 | Destructive agent actions lack consistent confirmation | Silent data loss |

**Highest priority from a user standpoint:** #1 (silent sandbox bypass), #10 (data loss without warning), and #5 (the master password is the hardest credential to store safely).
