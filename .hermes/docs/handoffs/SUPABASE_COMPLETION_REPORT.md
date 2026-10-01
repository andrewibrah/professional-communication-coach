# Supabase completion checklist — execution receipt

Overall: BLOCKED, not release-complete. Status is for each full criterion, not merely a passing subset. PASS entries specify local versus live evidence; FAIL means required implementation is missing; BLOCKED means proof or remote action requires access/input.

## Subsequent MCP access verification (supersedes earlier access blocker)

Andrew requires MCP-only Supabase management, not the Supabase CLI. JOSE's active Hermes profile now has an authenticated project-scoped mcp-remote bridge: independent connection test discovered 23 tools, and JOSE directly invoked `get_project_url` through the MCP SDK with an empty argument object. The read-only result matched `https://qpheitaamyzcekzvbcox.supabase.co`. Therefore earlier CLI project visibility is no longer a management-access blocker; the statuses below are the earlier implementation checkpoint, not a claim that MCP remains inaccessible. Application backend credentials/live account gates remain separate. No remote mutations have been performed. OpenCode's separate OAuth attempt failed `Unrecognized client_id`; do not confuse its status with JOSE's working bridge. Full evidence is in `doc.md`.

## Human action required

Authorize access to development project `qpheitaamyzcekzvbcox` using the correct Supabase CLI/MCP account or project Dashboard. Existing CLI login lists two different projects. Privately configure backend `SUPABASE_SERVICE_ROLE_KEY` and an authorized `SUPABASE_DB_URL`/migration workflow without overwriting other `.env` fields. Confirm development scope before additive remote migrations. Designate two test accounts and provide login/confirmation through secure user UI, never chat, shell arguments, screenshots or HAR.

## Root cause and verified fix

Actual Chromium MediaRecorder output from the application RecordingController lacks ffprobe duration metadata. Original code derives zero and rejects the file. A controlled 30.0031-second browser recording also decodes to 29.94 seconds, demonstrating codec/start-stop precision. Fix: validate byte size/container/audio streams, then decode to mono 16-bit 16 kHz PCM with a 181-second output cap, file/pipe protocol allowlist and 20-second timeout. Duration comes from decoded sample count, not client claims. Decoded bounds allow only 150ms precision tolerance; declared bounds remain strictly 30–180 seconds. No auth/ownership/quota checks removed. Raw temporary files still removed in finally.

Fixtures contain a non-private browser-generated tone, not Andrew’s speech. This confirms the browser/container defect; it does not prove the original personal recording or live transcription/coaching. Firefox/Safari remain unverified.

## Item-by-item evidence

### 1. PASS — Run current backend tests/lint, frontend tests/build; record exact results.

Current baseline 41/18; final backend 53 and frontend 18. Ruff and production build passed. npm ci completed; uv sync --frozen checked installed environment, not a fresh Python environment.

### 2. BLOCKED — Confirm target project, actual runtime settings, API/frontend connectivity, and credentials presence without exposing values.

URL matches target and HTTP connectivity passes; public/OpenAI keys present. Service-role/database credentials absent; CLI project list excludes target, so remote project authority is not proven.

### 3. PASS — Validate public-config endpoint cannot expose privileged keys; missing/invalid configuration fails closed.

test_config_security.py executes privileged/unknown public-key rejection and protected fail-closed requests; live endpoint exposes only seven allowlisted public fields.

### 4. BLOCKED — Verify Supabase Email provider, confirmations, Site URL, allowed redirects, JWT issuer/audience/signing configuration, and development email/SMTP limitations.

Live Auth settings HTTP 200: Email enabled, autoconfirm false. JWKS HTTP 200: ES256. Runtime audience authenticated. Dashboard Site URL/redirects/SMTP limits unavailable with current access.

### 5. BLOCKED — Authenticate MCP if needed through user approval; respect read-only restrictions. Use a separately authorized migration workflow rather than silently enabling write access.

No MCP approval/OAuth undertaken and no write workflow enabled. Current CLI login cannot see required project. Authenticate correct account through approved user UI.

### 6. BLOCKED — Reproduce `Invalid audio media or duration` with real MediaRecorder output in supported desktop browsers.

Chromium 154 MediaRecorder reproduction confirmed; Firefox/Safari and Andrew’s original microphone recording not independently captured. Controlled oscillator input is real browser-encoded media, not a user speech/end-to-end test.

### 7. PASS — Trace MIME/container, extension, byte size, codec, recorder stop/final chunk order, timer precision, uploaded fields, ffprobe output, and backend rejection branch. Inspect safe metadata only.

