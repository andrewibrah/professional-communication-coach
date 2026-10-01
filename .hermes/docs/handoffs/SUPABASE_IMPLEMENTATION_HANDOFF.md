# SpeechClear — Supabase implementation handoff

Target: `qpheitaamyzcekzvbcox`, explicitly authorized development root.

## Package status

Implementation and local cutover are delivered. **Mandatory live two-account/browser acceptance remains BLOCKED**, honoring Andrew's explicit instruction to stop before live account tests. The app must not be called release-complete.

| Goal / gate | Status | Actual evidence |
|---|---|---|
| Required Postgres tables, ownership FKs/checks/indexes/grants/RLS | PASS implementation | Three migrations applied via authenticated MCP; exact catalog/grant/function/bucket readback. 13 public application/support tables and private import receipts. |
| Atomic quota/idempotency/completion and strict report validation | PASS local | Real disposable PostgreSQL roles, competing connections, observed lock waiters, failure rollback, evidence-substring checks, immutable attempts. Remote account concurrency remains unverified. |
| Supabase runtime persistence, no active SQLite fallback | PASS | Default FastAPI Store uses service-only PostgREST RPC; API/proxy health reports Supabase and valid protected receipt. |
| Existing user-data preservation/import | PASS | Protected read-only backup/export; existing Auth-owner confirmation verified; atomic import and exact idempotent replay/readback. One original session and one usage record preserved; original SQLite rows unchanged. |
| Private buckets and short-lived upload authorization | PASS implementation | Private temporary-audio/documents buckets read back with 12 MiB/MIME limits. Five-minute identity/session-bound API relay, not built-in two-hour signed upload. |
| Authoritative server media validation | PASS local + live transport | Original Chromium WebM fix retained. Actual 482,659-byte boundary fixture survived live Storage roundtrip and decoded to 29.94s. |
| Reliable retry/crash cleanup | PASS local; BLOCKED live-account gate | Generation-checked cleanup claims, scheduled startup/60s sweeper, local crash-file recovery, delayed-writer compensation and durable tombstone reconciliation tested deterministically. Remote authenticated/crash lifecycle not exercised. |
| Anonymous database CRUD denial | PASS live | All 13 tables returned 401 for SELECT/INSERT/UPDATE/DELETE; application RPC returned 401. Mutation filters targeted nonexistent test IDs; no successful anonymous writes. |
| Anonymous Storage denial | PASS scoped | Empty private listing; exact controlled private object download returned 400. Not a two-user access proof. |
| Live Storage bytes/download/deletion | PASS service transport only | Non-private browser-encoded fixture uploaded, downloaded with matching SHA-256, decoded and deleted; exact absence read back. No Auth account created or impersonated. |
| Real User A/User B database CRUD/guessed-ID isolation | BLOCKED | Designated verified account participation paused by Andrew. Local role bootstrap is not this gate. |
| Real User A/User B Storage ownership/access | BLOCKED | Same explicit pause; service transport is not user-token authorization evidence. |
| Authenticated browser profile/scenario/upload/coaching/retry/history/delete | BLOCKED | No user login, provider coaching or two-account browser testing performed. Real signed-out Chromium public-config check passed. |
| Local secret scan | PASS scoped | 83 source/doc/migration/bundle files, zero configured privileged-value matches, no frontend source maps. Env/data/dependencies/external logs excluded. |
| Account deletion/document ingestion/public release | BLOCKED / unavailable | Not implemented or authorized; controls disabled. No deployment/commit/push. |

## Applied migrations

| Local migration | Remote version/name |
|---|---|
| `supabase/migrations/202609300001_speechclear.sql` | `20261001045305 speechclear_application_schema` |
| `supabase/migrations/202609300002_atomic_api.sql` | `20261001045338 speechclear_atomic_api` |
| `supabase/migrations/202609300003_legacy_import.sql` | `20261001045342 speechclear_protected_legacy_import` |

Schema-only MCP receipts: [remote-schema-evidence.json](../verification/remote-schema-evidence.json). Each write was followed by affected catalog/function/ACL/bucket readback and migration-list verification. No Supabase CLI, reset or destructive rollback was used.

## Changed implementation files

- `.gitignore` — excludes backend runtime data, exports, backups and receipts.
- `backend/app.py`, `admin.py`, `guards.py` — Supabase-default runtime, protected cutover readiness, verified admin readback, body limits, scheduled cleanup and safe failure warnings.
- `backend/supabase_store.py` — backend-only modern/legacy credential support, service RPC, owner/resource validation and coherent reads.
- `backend/migration.py` — protected backup/export, all-owner prevalidation, atomic import/replay, exact source-scoped readback and exclusive receipt creation.
- `backend/private_storage.py`, `storage_routes.py` — private bounded transport, five-minute authorization/relay/process, actual decoding, cleanup compensation and generation-aware sweeps.
- `supabase/migrations/` — schema, atomic processing/upload API, protected import.
- `backend/scripts/verify_postgres.py` — private disposable Unix-socket-only real PostgreSQL verifier.
- Backend tests: `test_api.py`, `test_flow.py`, `test_admin.py`, `test_persistence_cutover.py`, `test_supabase_store.py`, `test_migration.py`, `test_import_cutover.py`, `test_postgres_schema.py`, `test_storage_routes.py`, `test_private_storage.py`, `test_cleanup_races.py`, `test_integration_contracts.py`, `test_app_storage_integration.py`.
- Frontend: `src/api.ts`, `api.test.ts`, `SessionView.tsx`, `practice-flow.test.tsx`, `App.tsx`, `App.test.tsx` — relay handshake, guarded retries/cancellation, terminal failure UI, accurate storage/retention copy.
- Documentation organized in `.hermes/docs/`; current setup/contracts/overview, focused evidence and canonical log updated. Existing browser recorder and `backend/media.py` duration fix were preserved, not replaced.

