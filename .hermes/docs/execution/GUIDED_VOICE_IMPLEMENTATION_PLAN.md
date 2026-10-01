# Guided Voice Session Implementation Plan

> For Hermes: Use the subagent-driven-development skill if delegating implementation task-by-task; parent retains integration and verification responsibility.

**Goal:** Ship a real, authenticated, call-like drill coach with brief feedback, deterministic retry/advance, memory-mode visibility and verified persistence/termination, while preserving Recorded Practice.

**Architecture:** Browser WebRTC carries microphone and coach audio. FastAPI authenticates and creates provider sessions, observes/controls them through a trusted provider connection, and runs an authoritative drill controller. Dedicated Supabase entities persist guided state, validated turns and atomic usage without relaxing existing recorded-attempt contracts.

**Tech Stack:** Existing React 19/TypeScript/Vite/Vitest, FastAPI/Pydantic/OpenAI Python adapter, Supabase Auth/Postgres and pytest. Provider transport SDK/WebSocket dependency is selected only after inspecting current installed versions and current official API requirements.

## Reading and status

Read `../requirements/GUIDED_VOICE_SESSION_SPEC.md` and `GUIDED_VOICE_HERMES_INSTRUCTIONS.md` first. This is a proposed implementation plan, not implementation evidence. New file paths below are deliberate proposed artifacts, not claims of existing symbols. Revalidate source and external state before editing. No application build/deployment is authorized merely by generating this plan.

## Grounded baseline and blast radius

Inspected source paths:
- `frontend/src/App.tsx`: verified-account API construction, owner-generation invalidation, practice setup/history/progress. Integrate guided mode here without crossing identity lifetimes.
- `frontend/src/SessionView.tsx`: existing record/upload/report/retry UI. Keep its flow separate.
- `frontend/src/recording.ts`, `frontend/src/api.ts`: 30–180-second checks and upload receipt/idempotency flow. Guided transport must not reuse this upload path for short sentences.
- `frontend/src/types.ts`: recorded sessions, reports, config. Keep guided types separate and feature config explicit.
- `backend/app.py`: settings, identity/confirmed-account policy, AI controls, Supabase cutover readiness, lifespan/cleanup and route registration.
- `backend/ai.py`, `backend/models.py`: transcript/full-report/scenario adapters and strict schemas; do not use full Report as guided-turn schema.
- `backend/guards.py`: request body cap and HTTP-only middleware. New SDP and authenticated streaming/control routes need deliberate bounded policies; WebSockets must enforce their own auth/frame limits.
- `backend/storage_routes.py`, `backend/media.py`: recorded-upload duration/container/cleanup authority; keep unchanged unless a proven integration bug requires a targeted fix.
- `backend/supabase_store.py`, `supabase/migrations/202609300001_speechclear.sql`, `202609300002_atomic_api.sql`, `202609300003_legacy_import.sql`: existing owner/atomic/persistence contracts. Add new migration; do not rewrite deployed migrations.
- `backend/scripts/verify_postgres.py`: existing disposable real-SQL verification entrypoint; inspect loader/test discovery before extending.

History records an incomplete persistence cutover and a stop-before-live-account-tests boundary. Current remote state/readiness cannot be inferred from those historical entries. Treat integration readiness as a prerequisite, not an excuse to enable a hidden SQLite fallback.

## Design contract to finalize in Task 1

Proposed API prefix: `/api/v1/guided-sessions`.
- POST collection: scenario_id, goal, optional professional context and prompt_visible; idempotent command/session creation. Returns owned session metadata plus approved connection setup, never permanent secrets.
- POST `/{id}/connection`: authenticated bounded SDP offer/config exchange or equivalent provider-supported setup. Server owns configuration. Bind provider call/session handle to owner and app session.
- GET `/{id}`: authoritative session revision, current prompt, turns and status under owner checks.
- POST `/{id}/commands`: bounded command enum replay/retry/pause/resume/mute/unmute/finish, canonical command ID and expected revision. No client-provided trusted scores/transcripts.
- GET collection: separate guided history with summaries; no conversion to full-report averages.
- DELETE `/{id}`: terminate active provider session and tombstone/delete owned private data safely; prevent late callback resurrection.
- Trusted event/control channel: provider sideband on server; authenticated app-to-browser state delivery over an inspected, bounded mechanism. For app WebSockets, prefer short-lived owner/session-bound tickets over access tokens in URLs; never log tickets. Confirm revocation/account-change behavior.

