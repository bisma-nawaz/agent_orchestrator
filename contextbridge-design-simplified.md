# ContextBridge — How Agents Share What They Know, Securely

## The problem

AI agents need to work together. Agent A researches a customer, Agent B writes the proposal. But right now, sharing context between agents is messy — they pass around huge blobs of text with no control over who sees what, no expiry, and no record of what was shared.

ContextBridge fixes this by giving agents three types of memory and a secure way to share across all of them.

---

## Three types of memory

### 1. Short-term memory — the whiteboard

This is a shared scratchpad for agents working together right now.

Picture two people in a room with a whiteboard. Both can write on it, both can read it, and when the meeting ends, the whiteboard gets erased.

That's what short-term memory is. When agents collaborate on a task, they create a "session" — a temporary shared space. Inside the session, they write to named slots (like sticky notes on the whiteboard). One agent might write "customer_info" while another writes "draft_plan." Both can see everything in the session instantly through a live connection.

Key details that matter:

- Everything lives in fast, temporary storage (RAM, not a hard drive). This is intentional — it's fast and leaves no trace after expiry.
- Sessions have a timer. The creator says "this session lasts 2 hours." When time's up, everything is deleted permanently. No recovery.
- Only invited agents can join. If an uninvited agent tries to connect, it gets blocked and the attempt is recorded.
- If two agents write the same slot at the same time, the last write wins by default. For situations where that's dangerous, agents can use version checking — "only save my update if nobody else changed this since I last read it." If someone did change it, the write is rejected and the agent has to re-read and try again.
- Even though the data is temporary, it's still encrypted. If someone broke into the server's memory, they'd see gibberish, not your data.

### 2. Episodic memory — the journal

This is the record of what happened in the past.

Think of it like a work journal. After a task is done, you write down what happened, what decisions were made, and what the outcome was. You don't copy the entire conversation — you write the important parts.

That's what episodic memory stores. When a session ends, agents can choose to save the important bits as an "episode." Later, any authorised agent can search through past episodes to find relevant history.

Key details that matter:

- Episodes can't be edited once written. This is on purpose — you need to trust that historical records haven't been tampered with. If you need to add context later, you add an annotation (a follow-up note), not an edit.
- Every episode records: when it happened, who was involved, what type of event it was (task completed, decision made, error encountered), a summary, the full details, and the outcome (success, failure, partial).
- Episodes are searchable in three ways. By time ("what happened last week?"). By tags and filters ("show me all failed tasks involving ACME Corp"). By meaning ("find anything related to refund policies" — this uses AI-powered semantic search that understands concepts, not just exact word matches).
- Episodes have sensitivity levels: public, internal, confidential, restricted. An agent searching for episodes only sees results it's allowed to see. The search system itself is encrypted — even someone with access to the search index can't read episode content.
- Episodes can expire. You can say "delete this after 1 year." Or keep them forever. Organisations set blanket retention rules (e.g., "delete everything over 2 years old unless it's tagged compliance").

### 3. Context vault — the safe

This is where persistent, important information lives — the things agents reference over and over.

Customer profiles, project settings, knowledge bases, tool configurations. Unlike episodes (which are historical records of events), vault items are living documents that get updated as facts change.

Key details that matter:

- Every update creates a new version. The old version is kept. You can ask "what did this customer profile look like three days ago?" and get an exact answer.
- Access control works at the field level. Agent A might see the full customer record. Agent B might see everything except payment details. This isn't done by trusting agents to ignore fields they shouldn't see — the server physically only sends them the fields they're allowed to read.
- Vault items have an owner (the agent that created them) and an access list that specifies exactly who can read, who can write, and whether readers are allowed to re-share with others.

---

## How the three layers connect

Context flows between layers through deliberate actions, never automatically.

**Promote** — When a session (whiteboard) ends, agents choose what's worth saving and write it as an episode (journal entry). The rest is erased. This keeps the journal clean — only meaningful events, not every intermediate step.

**Recall** — When starting a new session, an agent can search past episodes and pull relevant ones into the session as read-only reference material. "What did we do last time we onboarded a customer like this?"

**Load** — Agents can pull vault items (the safe) into a session to work on them together. When the session ends, changes can be saved back to the vault.

**Reference** — Episodes can link to vault items. "This episode involved customer_profile/abc-123." This creates a trail between what happened and the data it affected.

---

## How agents prove who they are

Every agent has a digital identity — not just a username, but a pair of cryptographic keys.

The private key is like a signature stamp. Only the agent has it. It uses the private key to sign every request, proving "this request really came from me."

The public key is like a signature verification card. The server (and other agents) use it to verify that a signature is genuine.

When an agent makes a request, two checks happen:

1. **The connection is verified (mTLS).** Both the agent and the server show certificates to each other. This proves the agent is registered and the server is real (not an impersonator). Think of it as both parties showing ID at the door.