## Commands and receipts

```sh
cd backend
uv run --frozen ruff format .
uv run --frozen ruff check .
uv run --frozen pytest -q
uv run --frozen ruff format --check .
# 235 passed; lint passed; 36 files already formatted on final check.

cd frontend
npm test
npm run build
# 58 tests across 6 files passed; TypeScript/Vite passed.
```

Protected import executed from backend:

```sh
uv run --frozen python migration.py import-export \
  data/migration-backups/20261001T043016Z/export.json \
  --receipt data/supabase-cutover.json
```

Result: `Import and cutover receipt verified.` First invocation failed closed on data-directory mode 0755; mode corrected to 0700 before retry. Snapshot files and receipt are 0600, private directory 0700. No private rows, owners or keys printed.

Protected backup: `/Users/me/Desktop/professional-communication-coach/backend/data/migration-backups/20261001T043016Z`.

Readbacks: original/remote source fields and timestamps match; coherent session has zero attempts; MCP counts session 1/usage 1/import receipt 1. SQLite backup bytes need not equal original file bytes; row preservation and the original pre/post-source comparison are the relevant evidence.

## Running locally

- Frontend: `http://localhost:5173`
- API: `http://127.0.0.1:8000`
- API and proxy health: HTTP 200, `storage=supabase`, `auth_configured=true`, `persistence_ready=true`, `audio_storage_ready=true`.
- Isolated Chromium: public config 200, authentication configured, no visible setup warning. The earlier screenshot's warning came from the deliberately stopped API during migration, not loss of the user's account. Reload the existing page to obtain the restored config.

These readiness flags do not imply the blocked real-user gates passed.

## Remaining limitations and risks

- Cleanup is eventual under a running successful worker and available SQL/Storage. A 24-hour metadata deadline is not an unconditional physical-retention guarantee during outages. Tombstones must remain available for late-writer reconciliation.
- Backend secret is privileged; SQL/RLS cannot protect against a stolen service credential. Keep it backend-only and rotate if exposed.
- Per-process IP/user rate limiting is not a distributed limiter; quotas/idempotency/control writes are database-atomic.
- Frontend upload receipts are tab-memory-only; reload loses processing retry metadata. Generic processing 409 cannot distinguish running versus terminal failure; UI advises checking history.
- Fixed alpha caps are 20/day and 200/month; subscription records do not implement billing/paid-plan enforcement.
- Account deletion and safe document ingestion are disabled; no full Day-4 release claim.
- Pre-existing `rls_auto_enable` anonymous/authenticated EXECUTE warnings and disabled leaked-password protection remain. Remediation references: https://supabase.com/docs/guides/database/database-linter?lint=0028_anon_security_definer_function_executable and https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection. They were not silently altered.
- New default runtime was exercised with live runtime credential/import and public requests, but not signed-in real-user API/provider completion. No clean-checkout reproduction claim: application files remain uncommitted/untracked at Andrew's direction.

## Backout

See [protected cutover procedure](../verification/PERSISTENCE_CUTOVER.md). Stop writers, preserve any new Supabase data/objects privately, archive/remove the readiness receipt to fail closed, and reconcile before an explicitly approved rollback. Never delete remote data or automatically reactivate SQLite.

## Required next authorized test steps

When Andrew authorizes live account testing:

1. Designate two verified test accounts through secure UI/vault or private configuration; no passwords/tokens in chat, logs or command arguments. Do not use private production speech or documents.
2. User A: save profile, create a scenario, record 30–180 seconds, relay/upload/process, validate/persist report, retry in the same session, verify history across logout/login and API restart, then delete only designated test data and read back rows/objects absent.
3. User B: perform direct Supabase CRUD and API guessed-ID requests across A's profile/session/attempt/transcript/report/usage/subscription/document/object metadata; assert forbidden/empty results and no state change. Test direct private Storage list/download/upload/delete for both owners.
4. Observe signed-in token refresh/verification/sign-out races, concurrent quotas/idempotency, provider/strict-output failure, delete-during-processing, and cleanup after worker interruption with exact object absence readback.

Next action now: reload `http://localhost:5173`. When ready for acceptance, explicitly authorize the two-account test pass; implementation is not release-complete until it passes.
