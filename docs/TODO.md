# Open Interview — TODO

Active backlog of work items that didn't fit in the current iteration.
Items are grouped by theme, then sized roughly. Anything you want to
pick up, open an issue first so we can discuss the shape before code.

Last updated: 2026-05-09

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

Common KB infrastructure is implemented in Core: admins can create
spaces/sources, upload single documents or folders into a chosen space,
process extracted items, review documents/items on focused pages, and hard
delete documents individually or in batches. Deleting a document removes the
document row, extracted items/tags, common-KB vector records, and the stored
blob on a best-effort basis. The remaining work in this section is content
quality, sourcing, attribution, and refresh automation.

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

### 3.1 Standalone retrieval / RAG service boundary  ✅ first slice done

Core now has an in-process retrieval boundary under
`openinterview_core/domain/retrieval/` with shared schemas in
`openinterview_schemas/retrieval.py`. Existing callers are routed through the
boundary: `/chat`, Mentor, Interviewer, QA generation, and resume claim
mapping. The first slice keeps Chroma, collection naming, embeddings, and
persisted artifacts unchanged.

Implemented responsibilities:
- Source adapters for project code chunks, resume claims, generated QA,
  common KB, working memory, episodic memory, and long-term memory.
- Query planning: source selection, per-source top-k, filters, workspace-wide
  project selection, and user/project permissions.
- Ranking and merging: score sorting, dedupe, citation packing, snippet
  truncation, and token-budget aware context assembly.
- Retrieval observability: purpose, selected sources, counts, latency, and
  context budget approximation.
- Golden-style unit coverage for project chunks, resume claim evidence,
  common-KB SQL fallback, mixed workspace retrieval, and isolation.

Remaining follow-ups:
- Decide whether this boundary should become a separate process after the
  contract stabilizes.
- Add hybrid scoring/reranking once the first retrieval metrics show where it
  matters.
- Add broader production evaluation fixtures for recall/precision against
  known project/resume questions.

Original target shape retained for future hardening:
- Source adapters for future curated learning resources.
- Query planning with richer recency and role/session policies.
- Ranking and merging: hybrid scoring, reranking, richer citation packing,
  token-budget aware context assembly.

**Non-goals for first slice.**
- New vector database.
- Re-indexing every artifact.
- Making retrieval provider-neutral across all embedding vendors before the
  source/ranking contract is proven.

### 3.2 Workspace-wide RAG for `/chat`  ✅ first slice done

`/chat` now calls `RetrievalService` for workspace-wide context across ready
projects, resumes, common KB, generated QA, and memory, then injects compact
retrieval context into `general_stream`.

### 3.3 Long-term memory pinning  ⏱ small

Let users mark a memory item as "pinned" so the distiller won't
prune it. UI: long-press in the memory panel.

### 3.4 Per-project memory namespacing  ⏱ small

Today's long-term memory is per-user. Optional per-project memory
helps when a user has many projects (e.g. "this fact only applies
to project X").

---

## 4. Interview intelligence

### 4.1 Standalone question-set generation boundary  ✅ first slice done

Core now has an in-process `QuestionSetService` boundary under
`openinterview_core/domain/question_sets/`. `QAGenerationService` remains as a
compatibility facade for older API, ingestion, and messenger call sites.

Implemented responsibilities:
- Project-scoped and resume-scoped request/response DTOs.
- QA-set lifecycle: get/create set, clear retry errors, mark `running`, run
  bounded shard generation, merge/dedupe, persist canonical items, mark
  `ready` or `failed`.
- Project and resume generators now request and persist canonical
  `follow_up_axes` on each item.
- QA responses expose nullable `project_id`, `resume_id`, `scope`, and item
  `follow_up_axes`.
- Regeneration branches correctly by `qa_set.scope`.
- Focused tests cover project/resume generation, all-shards failure, retry
  error clearing, merge behavior, and axis normalization.

Remaining follow-ups:
- Worker-only deployable for long generation jobs.
- Dedicated storage for generation artifacts and eval reports.
- Admin UI for question-set quality review and regeneration.

### 4.2 Threaded mock interview flow with deeper follow-ups  ✅ first slice done

The mock interviewer now maintains a per-session `thread_state` and uses a
small policy module to decide whether the next turn should stay on the current
topic or move to a new seed question.

Implemented behavior:
- Explicit policy actions: `ask_opener`, `ask_follow_up`, `challenge_claim`,
  `switch_topic`, and `wrap_up`.
- `chat_sessions.target.thread_state` tracks the current seed item, category,
  claim/topic, answer depth, used axes, remaining axes, last action, and last
  axis.
- `n_questions` now caps seed topics; follow-ups are separately bounded by the
  topic depth budget.
- Strong answers with remaining axes trigger deeper follow-ups; shallow early
  answers trigger `challenge_claim`; exhausted axes/depth switch topics or wrap.
- Text, audio, realtime, and messenger interview paths all read/write the same
  thread state.
- Assistant metadata persists `next_action`, `follow_up_axis`, and
  `thread_state`; final evaluation receives coverage events for breadth/depth.
- Tests cover strong-answer follow-up, shallow-answer challenge, depth budget,
  state persistence through session target, and policy unit decisions.

Remaining follow-ups:
- Optional UI affordance for "follow-up" vs "new topic" if user testing shows
  it helps.
- Quality review of generated follow-up prompts across more company/level
  styles.

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