Actual app RecordingController generated audio/webm;codecs=opus, response.webm, three byte counts and fractional performance.now durations. ffprobe identified audio/opus, matroska,webm and absent duration. API form fields exercised with actual bytes and test-only identity/provider.

### 8. PASS — Test whether streaming WebM lacks container duration, whether real duration is slightly under 30 seconds, or whether another validation condition fails. Do not assume a cause.

Observed missing duration plus boundary decoded 29.94s against declared 30.00310000014305s; 31.202099999904632s recording decoded 31.14s. Original validator rejected both with exact reported 422 error.

### 9. PASS — Add a failing regression using actual browser-generated audio and fix the root cause. If container duration is absent, derive actual decoded duration via bounded trusted decoding instead of trusting client claims. Handle legitimate boundary precision explicitly without allowing arbitrary undersized recordings.

Actual browser fixtures failed first (two failures, one pass). Bounded PCM decoding fix passed. 150ms decoded boundary tolerance; declared range remains 30–180. Two-second actual media cannot pass by claiming 30.

### 10. BLOCKED — Keep file-size/duration/codec limits, bounded decoding/timeouts, ownership checks, clear errors, and cleanup intact. Do not disable validation to get a green flow.

Local size/container/audio-stream validation, timeout, decoded duration, ownership and finally cleanup preserved/tested. Full browser codec matrix and Supabase object ownership are not verified; no Storage path implemented.

### 11. BLOCKED — Verify allowed browser media plus too-short/long, empty, malformed, MIME-spoofed, and oversized uploads.

Chromium WebM and WAV, malformed, spoofed MIME/container, short/long and oversize exercised; decode timeout and precise boundaries tested. Other supported browser formats remain unverified.

### 12. BLOCKED — Signup -> confirmation email -> callback -> verified sign-in -> protected request works in the browser.

Requires designated real test account and confirmation-email access. No accounts created or authentication bypassed.

### 13. BLOCKED — Test existing-user sign-in, sign-out, token refresh, expired/invalid tokens, magic link, password recovery/update, and callback errors.

Local SDK/UI and signed-token tests pass; real login/refresh/magic-link/recovery/callback lifecycle not exercised.

### 14. BLOCKED — Verify unverified users cannot invoke AI, and client-controlled profile metadata cannot grant verification or authority.

Local confirmation helper rejects user_metadata verification and wrong subject; live unverified-account AI denial not exercised.

### 15. BLOCKED — Test account switching/sign-out during in-flight requests; old-owner data cannot reappear.

Existing frontend regression holds a response across sign-out and confirms private history stays cleared; SDK mocked. Real two-account switching not exercised.

### 16. BLOCKED — Verify backend derives owner exclusively from a verified token; no body/header/query override.

Signed-token verifier tests reject bad expiry/audience/issuer/signature; owner-scoped API tests pass with test-only identity adapter. Real verified-token owner-override attempts not exercised.

### 17. PASS — Inspect current SQLite schema and data before designing migrations. Map existing records/relationships without dropping real data.

SQLite opened read-only; schema/columns/FKs inspected in store source and counts collected without private row content. One session and one usage record preserved.

### 18. FAIL — Create versioned migrations for every required table: profiles, practice sessions, attempts, transcripts, reports, usage, subscriptions, audit events, documents, object metadata, and isolated knowledge chunks if implemented.

Required Postgres migrations not implemented. Stopped at genuine target-access blocker rather than producing unexercised migration scaffolding.

### 19. FAIL — Add ownership, constraints, indexes, referential integrity, and Row Level Security to all user-data tables; document policies and grants.

Required Supabase ownership constraints/indexes/RLS policies/grants not implemented or applied.

### 20. FAIL — Replace active SQLite reads/writes with Supabase/Postgres adapters while preserving UI/API contracts. Define a safe explicit migration/backout strategy; do not silently dual-write or fallback.

Active app still explicitly uses transitional SQLite. No migration, dual-write or hidden fallback introduced.

### 21. BLOCKED — Apply migrations through authorized tooling and read back exact remote schema/policies to verify effects.

No authorized target migration access and no privileged backend/database credentials. No migrations applied.

### 22. BLOCKED — Test actual access as anonymous, User A, and User B across SELECT/INSERT/UPDATE/DELETE. Checking that RLS is enabled is insufficient.

Remote schema/policies and designated User A/User B credentials unavailable.

### 23. BLOCKED — Privileged backend paths must explicitly enforce ownership because service-role credentials bypass RLS. Test both app API and direct Supabase access.