Proposed entities: guided_sessions, guided_prompts, guided_turns, guided_usage/leases (or carefully integrated existing usage mechanism). Session includes owner, scenario, goal, state, revision, retry budget, active prompt, expiry, trusted provider handle and termination status. Prompts are immutable/versioned targets. Turns include unique provider/item identity, prompt ID, attempt number, recognized transcript, validated feedback, evidence basis, duration where trusted and prompt visibility context. Separate private provider handles from public responses. Use composite owner/session references, restrictive grants and RLS; trusted write functions remain privileged-only.

Do not commit to unsupported provider event names here. Finalize exact SDK/model/events, output playback completion, usage callbacks, cancellation/termination and server caps against current official docs and actual adapter probes.

## Ordered tasks

### Task 0 — Establish baseline and unresolved gates
Files: read manifests, auth/app/store/guards, frontend auth/recording/tests, doc index and current verification handoffs.
1. Recheck Git and instructions; inventory only relevant source, excluding credentials/runtime private data.
2. Run `cd frontend && npm test && npm run build` and `cd backend && uv run --frozen pytest -q`.
3. Run `cd backend && uv run --frozen python scripts/verify_postgres.py` where prerequisites permit.
4. Record actual baseline failures before modifications; isolate pre-existing failures from regressions.
5. Read authorized Supabase development metadata via MCP and verify persistence readiness without printing credentials.
Acceptance: explicit baseline receipt and exact remaining access/readiness gates; no accidental remote writes.

### Task 1 — Finalize architecture and acceptance mapping
Modify: this plan; canonical engineering log.
1. Inspect installed dependency versions and current provider docs; pick one supported API generation.
2. Verify server observation/termination and usage-cap feasibility. Reject client-timer-only design.
3. Finalize schemas, route/event mapping, state transition table, playback-vs-generation completion, budgets and privacy policy.
4. Map every spec acceptance row to a test/live receipt before writing production code.
Acceptance: executor has no guessed API/imports; changes to this proposal are documented.

### Task 2 — Define strict guided contracts
Create: `backend/guided_models.py`, `backend/tests/test_guided_models.py`, `frontend/src/guided-types.ts`.
1. Write failing tests for valid payloads and rejection of extra fields, excessive text, invalid IDs/revisions/decisions and invalid feedback evidence.
2. Run `cd backend && uv run --frozen pytest -q tests/test_guided_models.py`; require observed RED.
3. Implement minimal strict models and matching frontend contracts.
4. Rerun targeted tests; require GREEN.
Acceptance: typed, bounded commands/feedback; no client-authoritative trusted result payload.

### Task 3 — Implement deterministic drill controller
Create: `backend/guided_coach.py`, `backend/tests/test_guided_coach.py`.
1. RED tests: first prompt, retry same ID, next new ID, finite retry/simplify, replay not scored, clarify not failed, pause/mute no silence failure, stale revision/duplicate turn, end tombstone.
2. Implement pure transitions and validated decisions, independent of transport.
3. GREEN all transition tests; add property/table-driven impossible-transition cases.
Acceptance: same event cannot advance twice; provider cannot bypass progression/limits.

