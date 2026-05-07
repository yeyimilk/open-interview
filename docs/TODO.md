# Open Interview — TODO

Active backlog of work items that didn't fit in the current iteration.
Items are grouped by theme, then sized roughly. Anything you want to
pick up, open an issue first so we can discuss the shape before code.

Last updated: 2026-05-07

---

## 1. Messenger channels

### 1.1 WhatsApp DM support  ⏱ medium

**Problem.** Linked-device sessions opened by Baileys can't reliably
read self-DMs from the owner's primary phone. WhatsApp packages those
into `protocolMessage` envelopes (sync/state signals), not as
`conversation` text. Group messages work; DMs from *other* contacts
to the bot also work; only the owner-DM-to-self path is blocked.

**Status.** The two DM-related filter modes (`dms_only`, `all`) are
disabled in **Settings → Messaging** with an "Unavailable" badge so
users don't accidentally pick a broken mode.

**Investigation paths:**
- Try a newer Baileys minor version with revised `messageContextInfo`
  decoding; log every observed `protocolMessage.type` for self-DMs.
- Look at how openclaw sources self-DM text — they may use a different
  hook (e.g. `chats.history` or `messages.update`) that surfaces the
  decrypted text via a separate event.
- As a workaround, accept DM-from-second-account as the canonical
  "DM bot" path; document it in the UI.

**Scope of change.**
- `whatsapp_bridge/src/baileys-driver.ts` — extend `extractText` and
  add the new event hook.
- `frontend/app/src/features/settings/SettingsPage.tsx` — re-enable
  the `dms_only` and `all` ModeOptions (drop the disabled flag).
- New end-to-end check that owner self-DM round-trips.

### 1.2 WeChat plugin  ⏱ large

**Goal.** A second messenger plugin under `plugins/wechat/` that proves
out the channel-extensibility story. Same SDK contract — only a new
sidecar / vendor library.

**Open questions:**
- Personal-account access: WeChat's official APIs are heavily gated;
  community libraries (`wechaty`, `padlocal`, `padpro`) require paid
  PadLocal tokens. Is BYOC (bring-your-own-credentials) acceptable for
  v1, or do we need a reverse-engineered bridge?
- Manifest needs to expose Chinese-language command aliases (e.g.
  `/聊天` for `/chat`) and the command parser needs CJK-friendly
  whitespace tokenisation.
- Chunking limits differ (≈ 600 chars / WeChat message), so plugin
  manifest's `max_outbound_chars` must reflect that.

**First slice:**
- `plugins/wechat/plugin.json` + `runtime.py`
- `services/wechat_bridge/` Node sidecar wrapping wechaty (matching
  the WhatsApp bridge layout)
- New filter kind `contact` (WeChat doesn't expose phone numbers per
  contact)
- Echo suppression at the bridge level, identical to WhatsApp

### 1.3 Telegram plugin  ⏱ small

Comparatively trivial: official Bot API, no sidecar needed (long-poll
or webhook in the plugin itself). Good "second channel" choice if the
WeChat sidecar story stalls. Implementation could be a 1-day spike.

### 1.4 Slack plugin  ⏱ small

Slash commands map cleanly to our command grammar. Useful for users
running Open Interview inside their team's workspace. Slack Events
API webhook → `MessengerKernel.handle_turn`. ~ 1 day.

### 1.5 Voice notes inbound  ⏱ medium

WhatsApp / Telegram users will send voice notes. We already have STT
(`POST /audio/transcribe`). Wire `Attachment(kind="audio")` from the
plugin to a transcribe step, then route the transcript through the
kernel as a normal text turn. Update `MessengerCapabilities` with an
`inbound_voice` flag; mentor/general modes are happy to consume
transcripts.

---

## 2. Public learning resources

The Mentor / Interviewer get most of their power from grounding
against the user's own code. Add a curated **common KB** so they can
also reference industry-standard material when the user asks
"explain B-trees" or "give me a system design walk-through".

### 2.1 LeetCode question pack  ⏱ medium

