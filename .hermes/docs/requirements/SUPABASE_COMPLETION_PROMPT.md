# SpeechClear — Supabase + Web App Completion Prompt

Act as a senior full-stack engineer and security reviewer. Implement and verify a fully connected SpeechClear private desktop-browser alpha. Do not stop at a plan, scaffolding, passing mocks, or configured credentials. Use this document as an execution checklist; mark each item PASS, FAIL, or BLOCKED with evidence.

## Context and inputs

Repository: `/Users/me/Desktop/professional-communication-coach`.
Supabase project reference: `qpheitaamyzcekzvbcox`. Verify target before remote operations.
Stack: React/TypeScript/Vite frontend, FastAPI backend, OpenAI scenario generation/transcription/coaching, Supabase Auth. Application data currently uses transitional SQLite, and audio uploads directly to FastAPI; these must be replaced by tested Supabase database/private Storage integration.

Inspect before changing: `doc.md`, `README.md`, `IMPLEMENTATION_CONTRACT.md`, `SUPABASE_SETUP.md`, `BACKEND_VERIFICATION.md`, `FRONTEND_VERIFICATION.md`, all four `DAY_*` requirement documents, frontend manifest/source, backend manifest/source/tests, and any existing migrations. Recheck git status and actual implementation rather than trusting historical receipts.

Last independently observed baseline: 41 backend tests, 18 frontend tests, Ruff checks, and production frontend build passed. This is historical, not evidence for your current changes. Live authenticated end-to-end coaching remains unverified.

Known blockers:
- Browser fetch receiver bug was fixed in the shared API wrapper; native Chromium reproduction and transport verification passed. Recheck regression, do not assume every auth issue has the same cause.
- User reached a generated scenario and recorded an answer. Screenshot shows `00:30`, `Your response is ready`, and `Invalid audio media or duration`. Cause has NOT been determined. Investigate actual browser audio, not just a fabricated ffmpeg file or mocked probe.
- Claude Code Supabase MCP is registered including Storage; last verified status Pending approval. Registration is not authentication. Supplied URL does not enforce read-only. MCP auth and runtime application credentials are separate.

## Boundaries

- Never print, log, commit, or expose `.env` secrets, passwords, verification codes, tokens, verification-link fragments, signed URLs, or private user content. Preserve existing `.env` values; Andrew may edit it concurrently.
- OpenAI/privileged Supabase/database credentials stay backend-only. Frontend receives only project URL and publishable/anon key.
- No fake accounts, authentication bypasses, fabricated reports, synthetic success receipts, or insecure fallbacks to SQLite after migration.
- No destructive remote resets, truncation, deletion of real user data, billing changes, commits, pushes, or deployments to public production without explicit approval. Additive scoped migrations may proceed only within authorized development-project access; request approval for destructive or production changes.
- Use designated test accounts/data with safe cleanup. Obtain secrets through approved secure mechanisms or user UI, never chat or shell arguments.
- Load relevant debugging, Supabase, TDD, and agent-browser skills. Use agent-browser for real browser checks; if unavailable, resolve installation or document the exact blocker and an explicit alternative.
- Keep every meaningful implementation/verification batch in `doc.md`: affected files, rationale, exact commands, observed results, evidence level, remaining risks. Never mark a checkbox complete from code inspection alone when it requires execution.

## Ordered execution checklist

### 1. Baseline and configuration
- [ ] Run current backend tests/lint, frontend tests/build; record exact results.
- [ ] Confirm target project, actual runtime settings, API/frontend connectivity, and credentials presence without exposing values.
- [ ] Validate public-config endpoint cannot expose privileged keys; missing/invalid configuration fails closed.
- [ ] Verify Supabase Email provider, confirmations, Site URL, allowed redirects, JWT issuer/audience/signing configuration, and development email/SMTP limitations.
- [ ] Authenticate MCP if needed through user approval; respect read-only restrictions. Use a separately authorized migration workflow rather than silently enabling write access.

### 2. Fix real browser recording rejection
- [ ] Reproduce `Invalid audio media or duration` with real MediaRecorder output in supported desktop browsers.
- [ ] Trace MIME/container, extension, byte size, codec, recorder stop/final chunk order, timer precision, uploaded fields, ffprobe output, and backend rejection branch. Inspect safe metadata only.
- [ ] Test whether streaming WebM lacks container duration, whether real duration is slightly under 30 seconds, or whether another validation condition fails. Do not assume a cause.
- [ ] Add a failing regression using actual browser-generated audio and fix the root cause. If container duration is absent, derive actual decoded duration via bounded trusted decoding instead of trusting client claims. Handle legitimate boundary precision explicitly without allowing arbitrary undersized recordings.
- [ ] Keep file-size/duration/codec limits, bounded decoding/timeouts, ownership checks, clear errors, and cleanup intact. Do not disable validation to get a green flow.
- [ ] Verify allowed browser media plus too-short/long, empty, malformed, MIME-spoofed, and oversized uploads.