### Task 4 — Add additive SQL and atomic persistence
Create: `supabase/migrations/202610010004_guided_voice.sql` only if that version is unused; otherwise use next available unique version. Create `backend/tests/test_guided_postgres.py`; extend existing verifier discovery if necessary.
Modify: `backend/supabase_store.py` or create a small dedicated guided store module after inspecting adapter style.
1. RED real-SQL tests for owner reads, cross-owner refs, unauthorized writes, unique turns/commands, revision compare-and-swap, concurrency caps and trusted-only results.
2. Implement dedicated tables/RLS/grants/RPCs and cleanup/termination leases; preserve existing functions/contracts.
3. Add delete/tombstone races and watchdog claim fencing tests.
4. Run disposable verifier and adapter tests to GREEN; security-review SQL before any remote apply.
Acceptance: real PostgreSQL transaction/concurrency evidence; service-role tests not mislabeled as live two-user auth.

### Task 5 — Implement provider session adapter
Create: `backend/voice_provider.py`, `backend/tests/test_voice_provider.py`.
Modify: `backend/pyproject.toml` and lockfile only if a verified missing dependency requires it.
1. RED adapter contract tests for setup, trusted config, bounded timeouts, sideband events, cancel/playback lifecycle, usage, termination and resource closing.
2. Implement against verified provider API; no hardcoded obsolete event assumptions.
3. Fail closed on missing credentials/model or unrecognized lifecycle. Normalize safe errors; redact identifiers/secrets from logs.
4. GREEN mocked contract tests, then authorized real-provider connection probe when allowed.
Acceptance: permanent key server-only; demonstrable server termination path; contract mocks labeled honestly.

### Task 6 — Authenticated routes, event worker and watchdog
Create: `backend/guided_routes.py`, `backend/guided_runtime.py`, `backend/tests/test_guided_routes.py`, `backend/tests/test_guided_runtime.py`.
Modify: `backend/app.py`, `backend/guards.py` where required.
1. RED route tests for anonymous/invalid/unconfirmed/suspended accounts, disabled AI, unavailable persistence, cross-owner commands/reconnect/delete and body/frame caps.
2. Reuse inspected identity policy rather than fork it; register routes and lifespan workers with proper cleanup.
3. Reserve allowance before billable provider setup; use atomic active-session lease. Compensate failures without double charging or free unlimited setup retries.
4. Implement backend-observed trusted event persistence and bounded browser state delivery. Guard provider callbacks against ended/deleted state and stale revisions.
5. Implement watchdog, idle/max-duration caps and actual provider termination; add multi-worker/restart-safe lease handling.
6. GREEN route/runtime/concurrency tests.
Acceptance: browser cannot forge results, config, quota usage or active lease; logout/revocation/expiry semantics documented and enforced.

### Task 7 — Browser transport and teardown
Create: `frontend/src/voice-session.ts`, `frontend/src/voice-session.test.ts`.
Modify: `frontend/src/api.ts` only for explicit authenticated guided operations; preserve existing bound native fetch/upload guards.
1. RED tests for permission gesture/cancel races, connect failure, data channel readiness, output play rejection, local mute/pause, end, unmount, owner change and stale events.
2. Implement peer connection/microphone/remote audio/events with generation guards and AbortController.
3. Separate generated-response completion from finished playback; gate input evaluation and suppress partial/echo turns.
4. Close tracks, connection/channel/listeners/timers and requests on every terminal path. No automatic permission prompt during replay/reconnect without appropriate user gesture.
5. GREEN targeted tests.
Acceptance: original recording transport remains unaffected; no orphan local media resources.

### Task 8 — Guided call UI and memory toggle
Create: `frontend/src/GuidedSessionView.tsx`, `frontend/src/guided-flow.test.tsx`.
Modify: `frontend/src/App.tsx`, `frontend/src/types.ts`, `frontend/src/styles.css`; SessionView only if a small shared mode affordance actually belongs there.
1. RED component tests for setup, states, exact prompt identity, feedback brevity, retry/next and control availability.
2. Implement the real guided screen and separate mode entry; unavailable state is explicit.
3. RED hidden-mode tests covering target panel, captions, corrected example, history, aria-live/accessibility and focus; implement structured rendering suppression.
4. Ensure toggle/replay do not change revision/attempt unless an actual authorized command warrants it.
5. GREEN flow tests and production build.
Acceptance: memory mode hides practice text across all session surfaces without blocking accessible controls.