Local owner-scoped API tests pass; privileged Supabase adapter/direct-SDK isolation not implemented or exercised.

### 24. BLOCKED — Create private temporary-audio/document buckets and owner-scoped paths `{user_id}/{resource_id}/{filename}`.

Private buckets not created; authorized target write access absent.

### 25. FAIL — Implement short-lived upload authorization, private upload, processing, and tightly scoped retrieval/download. Storage ownership derives from verified identity.

Signed private Storage upload/process/download path not implemented; browser still uploads multipart to FastAPI.

### 26. BLOCKED — Verify actual uploaded bytes/media/duration and object/session ownership server-side. Do not trust uploaded metadata, filenames, MIME headers, or client duration alone.

Actual media decoded server-side in exercised API tests; session ownership tested locally. Storage object ownership cannot pass without implemented Storage integration.

### 27. BLOCKED — Make processing idempotent and concurrency-safe across workers; enforce quotas/suspension/kill switch before expensive calls and atomically reserve usage.

Local SQLite atomic reservation/idempotency/control tests pass; distributed worker leases/crash recovery/Supabase transactions not implemented or verified.

### 28. BLOCKED — Validate strict model JSON before persistence, keep instructions separate from untrusted transcripts/reference text, and require transcript evidence.

Local strict schema, exact transcript evidence and failed-report persistence tests pass. Real provider output and restricted reference-text behavior not exercised.

### 29. FAIL — Delete raw audio after processing by default and no later than policy limits; implement reliable retry/crash cleanup and verify objects disappear. Explain external provider retention separately.

Local temporary files removed in finally and asserted absent on success/failure. Durable retry/crash cleanup and Supabase object removal not implemented.

### 30. BLOCKED — With real verified test accounts and real OpenAI responses: save profile -> create personalized scenario -> record -> upload -> transcribe -> validate/persist feedback -> retry in same session -> compare.

Real verified test accounts/private Storage/Supabase persistence unavailable. No live OpenAI coaching receipt claimed.

### 31. BLOCKED — Confirm browser history/progress uses persisted results and survives logout/login and API restart.

API restarted and healthy, but no authenticated browser logout/login persistence loop was exercised.

### 32. BLOCKED — Exercise provider errors/timeouts, invalid model output, duplicate/retried requests, concurrent quota exhaustion, suspension, and global kill switch. Failed processing must not persist a pretend report.

Existing local mocked-provider failure/invalid report/replay/quota/control tests pass; live provider timeouts and distributed quota exhaustion unverified.

### 33. BLOCKED — Verify every frontend action reaches the intended real endpoint with correct state/loading/error recovery.

Live public UI/API/proxy and invalid-token protected transport verified; all authenticated frontend actions require account access.

### 34. FAIL — Implement session/history/document/account deletion with dependency-safe cleanup of rows, objects, indexes, and auth identity. Specify retry behavior and retention exceptions; verify with readback and failed subsequent access.

Session/history deletion locally implemented/tested; document/object/account/Auth-identity deletion workflow missing.

### 35. PASS — Complete restricted PDF/DOCX/TXT/Markdown/CSV ingestion and owner-isolated retrieval per Day 4 only if safely supported. Enforce actual format, page/count/content limits and prompt-safety boundaries. Keep general uploads disabled without dependable scanning and document restriction honestly.

Conditional safe restriction: document ingestion intentionally unavailable; live POST /api/v1/documents returns 404. No scanner or private retrieval claimed. Restricted PDF/DOCX/TXT/MD/CSV ingestion remains undelivered.

### 36. FAIL — Add safe structured auth/security events with timestamp, operation, result/status and correlation ID; avoid secret headers, tokens, links, passwords and content. Define which events are browser, backend or Supabase-provider logs.

Existing minimal deletion/suspension audit rows do not provide required structured auth/security events and correlation IDs.

### 37. BLOCKED — Prove logs/errors/bundles/source maps are free of privileged secrets and private content. Provide practical troubleshooting instructions without requiring sensitive screenshots/HAR exports.

Scan of 63 source/docs/bundle files found zero configured privileged-value matches and zero frontend source maps. Environment/user data/dependencies/Git history excluded. External provider logs/private content were not audited.

### 38. BLOCKED — Run canonical unit, API, database-policy, Storage, browser end-to-end and secret-scanning checks from a clean install.

npm ci: 163 packages installed, zero npm audit vulnerabilities (one dependency deprecation warning); 18 tests/build pass. Backend uv sync --frozen plus 53 tests/Ruff pass in existing venv. Clean Python install, live DB policies/Storage/authenticated browser E2E unavailable.