### 3. Prove authentication lifecycle
- [ ] Signup -> confirmation email -> callback -> verified sign-in -> protected request works in the browser.
- [ ] Test existing-user sign-in, sign-out, token refresh, expired/invalid tokens, magic link, password recovery/update, and callback errors.
- [ ] Verify unverified users cannot invoke AI, and client-controlled profile metadata cannot grant verification or authority.
- [ ] Test account switching/sign-out during in-flight requests; old-owner data cannot reappear.
- [ ] Verify backend derives owner exclusively from a verified token; no body/header/query override.

### 4. Implement Supabase application persistence
- [ ] Inspect current SQLite schema and data before designing migrations. Map existing records/relationships without dropping real data.
- [ ] Create versioned migrations for every required table: profiles, practice sessions, attempts, transcripts, reports, usage, subscriptions, audit events, documents, object metadata, and isolated knowledge chunks if implemented.
- [ ] Add ownership, constraints, indexes, referential integrity, and Row Level Security to all user-data tables; document policies and grants.
- [ ] Replace active SQLite reads/writes with Supabase/Postgres adapters while preserving UI/API contracts. Define a safe explicit migration/backout strategy; do not silently dual-write or fallback.
- [ ] Apply migrations through authorized tooling and read back exact remote schema/policies to verify effects.
- [ ] Test actual access as anonymous, User A, and User B across SELECT/INSERT/UPDATE/DELETE. Checking that RLS is enabled is insufficient.
- [ ] Privileged backend paths must explicitly enforce ownership because service-role credentials bypass RLS. Test both app API and direct Supabase access.

### 5. Implement private Storage and trustworthy processing
- [ ] Create private temporary-audio/document buckets and owner-scoped paths `{user_id}/{resource_id}/{filename}`.
- [ ] Implement short-lived upload authorization, private upload, processing, and tightly scoped retrieval/download. Storage ownership derives from verified identity.
- [ ] Verify actual uploaded bytes/media/duration and object/session ownership server-side. Do not trust uploaded metadata, filenames, MIME headers, or client duration alone.
- [ ] Make processing idempotent and concurrency-safe across workers; enforce quotas/suspension/kill switch before expensive calls and atomically reserve usage.
- [ ] Validate strict model JSON before persistence, keep instructions separate from untrusted transcripts/reference text, and require transcript evidence.
- [ ] Delete raw audio after processing by default and no later than policy limits; implement reliable retry/crash cleanup and verify objects disappear. Explain external provider retention separately.

### 6. Verify the real product loop
- [ ] With real verified test accounts and real OpenAI responses: save profile -> create personalized scenario -> record -> upload -> transcribe -> validate/persist feedback -> retry in same session -> compare.
- [ ] Confirm browser history/progress uses persisted results and survives logout/login and API restart.
- [ ] Exercise provider errors/timeouts, invalid model output, duplicate/retried requests, concurrent quota exhaustion, suspension, and global kill switch. Failed processing must not persist a pretend report.
- [ ] Verify every frontend action reaches the intended real endpoint with correct state/loading/error recovery.

### 7. Finish privacy, restricted knowledge, and auth observability
- [ ] Implement session/history/document/account deletion with dependency-safe cleanup of rows, objects, indexes, and auth identity. Specify retry behavior and retention exceptions; verify with readback and failed subsequent access.
- [ ] Complete restricted PDF/DOCX/TXT/Markdown/CSV ingestion and owner-isolated retrieval per Day 4 only if safely supported. Enforce actual format, page/count/content limits and prompt-safety boundaries. Keep general uploads disabled without dependable scanning and document restriction honestly.
- [ ] Add safe structured auth/security events with timestamp, operation, result/status and correlation ID; avoid secret headers, tokens, links, passwords and content. Define which events are browser, backend or Supabase-provider logs.
- [ ] Prove logs/errors/bundles/source maps are free of privileged secrets and private content. Provide practical troubleshooting instructions without requiring sensitive screenshots/HAR exports.

### 8. Release gate
- [ ] Run canonical unit, API, database-policy, Storage, browser end-to-end and secret-scanning checks from a clean install.
- [ ] Two real users cannot access each other's profiles, sessions, attempts, transcripts, reports, audio, documents/chunks, usage or subscriptions—including guessed IDs and direct SDK requests.
- [ ] Complete setup/API/schema/RLS/retention/threat-model docs, secure environment separation, rollback procedure, and explicit known limitations.
- [ ] If deployment is authorized and hosting access exists: deploy to controlled staging with HTTPS, API routing/CORS and exact auth redirects; add privacy-safe Sentry/PostHog configuration per requirements; repeat real browser flow and isolation checks on deployed URLs.
- [ ] If hosting/auth/access blocks any gate, mark BLOCKED with exact human action required. Do not call the app fully connected or release-complete while mandatory gates remain unverified.

## Final handoff

Report:
1. Completed checklist with PASS/FAIL/BLOCKED evidence.
2. Root cause/fix for the audio rejection.
3. Changed files and applied migrations.
4. Exact test commands/results and live browser/provider/database evidence.
5. Running URLs, deployment state, remaining blockers and limitations.
6. Updated `doc.md` location and one concrete next action.

Definition of done: real authorized users can complete the browser practice/retry/privacy loop with Supabase-backed data/private storage and real OpenAI, cross-user isolation and controls are proven, and required release gates either pass or are explicitly blocked. Code written or mocked tests passing alone is not completion.