### Task 9 — Silence, partial turns and reconnect
Tests: existing guided controller/runtime/transport/flow test files.
1. RED tests for thinking pauses, no speech, muted silence, uncertain transcript, interrupted prompt, duplicate/out-of-order events and ambiguous disconnect during persistence.
2. Tune provider-supported patient turn detection and I'm done fallback; distinguish text-final/audio-final/business commit.
3. Implement bounded reconnect: obtain authoritative current revision, do not duplicate completed turns, require expired lease to create a new session.
4. GREEN all cases with deterministic fake clocks/events; browser confirmation later.
Acceptance: no automatic scored silence failure, hallucinated transcript, stale reply or infinite recovery loop.

### Task 10 — Guided history, recap and deletion
Modify: frontend App/history presentation, guided models/routes/store; extend guided tests.
1. RED tests for saved owned prompts/turns/qualitative recap, empty states, mode labels, history reopen and delete while active.
2. Implement persisted recap without inventing numeric progress; keep guided data out of recorded /100 averages.
3. Ensure deletion/termination saga survives provider failure and prevents callback resurrection; watchdog retries durable termination intent.
4. GREEN history/privacy tests and real-SQL delete races.
Acceptance: readback agrees with trusted saved events; privacy deletion and audio stop are independent from successful recap generation.

### Task 11 — Full regression and security review
Run:
- `cd frontend && npm test && npm run build`
- `cd backend && uv run --frozen pytest -q`
- `cd backend && uv run --frozen python scripts/verify_postgres.py`
- Ruff check/format only if installed or available through the project's established tooling; do not assume it is a pinned dependency.
- `git diff --check` plus explicit checks of new/untracked files (Git diff alone omits those files).

Review secret exposure, private-error logging, auth-generation races, owner isolation, direct client result forgery, SQL privilege escalation, uncontrolled realtime billing, duplicate commands and lifecycle leaks. Fix root causes, add regressions and rerun. Do not refactor unrelated modules.
Acceptance: exact commands/results logged; baseline features pass; unresolved failures explicitly listed.

### Task 12 — Authorized development integration
Before writes: verify exact target, current migrations/policies, existing scope authorization, independent SQL review and passing disposable tests. Apply additive migration only through Supabase MCP within authorized scope, then read back exact migration/tables/policies/grants. Do not provision production or erase legacy data. Reconcile existing cutover readiness first; do not forge a cutover receipt to enable guided sessions.
Acceptance: deployed development schema verified separately from app runtime credentials/auth; no “migration succeeded” claim based only on API response.

### Task 13 — Actual browser/provider acceptance
Create evidence: `.hermes/docs/verification/GUIDED_VOICE_VERIFICATION.md`.
1. Respect paused live-account testing: obtain participation authorization before credentials/accounts; use secure UI/vault only.
2. Run local frontend/API with established commands:
   - `cd backend && uv run --frozen uvicorn app:app --host 127.0.0.1 --port 8000`
   - `cd frontend && npm run dev -- --host 127.0.0.1`
   Verify health/ready flags and feature config before claiming usable runtime.
3. In a real browser, exercise real user speech, audible prompt, short feedback, retry then next; toggle hidden mode and replay; pause/resume/mute/I'm done/end.
4. Check permission denial, playback gesture restrictions, disconnect/reconnect and navigation/logout microphone stop. Test supported Chrome first; Safari/Firefox either verified or explicitly unsupported/unverified.
5. Read exact owned saved session/turn metadata back without printing private content. Exercise actual server limit/end termination and usage readback.
6. Perform authorized two-user isolation tests when allowed; synthetic identities and privileged DB checks are not substitutes.
7. Measure actual response latency and usage, note input/audio conditions, and record evidence scope.
Acceptance: real transport, auth, provider, application progression, persistence and teardown jointly proven, or precise BLOCKED rows remaining.