2. **The request is verified (signed token).** Inside the secure connection, every request includes a short-lived token (expires in 5 minutes) signed by the agent's private key. This token says what the agent wants to do and which data it wants to access. The server checks the signature against the agent's public key.

Why two checks? If someone somehow cracked the connection security, they still can't forge the signed token without the agent's private key. If someone stole a token, they can't use it without a valid connection certificate. Both would need to fail for a breach to succeed.

**Key rotation:** Keys are replaced regularly (every 90 days recommended). During rotation, both old and new keys work for 24 hours so nothing breaks mid-transition. After that, the old key is permanently dead.

**Emergency kill switch:** If an agent's key is compromised, one API call revokes its entire identity. All its sessions are terminated, all its shared contexts are re-encrypted with new keys, and all access it granted to others is revoked. The audit log shows exactly what the compromised agent accessed.

---

## Access control — who can do what

ContextBridge doesn't use simple roles like "admin" or "viewer." Roles are too rigid — an agent might be a reader for customer data but a writer for sales notes, and only during business hours, and only for certain customers.

Instead, it uses rules based on attributes. Every request is evaluated against four things:

- **Who is asking** — the agent's organisation, its permissions, its trust level.
- **What are they accessing** — the data's sensitivity level, its type, who owns it, its tags.
- **What do they want to do** — read, write, share, delete, search.
- **What's the context** — current time, which network the request came from.

A rule looks like this in plain language: "Allow any agent in Organisation X to read items tagged 'project_alpha', but only if the item's sensitivity is 'internal' or lower, and only on weekdays between 8am and 8pm."

The system evaluates rules with a simple principle: if any rule says "deny," the answer is deny (deny always wins). If at least one rule says "allow" and nothing says deny, the answer is allow. If no rules match at all, the answer is deny (safe by default).

---

## How data is encrypted

Three layers of keys protect the data:

**Data key (DEK)** — Every single item (context, episode, session slot) gets its own unique encryption key. This key encrypts the actual data.

**Wrapping key (KEK)** — A higher-level key that encrypts the data keys. There are far fewer wrapping keys than data keys.

**Master key** — The root key that protects everything. This key lives inside a hardware security module (HSM) — a physical device specifically designed so that the key can never be extracted from it. All operations using the master key happen inside this device.

**How saving works (step by step):**

1. Agent creates a new item.
2. The system generates a fresh, random data key.
3. The item is encrypted with that data key.
4. The data key itself is encrypted ("wrapped") by the wrapping key.
5. The system stores the encrypted item and the wrapped data key together. The original data key is immediately discarded from memory.

**How reading works:**

1. The system retrieves the encrypted item and its wrapped data key.
2. It sends the wrapped data key to the key management service, which unwraps it (decrypts it inside the HSM).
3. The unwrapped data key is used to decrypt the item.
4. The data key is discarded from memory after use.

**Why this complexity?** It makes key rotation fast and cheap. When you rotate the wrapping key (recommended every 90 days), you only re-wrap the data keys — you don't re-encrypt the actual data. Re-wrapping thousands of small keys takes seconds. Re-encrypting terabytes of data would take hours.

**Field-level encryption:** When Agent A shares a context with Agent B but only certain fields, those fields aren't just filtered after decrypting everything. Instead, different groups of fields use different data keys. Agent B's access only allows unwrapping the keys for the fields it's permitted to see. Even if Agent B intercepted the full encrypted blob, it couldn't decrypt the restricted fields because the key management service would refuse to unwrap those keys for an unauthorised agent.

---

## How sharing works — step by step

Agent A wants to share a customer profile with Agent B, but only the name, email, and company fields, and only for 24 hours.

1. **Agent A sends a share request** — specifying the target agent, which fields to share, how long the access lasts, and whether Agent B can re-share with others.

2. **The policy engine checks everything** — Does Agent A own this data? Does its access list allow sharing with Agent B? Does Agent B meet the sensitivity requirements? Is re-sharing allowed? If any check fails, the request is denied and logged.

3. **The system creates a scoped access token** for Agent B — this token only grants access to the specified fields and expires after 24 hours.

