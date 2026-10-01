# Backend verification — local alpha, steps 1–3

## Result and scope

Reviewed `IMPLEMENTATION_CONTRACT.md`, the Day 1–3 requirements, every backend runtime module, and the existing tests. The implementation contract is the narrowed local-alpha boundary: verified Supabase identity with owner-scoped **transitional SQLite**, not a completed Supabase/Postgres/storage release.

Final verification: **41 tests passed**, Ruff lint passed, and all 20 Python files passed Ruff format checks. Tests exercise the FastAPI ASGI application; no listening server was started. No commits were created. No `.env` contents were printed or changed, and frontend/root README work was left to its owner.

## Security fixes made with RED → GREEN regressions

1. **Public config could disclose a privileged key placed in the public-key setting.** Added tests first demonstrating that `sb_secret_...`, a synthetic service-role JWT, and an unrecognized key were returned publicly. Config now fails closed unless the setting is a recognized `sb_publishable_...` key or legacy JWT classified as `role=anon`. Legacy decoding here is classification only, never authentication; real bearer identity still requires a verified asymmetric signature. Test fixtures use explicitly synthetic publishable keys.
2. **Suspension/kill-switch checks could become stale across processing stages.** Added tests first showing that a suspended owner could reserve quota directly and that a control change during email verification/transcription still allowed the next AI call. Suspension is now rechecked inside the same `BEGIN IMMEDIATE` transaction as quota reservation. AI availability is rechecked after email verification, after media probing, and before report evaluation. Mid-pipeline rejection marks the idempotency operation failed and removes its temporary audio.
3. Removed an unused test import and formatted the previously unfinished boundary tests.

Additional coverage verifies both RS256 and ES256 against locally generated signing keys, rejection of invalid signatures/missing expiry/malformed tokens, monthly quota rejection before AI, free completed-request replay even at quota, and sanitized provider failure with audio cleanup. These cover existing behavior rather than introducing runtime fallback data.

## Exact verification commands and observed results

Run from `/Users/me/Desktop/professional-communication-coach/backend`:

```sh
uv run pytest -q
# Initial baseline: 27 passed in 2.73s.

ruff check . --exclude .venv
ruff format --check . --exclude .venv
# Initial lint: unused test_flow.client_for import in test_boundaries.py.
# Initial format check: test_boundaries.py needed formatting.

uv run pytest -q tests/test_config_security.py
# RED: 3 failed, 2 passed; unsafe keys were exposed in config.
uv run pytest -q
# GREEN after config fix: 32 passed in 2.91s.

uv run pytest -q tests/test_control_races.py
# RED: 5 failed; missing atomic suspension checks and stale control gates.
uv run pytest -q tests/test_control_races.py
# GREEN: 5 passed in 0.77s.
uv run pytest -q
# GREEN full suite at this point: 37 passed in 2.90s.

ruff format . --exclude .venv
# 5 files reformatted, 15 unchanged.
ruff check . --exclude .venv
# All checks passed!
ruff format --check . --exclude .venv
# 20 files already formatted.
uv run pytest -q
# Final: 41 passed in 3.55s.
```

`command -v ffprobe` resolved to `/opt/homebrew/bin/ffprobe`. Real local ffprobe and ffmpeg run in the media tests, including a non-seekable browser-style WebM fixture. Synthetic audio/report data and substituted auth/provider behavior are **test-only**, not production behavior. Signed-token tests run the real verifier with test signing-key lookup substituted; flow tests inject test identities/provider responses. Neither is proof of live Supabase/OpenAI connectivity.

## Verified implementation boundaries