### Task 14 — Documentation and final handoff
Modify: `.hermes/docs/execution/doc.md`, this plan if implementation differed, doc index; complete guided verification matrix.
1. Record meaningful paths/decisions, RED/GREEN output, exact final commands and observed live results.
2. Mark each acceptance row PASS/FAIL/BLOCKED with evidence and limitations.
3. Provide working runtime/start instructions and concise completion report. Do not claim end-to-end if live/provider/isolation/termination proof remains blocked.
4. No commit/push or production deployment without explicit request.

## Evidence template

For each acceptance row record: requirement | status | test/command/live receipt | observed result | evidence scope | remaining gate. Distinguish local mocked tests, real SQL, browser synthetic audio, live provider speech and authorized real accounts. Never include passwords, tokens, signed URLs, private transcripts or recordings in documents.

## Risk/decision register

- Current cutover readiness may block all authenticated app work; complete local development without disabling the gate.
- Provider server controls/termination must be real, not inferred from token expiry: token expiry alone does not prove an established call ended.
- Sideband disconnect must not orphan billable calls; watchdog and durable lease need termination/retry evidence.
- Output event completion and physical playback completion differ; incorrect gating leads to echo or clipped user speech.
- Realtime transcription may differ from audio interpretation; feedback must flag uncertainty instead of exact-score fiction.
- SDP/body/frame limits, WebSocket auth and ticket leakage require separate review from ordinary HTTP routes.
- Existing untracked source and active parallel edits require ownership/context checks; do not reset the workspace.
- Hide Prompt is a UI practice mode, not a claim that network-delivered text is inaccessible to its owner.
- Previously paused live tests remain a human gate; a one-shot execution instruction is persistence, not permission to bypass it.

## Executor refinement — 2026-10-01

Current baseline: backend `uv run --frozen pytest -q` 235 passed; disposable PostgreSQL verifier 34 passed; frontend 58 passed and TypeScript/Vite build passed. Installed OpenAI 2.54.0, FastAPI 0.142.2, Pydantic 2.13.5, HTTPX 0.28.1. Explicit raw-WebSocket transport dependency `websockets>=15,<17` resolved/locked to 16.1.1; OpenAI's SDK Realtime extra is not used (its version range differs). Structured Responses use existing HTTPX transport with strict schemas. Development target read back through MCP is `https://qpheitaamyzcekzvbcox.supabase.co`; three recorded remote migrations now exist (historical empty-schema statements are superseded). Protected runtime cutover receipt currently validates. Never recreate/forge it.

### Fixed integration contract

- Use OpenAI Realtime GA unified WebRTC setup: backend multipart POST `/v1/realtime/calls` with `sdp` and `session`; extract the opaque call ID from `Location`; attach backend sideband `wss://api.openai.com/v1/realtime?call_id=...`; terminate with POST `/v1/realtime/calls/{call_id}/hangup`. Do not mix GPT-Live `/live` examples/events into this adapter. Model is backend-configurable; exact account/model access and call behavior remain live gates.
- Backend generates three short, professional repetition targets using structured AI output with existing scenario/goal/profile context. No runtime fixture prompts, fake transcripts or seeded praise. Backend separately evaluates finalized provider audio transcripts with strict structured output; MVP evidence is wording/transcript only, not pronunciation/prosody. Realtime speaks server-authored canonical target/validated feedback, not arbitrary client coaching.
- Semantic VAD with low eagerness and `create_response=false`, `interrupt_response=false`; server requests every output. Sideband observes committed audio identity and transcription completion; only correlated audio items in an authoritative listening state are eligible. Generated completion and `output_audio_buffer.stopped` are separate; only actual provider playback stop permits listening. No browser-reported transcript/tool output is accepted by an app endpoint.
- Browser WebRTC is audio-only with no provider data channel. Server validates offer AND answer: exactly one active `m=audio`, no additional media, application/SCTP or video. This follows OpenAI's server-controlled example; coding a receive-only channel alone is not an authorization boundary. Sideband additionally rejects configuration changes/input-text/unauthorized responses. Audio-only cannot prove a human microphone source or enforce admission of off-window audio; trusted evaluation discards off-window input. Spending uses duration/usage caps and actual hangup, not token expiry. Residual lifecycle failure windows are documented, not waived.
- App transport uses authenticated HTTP snapshot polling/heartbeat rather than a second browser WebSocket or access-token URL. GET is read-only; POST heartbeat renews only a bounded browser-presence lease without extending absolute expiry. All media is tab memory only; no guided prompt, transcript or result in browser persistent storage.