### 39. BLOCKED — Two real users cannot access each other's profiles, sessions, attempts, transcripts, reports, audio, documents/chunks, usage or subscriptions—including guessed IDs and direct SDK requests.

Two designated real users and remote database/Storage integration required; local mocked-identity tests are not this release gate.

### 40. FAIL — Complete setup/API/schema/RLS/retention/threat-model docs, secure environment separation, rollback procedure, and explicit known limitations.

Existing setup/API/retention limitation docs preserved; complete deployed schema/RLS/threat model/rollback documentation awaits actual integration. This receipt explicitly inventories gaps.

### 41. BLOCKED — If deployment is authorized and hosting access exists: deploy to controlled staging with HTTPS, API routing/CORS and exact auth redirects; add privacy-safe Sentry/PostHog configuration per requirements; repeat real browser flow and isolation checks on deployed URLs.

No staging/public deployment or hosting authorization supplied; no deployment, Sentry or PostHog configuration performed.

### 42. PASS — If hosting/auth/access blocks any gate, mark BLOCKED with exact human action required. Do not call the app fully connected or release-complete while mandatory gates remain unverified.

Genuine blockers identified; app explicitly remains local SQLite alpha, not fully connected or release-complete. Required human action recorded below.

## Commands and observed results

Baseline backend: `cd backend && uv run --frozen pytest -q && uv run --frozen ruff check . && uv run --frozen ruff format --check .` → 41 passed; lint passed; 20 formatted files.
Baseline frontend: `cd frontend && npm test -- --run && npm run build` → 18 passed across six files; build succeeded.
Browser capture: `SPEECHCLEAR_TEST_CHROME="/Users/me/.agent-browser/browsers/chrome-154.0.8037.92/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" python3 frontend/scripts/capture_browser_audio.py` → actual short/boundary/valid WebM files (31,089 / 482,659 / 501,995 bytes). CLI run via npx; managed Chrome explicitly selected.
RED: `cd backend && uv run --frozen pytest -q tests/test_browser_media.py` → two browser-media failures and one short-media pass before fix.
Final backend: `cd backend && uv sync --frozen && uv run --frozen ruff format media.py tests/test_browser_media.py && uv run --frozen pytest -q && uv run --frozen ruff check . && uv run --frozen ruff format --check .` → 37 packages checked, 53 tests passed, lint passed, 21 files formatted.
Final frontend: `cd frontend && npm ci && npm test -- --run && npm run build` → 163 packages installed; zero npm audit vulnerabilities; 18 tests passed; TypeScript/Vite build passed. One whatwg-encoding deprecation warning.
Live read-only Supabase HTTP probes → Auth settings 200, Email enabled, confirmations required; JWKS 200/ES256. No privileged values printed.
Live local HTTP → frontend, health and proxy 200; anonymous profile/sessions 401; document upload route 404. Actual Chromium API wrapper with deliberately invalid token reached backend and returned `Invalid or expired access token`, not Illegal invocation.
Secret check → 63 source/docs/bundle files, zero configured privileged-value matches, zero frontend source maps. Not an external log/private-content/Git-history audit.

## Changed files and remote state

- `backend/media.py`: bounded decoded-duration validation and explicit boundary precision.
- `backend/tests/test_browser_media.py`: real-browser fixture regression, decoded boundary/timeout/API cleanup tests.
- `backend/tests/fixtures/browser-audio.json`, `chromium-short.webm`, `chromium-boundary.webm`, `chromium-valid.webm`: actual controlled browser recordings and safe metadata.
- `frontend/scripts/capture_browser_audio.py`: repeatable capture using actual app controller/Chromium, no user microphone or account content.
- `README.md`, `doc.md` and this receipt: decoder prerequisites, execution evidence and blockers.
- No migrations applied; no remote writes, deployments, commits, credentials edits or real-user data deletion. Frontend production bundle rebuilt locally.

## Runtime and resumption

Local frontend: `http://localhost:5173`; backend: `http://127.0.0.1:8000`; health: `/api/v1/health`. Servers were started for checks, backend restarted after fix and read back healthy. They are conversation-owned processes, not a deployment or guaranteed persistent service.

Resume by rechecking git status and credential presence, verifying target authority, then implementing/exercising additive migrations and Postgres/private Storage adapters. Preserve the existing SQLite session/usage record with an explicit read-only export, owner mapping, protected backup, verified import, and operator-controlled cutover/backout; never silently fallback or dual-write. Keep document uploads unavailable until ingestion/scanning boundaries are dependable.