- Public config has only the contracted public fields; missing/unsafe auth configuration fails closed. Protected routes require a bearer token. JWT verification allows only RS256/ES256 and checks signature, issuer, audience, expiry, and nonempty subject. Legacy HS256 access tokens are deliberately unsupported.
- Email verification for AI requests is fetched from Supabase `/auth/v1/user` and tied to the verified subject; user-editable metadata is not trusted. Network failure fails closed. Missing API credentials and the AI kill switch block provider work.
- Profile, sessions, attempts, history and usage queries bind the owner derived from authentication. Cross-owner reads, uploads, deletes and history deletion are tested.
- Runtime calls real OpenAI Responses structured generation/evaluation and audio transcription. Profile/transcript content is serialized as untrusted user data separately from policy. Requests disable response storage (`store=False`); report schemas forbid extras and validate strict integer scores/ranges. Evidence quotes must be exact transcript substrings. Invalid output is never saved; errors do not return provider details.
- Audio has a 12 MiB file limit plus bounded total request bodies (including chunked uploads), accepted MIME/extension checks, actual ffprobe container/audio-stream validation, finite declared/measured 30–180 second duration, and a maximum three-second discrepancy. ffprobe has a 15-second timeout and a restricted protocol list. Named processing files are deleted in `finally`; successful multipart parsing is context-managed.
- Quota reservations and processing-key claims are serialized with SQLite `BEGIN IMMEDIATE`; concurrent reservations cannot exceed limits. Scenario generation costs one usage unit and an attempt pipeline costs one usage unit. Failed provider operations retain their charged unit to avoid free repeated expensive failures.
- Attempts require canonical UUID idempotency keys. A completed key returns the saved attempt without another AI call or charge; a processing/failed key returns 409. A failed attempt requires a new key. Deleting a session cascades its attempts and operation keys; deleting during an attempt prevents saving the late result. Usage/audit records survive history deletion so deleting history cannot reset quota.
- IP/user rate limits are enforced; suspension and deletion create audit records. JSON validation/provider errors expose safe string `detail` values.

## Local start and controls

Prerequisites: Python 3.11+, `uv`, ffprobe on PATH (ffmpeg is needed for the WebM regression test). Configure the existing root `.env` with Supabase URL, a **publishable or legacy anon key**, and OpenAI API key; never use a service-role/secret key as the public setting. The backend reads `.env` server-side.

```sh
cd /Users/me/Desktop/professional-communication-coach/backend
uv sync
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

The start command is documented, not executed in this lane. Use the Vite `/api` proxy for browser requests; there is no broad permissive CORS setting.

Operator-only suspension commands (use the real verified Supabase subject):

```sh
uv run python admin.py suspend <verified-subject>
uv run python admin.py unsuspend <verified-subject>
```

The CLI reads back the exact control row before reporting success, and both commands are exercised against a disposable test database. `AI_ENABLED=false` disables AI at startup. Environment settings are snapshots: changing `.env` alone does not update an already-running process; restart it. To stop further work immediately, stop the backend process. In-memory setting changes are checked at stage boundaries but cannot cancel an already dispatched provider call.

## Remaining limitations / not claimed

- **No live Supabase signup/login/JWKS/email-status or real OpenAI response/transcription was exercised.** Supabase setup and credentials are still an integration prerequisite. No auth bypass, mock report, or fallback transcript exists in runtime.
- No Supabase migrations, Postgres RLS, private buckets, signed upload URLs, account deletion, documents, subscription plans or deployment work is included. Direct browser upload and SQLite are explicitly transitional. This is not the full Day 1–3 production acceptance receipt.
- Rate limits are per process/in memory; run one local worker. Durable quotas/suspension/idempotency share SQLite, but distributed deployment needs shared infrastructure. The kill-switch env value requires process restart; there is no remote admin UI/control plane.
- Processing is synchronous request work with bounded provider timeouts, not a durable queue. A crash/cancellation can leave a processing key and temp file; there is no automatic crash-recovery/24-hour janitor. Normal success/error paths clean up audio. A crashed operation needs a fresh key; do not retry it automatically and risk duplicate provider cost.
- History deletion is logical database deletion, not forensic disk erasure. Profiles, usage and minimal audit rows remain; complete account deletion is pending. Keep the SQLite directory private to the local operator and do not expose this alpha directly to the Internet.
- Schema/evidence validation and policy instructions constrain coaching, but do not prove every model response is free of diagnosis or other unsafe interpretation. Live output evaluation, external-provider retention review, and production security/observability hardening remain necessary before release.