4. **Agent B gets notified** — either via a webhook (a push notification to Agent B's server) or the next time Agent B checks its inbox. The notification includes the context ID, which fields are available, when access expires, and the access token.

5. **Agent B reads the data** — using the access token. The system decrypts only the permitted fields and returns them. The read is logged.

6. **Agent A can revoke access at any time** — one API call immediately invalidates Agent B's token. Any further read attempts by Agent B are blocked and logged.

**Delegation depth limits** prevent "share chains." Imagine Agent A shares with B, B shares with C, C shares with D — suddenly the data has leaked far beyond what A intended. The owner sets a maximum depth (e.g., 2 hops). At depth 2, Agent B can re-share once, but those secondary recipients can't share further.

---

## Audit log — the immutable record

Every operation in the system is logged. This isn't optional.

Each log entry records: who made the request, what they wanted to do, which data they targeted, what the policy engine decided (allow or deny), when it happened, and from which IP address.

Two things make this log tamper-proof:

1. **Hash chaining** — each entry includes a fingerprint (hash) of the previous entry. If someone modifies or deletes an entry in the middle, all entries after it would have wrong fingerprints, making tampering immediately obvious. This is the same concept behind blockchain, but without the overhead.

2. **Digital signatures** — each entry is signed by the platform's private key. An external auditor can independently verify any entry using the platform's public key, without having to trust the platform's database.

Logs are kept for a minimum of 1 year (default 7 years). Organisations can stream the log in real time to their own security monitoring systems.

---

## How leaks are prevented

**Automatic expiry** — Expired data is hard-deleted. The encryption keys are destroyed first, making the data permanently unrecoverable even if encrypted copies exist in backups.

**Share chain limits** — Delegation depth prevents context from spreading beyond the owner's control.

**Rate limiting** — Each agent has quotas on how many reads, writes, and shares it can perform. An agent suddenly reading 10,000 items gets throttled and flagged.

**Anomaly detection** — The audit log feeds a monitoring system that watches for unusual behaviour: an agent accessing data it's never touched before, a sudden spike in sharing, requests from unfamiliar networks. Alerts go to the security team.

**Instant revocation** — Revoking access takes effect immediately. There's no caching window where a revoked token still works. Every request checks revocation status in real time.

---

## Full API overview

### Short-term memory (sessions)

- **Create a session** — `POST /sessions` — start a new shared workspace.
- **Write to a slot** — `PUT /sessions/{id}/slots/{key}` — add or update a named value.
- **Read a slot** — `GET /sessions/{id}/slots/{key}` — get the current value.
- **List all slots** — `GET /sessions/{id}/slots` — see everything in the session.
- **Add a participant** — `POST /sessions/{id}/participants` — invite another agent.
- **Remove a participant** — `DELETE /sessions/{id}/participants/{agent_id}`.
- **Live updates** — `WS /sessions/{id}/stream` — real-time changes via WebSocket.
- **Promote to episode** — `POST /sessions/{id}/promote` — save important bits to episodic memory.
- **End session** — `DELETE /sessions/{id}` — wipe everything.

### Episodic memory (episodes)

- **Record an episode** — `POST /episodes` — save a new event record.
- **Get an episode** — `GET /episodes/{id}` — retrieve a specific record.
- **Search episodes** — `GET /episodes/search?q=...&tags=...&from=...&to=...` — find past events.
- **Annotate** — `POST /episodes/{id}/annotations` — add a follow-up note.
- **Delete** — `DELETE /episodes/{id}` — soft-delete (fully removed after retention period).

### Context vault (persistent data)

- **Create** — `POST /contexts` — store a new context object.
- **Read latest** — `GET /contexts/{id}` — get the current version.
- **Read specific version** — `GET /contexts/{id}/versions/{v}` — get a historical version.
- **List versions** — `GET /contexts/{id}/versions` — see all past versions.
- **Update** — `PUT /contexts/{id}` — save changes (creates a new version).
- **Share** — `POST /contexts/{id}/share` — grant access to another agent.
- **Revoke** — `DELETE /contexts/{id}/share/{agent_id}` — remove access.
- **Delete** — `DELETE /contexts/{id}` — soft-delete.

### Identity and admin

- **Register agent** — `POST /agents/register` — create identity, receive keys.
- **Rotate keys** — `POST /agents/{id}/rotate-keys` — replace keys (old ones stay valid 24 hours).
- **Revoke agent** — `PUT /agents/{id}/revoke` — emergency kill switch.
- **Query audit log** — `GET /audit?agent=...&action=...&from=...&to=...` — search the record.
- **Export audit log** — `GET /audit/export` — stream to external monitoring.

---

## Infrastructure notes

**Where each layer is stored:**

- Short-term memory runs on Redis (an in-memory database optimised for speed). Data never touches disk. Encrypted at rest in RAM.
- Episodic memory uses PostgreSQL (a reliable relational database) with a vector search extension for semantic queries. Large episode payloads go to object storage (like S3).
- Context vault uses PostgreSQL for metadata and access lists, object storage for encrypted payloads.
- Audit log uses append-only storage — a database where you can only add new entries, never modify or delete existing ones.

**Scaling:** The gateway and policy engine are stateless — run as many copies as you need behind a load balancer. The databases scale with read replicas. Sessions are distributed across Redis nodes by session ID.

**Multi-region:** For data sovereignty (e.g., EU data must stay in the EU), contexts can be pinned to a specific region. The policy engine supports region-based rules — "this data can only be accessed by agents running in the EU."