Public session DTO (matching Python/TypeScript and SQL snapshot): `id`, `scenario_id`, `goal`, `created_at`, `expires_at`, `state`, `revision`, `prompt_visible`, `muted`, `max_retries`, `prompts`, `prompt_index`, `attempts_on_prompt`, `turns`, `recap`, `status_message`. Prompts: `id`, `text`, `exercise_type` (`repetition`), `position`. Turns: `id`, `prompt_id`, `provider_item_id`, `attempt`, `transcript`, `feedback`, `prompt_visible`, `created_at`. Feedback required fields: `prompt_id`, nullable `strength`, nullable `priority_correction`, nullable `corrected_example`, `decision` (retry/next/simplify/finish/clarify), `evidence_basis` (transcript/uncertain), nullable `evidence_quote`, `spoken_feedback`. Quotes must occur literally in transcript; uncertain input cannot create a failed attempt. Feedback is bounded to three short sentences and one correction. Recap: `practiced_exercises`, `completed_attempts`, `focus`, `next_practice`; no numeric score or unsupported improvement claim. Empty prompts are allowed only before provider generation; immutable prompt identities/text and append-only turn identities survive retries/reconnect.

Routes under `/api/v1/guided-sessions`: POST `{command_id,scenario_id,goal,context,prompt_visible}`; GET collection `{sessions:[DTO...]}`; GET `/{id}` DTO; POST `/{id}/connection` `{command_id,expected_revision,sdp}` -> `{sdp,session:DTO}`; POST `/{id}/commands` `{command_id,expected_revision,prompt_id,action,prompt_visible?}` -> DTO; POST `/{id}/heartbeat` -> DTO; DELETE `/{id}` -> 204. Actions: replay/retry/done/pause/resume/mute/unmute/finish/visibility/reconnect. No scoring/transcript fields accepted. UUIDs are canonical lowercase, extra fields rejected, SDP and JSON remain within existing 32 KiB request cap. Finish and deletion must be permitted independently of AI availability for owned sessions; creation/connection require confirmed auth, readiness, controls, provider and quota. Stale revisions return 409; command replay is idempotent. Resume/reconnect orientation requires a user gesture to acquire fresh media when necessary.

Dedicated additive `202610010004_guided_voice.sql` and `backend/guided_store.py` own service-only `speechclear_guided_api(p_action,p_owner,p_payload)`; existing migrations are not edited. Adapter methods:
`reserve(owner,data,daily_seconds,monthly_seconds,max_seconds)`, `get(owner,id)`, `list(owner)`, `commit(owner,id,expected_revision,data,command_id=None)`, `heartbeat(owner,id)`, `claim_connection(owner,id,expected_revision,worker_id)`, `attach(owner,id,worker_id,call_id)`, `release_call(owner,id,worker_id,call_id,confirmed)`, `usage(owner,id,worker_id,tokens)`, `watchdog()`, `delete(owner,id)`, `ready()`, `close()`.

