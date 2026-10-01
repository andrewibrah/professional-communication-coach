# SpeechClear — compact resumption checkpoint

## Superseding current handoff

Read [SUPABASE_IMPLEMENTATION_HANDOFF.md](SUPABASE_IMPLEMENTATION_HANDOFF.md) before the historical sections below. Three migrations are now applied to the authorized development root; protected import preserved one session/one usage row; default runtime is Supabase-only and local API/proxy are healthy. Current local gates: 235 backend tests, Ruff checks, 58 frontend tests and build. Live anonymous CRUD and controlled Storage transport/deletion passed. Actual User A/User B and signed-in browser/provider acceptance remain BLOCKED at Andrew's explicit stop-before-account-tests instruction. All documentation is under `.hermes/docs/`; use the current work log and actual code rather than old pending-SQLite claims below.

Documentation location update: all authored docs are organized under `.hermes/docs/`. Start with [the index](../README.md); the canonical work log is [execution/doc.md](../execution/doc.md), completion requirements are [requirements/SUPABASE_COMPLETION_PROMPT.md](../requirements/SUPABASE_COMPLETION_PROMPT.md), and current focused evidence is in `../verification/`. Root-level document paths below are historical handoff references, not current locations. This checkpoint's implementation state is historical; recheck the work log and live files before acting.

## Active objective and authorization
Andrew authorized implementation of: (1) Supabase Postgres application tables and RLS, (2) frontend/API persistence replacing SQLite, and (3) private Supabase Storage audio uploads. He requested context cleanup before implementation. Supabase management MUST use MCP, not the Supabase CLI. Preserve credentials and existing user data. Additive development changes only; no destructive resets, real-data deletion, public deployments, commits or pushes.

## Repository and canonical requirements
Repository: `/Users/me/Desktop/professional-communication-coach`.
Read `SUPABASE_COMPLETION_PROMPT.md` as the detailed security/verification checklist, `doc.md` as the canonical execution log, and `SUPABASE_COMPLETION_REPORT.md` for the prior checkpoint and superseding MCP access evidence. Also inspect `IMPLEMENTATION_CONTRACT.md`, `README.md`, `SUPABASE_SETUP.md`, and four `DAY_*` documents. Recheck current git state; previous state was main with application files untracked.

## Verified MCP access — no management-access blocker
Target: `qpheitaamyzcekzvbcox`; exact project URL `https://qpheitaamyzcekzvbcox.supabase.co`.
Active Hermes profile: `telegramlite`, home `/Users/me/.hermes/profiles/telegramlite`.
Authenticated Supabase connection uses `npx -y mcp-remote@0.14.3` with the supplied project-scoped endpoint/features, HTTP-only transport, profile-scoped OAuth state and no secrets in command arguments. Existing IBKR config preserved. Independent Hermes connection test discovered 23 tools. JOSE executed read-only MCP `get_project_url` and verified exact target. User subsequently ran MCP reload; Supabase is now in the live tool catalog. Discover exact current tool schemas using tool search/describe before calling. Do not read or print OAuth token files.
OpenCode was separately configured but its OAuth failed `Unrecognized client_id`; that does NOT invalidate JOSE's working MCP. Direct Hermes HTTP OAuth hit an SDK compatibility issue; do not upgrade Hermes core or use unauthenticated fallbacks to resolve it.

## Current app architecture and credentials
React/TypeScript/Vite frontend -> `/api` proxy -> FastAPI backend -> owner-scoped transitional SQLite; frontend uses Supabase Auth; backend uses real OpenAI adapters. Application data and audio are NOT yet connected to Supabase Postgres/Storage. No remote migrations or writes performed so far.
Safe `.env` presence check: correct project URL, public/publishable key and OpenAI key present; backend service-role key and database URL absent at last check. MCP OAuth does not supply application runtime credentials. Recheck presence without printing values; preserve concurrent `.env` edits. Consider whether owner-token PostgREST/RPC adapters satisfy the security design before requiring privileged credentials; do not fabricate access or bypass verification.
SQLite inspected read-only: one existing session, one usage record, zero profiles/attempts/operations/controls/audit. Preserve all rows and ownership; inspect schema/relationships and safe counts only. A cutover needs explicit protected backup/export, verified owner mapping/import, and documented backout. Never silently dual-write or fall back after migration.