**Scope:**
- A read-only KB shared across users, sourced from the
  [`fishercoder1534/Leetcode`](https://github.com/fishercoder1534/Leetcode)
  problem index (titles, difficulty, tags only — no copyrighted
  solutions) plus our own concise *concept* notes per problem family.
- New table `common_kb_documents` (already designed in §3.x) populated
  by an admin-only refresh job: `make seed-leetcode`.
- Tag-based retrieval: when the user mentions "two-sum" or "graph DP"
  the mentor can fetch the relevant nodes.

**Out of scope:** problem solutions, premium content, full statements.

### 2.2 System design primer  ⏱ medium

**Source:** `donnemartin/system-design-primer` (CC BY 4.0; attributable).

**Scope:**
- Section-level chunking (Cache, Sharding, CAP, etc.).
- Embed into common KB.
- Mentor mode quotes the primer on request and links back to the
  upstream README anchor.

### 2.3 Designing Data-Intensive Applications notes  ⏱ small

**Source:** Open community summaries (e.g. `keyvanakbary/learning-notes`).

Just the chapter summaries; not the book itself. Useful background for
mentor "compare LSM vs B-tree" type prompts.

### 2.4 Applied-AI question bank  ⏱ medium

**Goal.** Replace the existing `applied_ai_questions` placeholder
seed with a real bank covering: prompt design, RAG, eval, agents,
tool-use, fine-tuning, infra (vector DBs, KV cache, batched inference).

**Source:** our own writing, curated. Each entry: question + ≥ 2
acceptable answer outlines + difficulty + tags. Persisted in the same
common-KB table.

### 2.5 Behavioral / STAR pack  ⏱ small

A library of behavioral prompts ("Tell me about a time you disagreed
with a peer") with rubric-aligned acceptance criteria. Mentor uses
these when the user has selected "include behavioral" on the project's
target positions.

---

## 3. Retrieval and RAG architecture

### 3.1 Standalone retrieval / RAG service boundary  ⏱ large

**Problem.** Retrieval is becoming a platform capability, not just a helper
inside Mentor or Interviewer. Today project chunks, resume claims, generated
QA, common KB, and long-term memory are retrieved through several in-process
paths (`MemoryRetriever`, `CommonKBRetriever`, project vector collections,
claim mapping, mentor/interviewer-specific prompts). As the number of sources
grows, ranking, filtering, citations, permissions, and evaluation will become
hard to reason about if they stay scattered across Core domain code.

**Target shape.** Create a dedicated retrieval boundary first, then decide
whether to deploy it as a separate process once the contract stabilizes.
The boundary should own:
- Source adapters for project code chunks, resume claims, generated QA,
  common KB, chat history, episodic memory, long-term memory, and future
  curated learning resources.
- Query planning: source selection, per-source top-k, filters, recency,
  role/session context, and user/project permissions.
- Ranking and merging: hybrid scoring, reranking, dedupe, citation packing,
  token-budget aware context assembly.
- Retrieval observability: query, selected sources, scores, rejected matches,
  latency, and prompt context size.
- Evaluation fixtures for recall/precision against known project/resume
  questions.

**First slice.**
- Define a `RetrievalService` interface and DTOs in shared schemas:
  `RetrieveRequest`, `RetrieveResponse`, `RetrievedChunk`, `Citation`.
- Move existing retrieval call sites behind that interface without changing
  behavior.
- Keep implementation in-process initially; expose HTTP only after Mentor,
  Interviewer, resume claim mapping, and general chat are all using the same
  boundary.
- Add a small golden test set: project-specific question, resume claim
  grounding question, common-KB question, and mixed query.

**Non-goals for first slice.**
- New vector database.
- Re-indexing every artifact.
- Making retrieval provider-neutral across all embedding vendors before the
  source/ranking contract is proven.

### 3.2 Workspace-wide RAG for `/chat`  ⏱ medium

Current `/chat` mode hits per-user memory but not project chunks.
Implement a fan-out retriever: top-k chunks from each project (k=2),
plus resume parsed text, re-ranked by score. Stream into the system
prompt of `general_stream`.

### 3.3 Long-term memory pinning  ⏱ small

Let users mark a memory item as "pinned" so the distiller won't
prune it. UI: long-press in the memory panel.

### 3.4 Per-project memory namespacing  ⏱ small

Today's long-term memory is per-user. Optional per-project memory
helps when a user has many projects (e.g. "this fact only applies
to project X").

---

## 4. Interview intelligence

### 4.1 Standalone question-set generation boundary  ⏱ large

**Problem.** Question/test-set generation is already more than a simple
helper: it plans topic coverage, retrieves grounding material, runs sharded
generation, merges/dedupes, persists QA sets, and may soon generate multiple
types of interview assets. Keeping this logic buried inside Core will make it
hard to add richer test sets, regenerate slices, compare quality, or retry
long-running work safely.

**Target shape.** Extract a `QuestionSetService` boundary that owns the full
question/test-set lifecycle:
- Inputs: project, resume, target role/level, company style, selected skills,
  requested interview format, and generation constraints.
- Planning: coverage matrix by topic, depth, difficulty, project/resume
  evidence requirements, behavioral/system-design/Applied-AI allocation.
- Generation jobs: sharded generation, retry/resume, temp artifacts,
  partial-result visibility, merge/dedupe.
- Outputs: canonical question set, ideal answer outline, evidence/citations,
  rubric, expected follow-up dimensions, and quality metadata.
- Evaluation: offline quality checks, duplicate detection, grounding coverage,
  and user feedback/flagging loop.

**First slice.**
- Keep the service in-process but move orchestration out of `QAGenerationService`
  into a narrower application boundary with explicit request/response DTOs.
- Preserve existing project-scoped and resume-scoped QA APIs.
- Add one richer output field to each generated item: `follow_up_axes`
  (for example: implementation details, trade-offs, scale, debugging,
  ownership, failure modes).
- Add job-state tests for resume/project generation, retry after shard failure,
  and deterministic merge.

**Later split candidates.**
- Worker-only deployable for long generation jobs.
- Dedicated storage for generation artifacts and eval reports.
- Admin UI for question-set quality review and regeneration.

### 4.2 Threaded mock interview flow with deeper follow-ups  ⏱ large

**Problem.** The current mock interviewer mostly picks one question from a
bank, evaluates the answer, then moves to another bank question. That is useful
for practice, but it does not feel like a real interview. Real interviewers
usually start with a simple project overview question, identify an interesting
area, and then drill down with follow-ups on design choices, implementation
details, trade-offs, bugs, scale, and ownership before changing topics.

**Target behavior.**
- Start each project/resume thread with a lightweight opener:
  "Tell me about X" or "What was your role in X?"
- Maintain an interview thread state: current project/claim/topic, depth,
  answer quality, uncovered follow-up axes, and when to move on.
- Prefer depth-first follow-ups for 2-4 turns when the candidate gives enough
  material, instead of always advancing to a new question.
- Ask progressively deeper questions:
  overview → architecture/design → implementation details → trade-offs →
  failure modes/debugging → scale/metrics → reflection.
- Fall back to a new topic when the candidate cannot answer, has already
  covered the axis well, or the configured depth/time budget is exhausted.
- Use the existing evaluation to decide whether the next turn should be a
  clarification, a deeper probe, a challenge, or a topic switch.

**Implementation notes.**
- Do not hard-code follow-ups as text appended after every answer. Model this
  as an interview policy/planner that emits the next action:
  `ask_opener`, `ask_follow_up`, `challenge_claim`, `switch_topic`,
  `wrap_up`.
- Persist thread state in the interviewer session target so reconnects and
  live-audio turns keep context.
- Let generated question sets provide `follow_up_axes`; the interviewer policy
  chooses from those axes at runtime based on the answer.
- Add a UI indicator for "follow-up" vs "new topic" only if it helps users
  understand the flow; do not make it feel scripted.

**Acceptance tests.**
- A strong answer to a project opener triggers a deeper project follow-up,
  not an unrelated bank question.
- A shallow answer triggers a clarification or easier probe before switching.
- After the configured depth budget, the interviewer moves to a new topic.
- Follow-up state survives refresh/reconnect.
- End-of-session evaluation can summarize both breadth and depth coverage.

---

## 5. Hardening / ops

- **Observability**: structured logging for messenger turns, gateway
  calls per session, distiller runs. Tracing via OpenTelemetry — at
  minimum a session-id span.
- **Export / wipe**: per-user "download all my data" zip; "wipe
  everything except auth row" button.
- **Real arq offload**: today QA generation runs in-process; move it
  to a worker so the API never blocks on long generations.
- **Rate-limit profiles**: per-tier outbound chunk pacing for the
  delivery guard. Free tier = slower, paid = burst higher.
- **Health endpoints** for the WhatsApp bridge integrated into the
  core's `/healthz` so docker-compose health checks cover the whole
  stack.

---

## 6. Frontend polish

- **Messaging settings**: real-time status pill (Connected / Pairing
  / Re-pair needed) instead of polling-only.
- **Group picker UX**: search + multi-select instead of free-form
  paste of jids.
- **Chat history search** across mentor / interviewer / general
  sessions, with mode + project filters.
- **Resume detail view** — currently only available via the
  WhatsApp `/resume <id>` command; build the equivalent in the SPA.

---

## 7. Tests we should have but don't

- End-to-end "owner sends message in group, bot replies, no loop"
  using FakeDriver across 5 round-trips.
- DeliveryGuard integration test covering the *entire* kernel path
  (not just the guard in isolation).
- Frontend component test for the disabled ModeOption (regression
  guard against accidentally re-enabling DM modes before they work).
- Snapshot test for `/help` text so the public command list doesn't
  regress as we add commands.

---

## 8. Documentation

- A short `docs/messenger-plugins.md` walking new contributors
  through "implement a channel in 90 minutes": manifest, runtime,
  webhook signature, capabilities flags, tests.
- `docs/operating-the-bridge.md` — pairing, re-pair, log locations,
  what to look for when a session refuses to authenticate.
- A diagram of the inbound message lifecycle (parse → resolve →
  filter → command/dispatch → DeliveryGuard → send) — extracted
  from the design doc into a dedicated SVG.

---

If you start on any of these, please open a thin GitHub issue first
referencing the section above so we can keep this doc in sync with
in-flight work.