`reserve` accepts initial DTO, enforces one active session per owner, atomically reserves the full permitted duration (default 300 seconds) against distinct guided daily/monthly budgets (1800/18000 seconds), and sets server-created times/absolute expiry. Reservation is never refunded after provider setup failure. `commit` compares revision atomically, sets `revision=expected+1`, prohibits ended/deleted resurrection, prompt mutation, turn overwrite/duplicate identities, and atomically normalizes immutable prompt/turn children. Command receipt lives in the same transaction. `claim_connection` fences worker ownership, expires abandoned claims, permits at most three connection setups for a session, and cannot extend absolute expiry. `attach` retains the private call handle in a service-only lease/termination table; no provider handle in public DTOs. A termination-intent record must survive deletion and provider failure. `release_call` verifies exact worker/call generation. `watchdog` returns service-only owner/id/worker/call handles due to absolute expiry, browser lease expiry, idle/grace, suspension/kill switch, token cap or pending deletion; stale candidates must be rechecked/fenced before state writes. Budget and retry constants are server-owned; hard SQL maxima remain fail-closed. All service RPCs use strict payload validation and existing owner/global lock order. Ordinary authenticated role gets owner SELECT only on private practice entities, no provider-handle/lease access and no generated writes.

### Vertical sequencing and file ownership

1. Agree this contract before parallel writes. SQL/store lane owns only new migration, guided store, SQL/store tests and verifier discovery. Backend lane owns guided models/controller/runtime/routes/tests, not `app.py` or provider adapter. Frontend lane owns guided types/API/transport/view/tests plus App/types/styles integration. Parent owns provider adapter/tests/dependency lock, FastAPI app wiring, final evidence and remote operations. No shared-file simultaneous writers.
2. Each lane executes small observed RED→GREEN behavior slices, not all-tests-first horizontal scaffolding. First integrated tracer is reserve→generated prompt→authenticated SDP→trusted sideband transcript→bounded feedback→CAS saved turn→retry/next→hangup. Then visibility/controls/recovery/history/security hardening.
3. Parent independently reruns all tests/build/disposable SQL, performs spec review then quality/security review, fixes failures with regressions, and reviews SQL before any approved additive development apply/readback.
4. Real signed-out browser and synthetic browser-media proof are permitted without using Andrew's account. Real-account/user-speech/provider acceptance and two-user isolation remain paused pending explicit participation authorization. Complete independent local work and record the exact remaining gate rather than bypassing auth.

### Executed refinement and remaining acceptance

Implemented the ordered package, then corrected independently reproduced failures with vertical regressions rather than stopping at the initial plan. Preparation is durably claimed once; full normalized creation context is fingerprinted without retaining raw context. Store additions are `claim_preparation`, `reserve_evaluation`, and `text_usage`; evaluation reservations include uncertain/invalid attempts and survive worker changes. Trusted text-response IDs/tokens join all voice/ASR lease generations in the 6000-token allowance. Provider `generate`/`evaluate` expose optional `on_usage(response_id,total_tokens)` callbacks before output validation. Retry policy is server-owned configurable 0–2, persisted per session; defaults remain two retries.

Separate local 100ms deadlines initiate exact-call hangup independently from the SQL watchdog/business locks. Committed items freeze into reviewing and retain prompt/visibility/epoch through ASR completion; silence excludes active/pending input, with separate speech/ASR deadlines. Final feedback persists as an interruptible speaking phase and ends only after matched generation/transcript/server-buffer drain. Polling uses heartbeat's authoritative snapshot, not an extra GET per cycle. Weak lock/connection registries and terminal counter cleanup bound resource retention. SQL watchdog termination creates a recap from actual saved turns. Migration source is now applied to the authorized development project as `20261001064804 / speechclear_guided_voice`; further SQL changes must use a new additive migration, not edit this applied artifact.

See `../verification/GUIDED_VOICE_VERIFICATION.md` for current receipts. Local backend/SQL review is approved and automated checks pass at the recorded checkpoints. Actual signed-out browser checks passed; the optional synthetic local-peer ICE experiment failed and is preserved, not represented as transport success. End-to-end acceptance is still blocked on the standing real-account/microphone/provider participation gate. Model-list/readiness/anonymous access checks and synthetic/bootstrap identities do not replace that gate. No production deployment or Git publication was performed.