## Existing code and interfaces
Backend: `backend/app.py` Settings/routes, `store.py` Store methods, `auth.py` asymmetric JWT verification and server-side email confirmation, `guards.py`, `media.py`, `ai.py`, `models.py`, tests and `pyproject.toml`/`uv.lock`.
Frontend: `frontend/src/App.tsx`, `api.ts`, `SessionView.tsx`, `recording.ts`, `types.ts`, auth dialog/lifecycle tests, `package.json`/lock.
Existing API includes profile, scenarios, sessions, multipart attempt processing with canonical UUID Idempotency-Key, usage, session/history deletion. UI/API contracts should remain coherent while upload changes to signed private Storage.
Required persistence tables include profiles, practice sessions, attempts, transcripts, reports, usage, subscriptions, audit events, documents and object metadata. Knowledge ingestion remains disabled unless safely implemented. All user-owned data needs tested RLS, ownership, constraints, grants/indexes/FKs; privileged paths bypassing RLS must explicitly enforce ownership. Quota/idempotency/completion require actual atomic multi-worker transactions, not service-role read/check/write races. Signed paths must be owner/resource scoped and actual bytes decoded server-side; temporary raw audio deletion needs retry/crash cleanup.

## Confirmed browser audio fix and evidence
Chromium's actual app RecordingController/MediaRecorder output lacked duration metadata; original probe derived zero and rejected valid media. A boundary clip declared 30.0031s decoded to 29.94s; a 31.2021s clip decoded to 31.14s. `backend/media.py` now validates size/container/audio streams and decodes mono 16-bit PCM at 16 kHz with a 181-second output cap, file/pipe protocol whitelist and 20-second timeout. Decoded acceptance permits only 150ms boundary precision; client declaration remains 30–180s. Existing ownership/control/cleanup retained.
Actual non-private Chromium tone fixtures: `backend/tests/fixtures/browser-audio.json`, `chromium-short.webm`, `chromium-boundary.webm`, `chromium-valid.webm`. Regression tests in `backend/tests/test_browser_media.py`; reproducible capture in `frontend/scripts/capture_browser_audio.py`. RED two browser failures, then GREEN. This is actual browser encoding, not personal speech, real-provider coaching, Safari or Firefox proof.
Shared frontend API native fetch receiver fix already exists and was rechecked with a real Chromium invalid-token request reaching backend. Do not revert it.

## Last actual verification
Backend: `uv sync --frozen`, `uv run --frozen pytest -q` -> 53 passed; Ruff lint and format checks passed, 21 Python files formatted. Existing Python environment, not a fresh install.
Frontend: `npm ci` -> zero audit vulnerabilities (one deprecated dependency warning); `npm test -- --run` -> 18 tests across six files; `npm run build` -> TypeScript/Vite success.
Live public Auth settings: Email enabled, confirmations required; JWKS ES256. Site URL/redirects/SMTP require authorized MCP/dashboard inspection.
Local frontend/API/proxy HTTP 200; anonymous protected requests 401; document upload route 404. Secret-value scan found no configured privileged values in source/docs/bundle; scope excluded env, user data, dependencies, Git history and external logs. No frontend source maps.
Local URLs were `http://localhost:5173` and `http://127.0.0.1:8000`; conversation-owned processes, recheck listeners rather than assuming alive. Runtime backend was restarted after audio fix.

## First next actions after context cleanup
1. Load relevant Supabase implementation, TDD and debugging skills; inspect current repository code/manifests before edits.
2. Through MCP, verify exact target then inspect existing public schema/migrations/private buckets read-only; avoid private row contents and API-key tool output.
3. Establish additive schema/RLS/atomic RPC/storage design and runtime auth strategy from observed state. Resolve development/production safety and any truly required credentials through secure user UI, never chat.
4. Implement vertical slices with failing tests first; apply authorized additive migrations through MCP and read back exact remote effects; integrate adapters, owner-isolated signed uploads and lifecycle cleanup.
5. Exercise actual direct-access A/B/anonymous policies, actual Storage bytes/deletion and frontend/API persistence. Live two-account/email/provider gates require designated accounts/secure user participation if unavailable.
6. Document every meaningful action, exact command/tool, observed result and evidence boundary in `doc.md`. Finish only on real verified delivery or a specific human-input blocker, never code inspection or mocked success alone.
