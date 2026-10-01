# FastAPI Supabase integration

## Runtime boundary

`create_app()` constructs `supabase_store.Store(Settings)` and `PrivateStorage(Settings)`. Modern backend secret keys and legacy service-role keys remain backend-only; public configuration never returns either. No credential inspection or remote write is needed to start public routes. Missing/invalid backend configuration creates an unavailable adapter rather than SQLite.

Private API routes require verified authentication and a protected, target-bound cutover receipt before invoking persistence. The receipt is rechecked on each private request. It must be an operator-owned regular file, mode 0600, without symlinks in the file/parent chain; it must contain the exact project URL/reference, lowercase SHA-256 hashes, timezone-aware nonfuture timestamp, and literal-true verification/readiness flags. Explicit `store=` injection is a local test seam, not a runtime environment fallback.

Supabase session detail uses the coherent `session_detail` RPC snapshot. Legacy multipart processing is available only for an explicitly injected SQLite adapter. Supabase processing accepts a small JSON upload reference after the authorize → authenticated relay → process flow; raw audio PUT bodies are capped at 12 MiB, while JSON processing bodies are capped at 32 KiB. Multipart legacy requests retain bounded overhead and streaming enforcement.

`/api/v1/health` reports `storage: supabase`, authentication configuration and separate persistence/audio readiness flags. These flags do not perform remote probes or certify live RLS/Storage access.

## Lifecycle and operations

Startup and the 60-second lifespan task run local stale-audio cleanup and, only once persistence is authorized, durable remote cleanup. Local removal is restricted to stale `speechclear-*` regular files owned by the process in a same-owner, mode-0700 nonsymlinked directory. Foreign files and symlinks are preserved. Remote cleanup exceptions emit a constant safe retry warning without provider exception details. Shutdown cancels the task and closes persistence and Storage HTTP clients.

`admin.py suspend|unsuspend USER_ID` uses Supabase by default and requires the same protected readiness receipt before any default control write. It reads back exactly the selected owner's `controls` row through privileged REST and verifies its boolean value before reporting success. No nonexistent `control_read` RPC is assumed. Explicit injected test adapters remain supported; failures do not print private values.

See `PERSISTENCE_CUTOVER.md` for backup, import, all-owner verification, partial-import reconciliation and non-destructive backout.

## Local validation

The integration tests cover receipt fail-closed behavior and permission rechecks, coherent session dispatch, JSON versus multipart routing, raw/JSON body limits, startup/retry/shutdown cleanup, public secret exclusion, admin exact readback, and a real WAV authorize/relay/process round trip through `create_app` with explicitly injected provider/persistence boundaries. Import tests use disposable PostgreSQL and a local Auth/REST HTTP bridge, plus negative protected-export/owner/data checks. These are local proofs, not deployed Supabase account/RLS/Storage acceptance.

Latest local run: `backend/.venv/bin/python -m pytest tests -q` returned **235 passed**. Ruff check passed for all integration-owned Python files and Ruff formatted them. Whole-backend Ruff was also attempted; at that checkpoint it reported 19 errors in concurrently edited, separately owned `private_storage.py`, `storage_routes.py`, `tests/test_cleanup_races.py`, and `tests/test_postgres_schema.py`, and six separately owned files needed formatting. Those files were not modified by the integration worker. The parent must rerun whole-backend lint/format after the Storage/SQL worker finishes. `git diff --check` passed.
