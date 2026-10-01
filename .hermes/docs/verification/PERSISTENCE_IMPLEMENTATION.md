# Persistence adapter and protected migration handoff

## Scope and evidence boundary

Owned files: `backend/supabase_store.py`, `backend/tests/test_supabase_store.py`, `backend/migration.py`, `backend/tests/test_migration.py`, this document. No app/admin/settings/frontend/schema changes, environment edits, remote writes, commits, pushes, real-account tests, or reads of runtime secrets/private SQLite contents were performed by this worker. All local SQLite fixtures and PostgreSQL records were synthetic. Real-account/remote integration gates remain required and are not waived.

## Backend adapter contract

`supabase_store.Store(settings, transport=None)` accepts an optional synchronous httpx transport. Required configuration:

- `supabase_url` must equal `https://qpheitaamyzcekzvbcox.supabase.co` exactly (no alternate host, userinfo, query, path, explicit port, or insecure scheme).
- `supabase_secret_key` is preferred; `supabase_service_role_key` is the legacy fallback only when the preferred setting is empty. Modern `sb_secret_` credentials use **apikey only**, never bearer Authorization. A classified legacy JWT with role `service_role` uses apikey plus bearer Authorization. Classification is not signature/authentication verification; Supabase must validate credentials. Missing, public/anon, placeholder, or unclassified credentials raise a safe `ValueError` at construction. No SQLite fallback exists.
- Requests do not follow redirects or inherit proxy/netrc environment configuration; timeout is 20 seconds.

Every operation is one POST to `/rest/v1/rpc/speechclear_api` with `{p_action, p_owner, p_payload}`. `p_owner`, session/attempt/key/upload identifiers must be canonical UUID strings. Owner must originate from verified backend authentication; the adapter does not authenticate incoming users. RPC validates owner existence/authorization and commits atomic mutations in SQL.

| Method / action | Payload | Successful JSON result |
|---|---|---|
| `profile(owner, data=None)` | `{}` or `{data}` | Profile object (strict existing Profile model; missing default fields expand) |
| `save_session(owner, data)` | `{data}` | Same complete session object |
| `session(owner, id)` | `{id}` | Session object matching requested ID |
| `session_detail(owner, id)` | `{id}` | Session object with `attempts` from one coherent SQL snapshot |
| `sessions(owner)` | `{}` | Session objects with required `attempt_count`, `latest_score` |
| `attempts(owner, id)` | `{id}` | Attempt array, all matching requested session |
| `require_active(owner)` | `{}` | JSON null |
| `reserve(owner, daily, monthly)` | `{daily, monthly}` | JSON null |
| `usage(owner, daily, monthly)` | `{daily, monthly}` | `daily_used, daily_limit, monthly_used, monthly_limit` |
| `begin_attempt(owner, session, key, daily, monthly, upload_id=None)` | `{session,key,daily,monthly}` with optional `upload_id` | JSON null for new reservation, full attempt for committed replay |
| `finish_attempt(owner, key, attempt)` | `{key,attempt}` | Same complete attempt object |
| `fail_attempt(owner, key)` | `{key}` | JSON null |
| `delete(owner, id=None)` | `{}` or `{id}` | JSON null |
| `suspend(owner, value)` | `{value}` | JSON null |

`rpc(action, owner, payload)` exposes the same service-only transport to trusted internal storage helpers and returns arbitrary JSON. It does not implement an action allowlist locally; SQL is the authoritative allowlist. Do not expose it as a client-controlled API dispatcher.

Session and attempt projections forbid extra fields and validate required types, canonical IDs, timezone-bearing timestamps, bounded text, finite decoded durations (29.85–180.15 seconds), strict existing Report schema and transcript quote evidence. Summaries/detail/list projections validate parent relationships, duplicate identifiers and summary coherence. Fresh writes validate before issuing the request; returned session/attempt write receipts must match the submitted object. Usage allows server-enforced limits **lower** than caller limits (global controls), rejects higher limits or invalid integer/count projections.

Safe HTTP mappings: 403 `Account suspended`, 404 `Session not found`, 409 `Request conflict`, 429 `AI quota reached`, 422 `Invalid storage request`; other statuses/transport failures become 503 `Storage temporarily unavailable`. Malformed JSON or projections become 503 `Invalid storage response`. No response message/body or underlying exception is echoed. The 403 message is deliberately stable, not an inference of whether SQL rejected suspension, kill switch, or missing owner.

Parent integration: select this Store explicitly, never automatically reopen SQLite on configuration/network errors; use `session_detail` in the detail route rather than separate parent/child reads. The adapter is usable but does **not** authorize active cutover of existing data.

## Protected migration preparation

Programmatic API: `migration.backup_export(source, new_directory, owner_mapping=None)`.

CLI from `backend/`:

```sh
.venv/bin/python migration.py backup-export SOURCE_SQLITE NEW_PRIVATE_DIRECTORY
# For legacy/noncanonical owners, use a private JSON file, not inline owner values:
.venv/bin/python migration.py backup-export SOURCE_SQLITE NEW_PRIVATE_DIRECTORY --owner-map PRIVATE_MAPPING_JSON
```

This creates a **new**, mode-0700 directory and exclusively-created mode-0600 `backup.sqlite3`, `export.json`, and `manifest.json`. Existing directories/files are not overwritten; symlink source/output ancestors are rejected. Owner-map files must not be group/world-readable. The source is opened with SQLite URI `mode=ro` and `query_only=ON`; SQLite's backup API preserves a consistent snapshot including committed WAL records. Both connections explicitly close before hashing/export receipts. Backup is integrity-checked; all seven tables and columns must match the current legacy schema. Unknown tables/columns fail closed, retaining the protected backup instead of silently omitting rows.

Export retains every original row/column, JSON TEXT bytes as original string values, IDs, timestamps, usage/control/audit rows, operations and row order. Owner mapping is separate; original ownership is not rewritten. Every observed owner must map exactly once to a distinct canonical UUID. Noncanonical legacy owners require an explicit mapping. Parent must later verify **each target UUID actually exists in Supabase Auth**; UUID format alone is not existence proof.

Pre-export checks include actual SQLite foreign-key integrity, attempt/operation parent ownership, completed operation attempt ownership/session, allowed operation states, suspended flags, and JSON-vs-relational IDs/owners. Invalid source data blocks export; no row is silently dropped, repaired, re-owned or coerced. Metadata exposes only counts, owner count, integrity result and backup/export/schema SHA-256 hashes; no owner values or user content are logged/printed.

`compare_receipt(manifest, receipt)` compares exact export hash, all source counts, project reference and explicit boolean `owner_mapping_verified`. It is a **metadata comparison primitive**, not authenticated proof or cutover authorization. Parent must retrieve authenticated remote receipts/readback independently, verify normalized dependent rows (transcripts/reports), account mappings, source freeze and post-import data. Local fixture receipts are not live import receipts.

`import_export(export_path, store)` currently **always fails closed** with `Remote import is not implemented; cutover blocked`, without invoking Store or making any remote write. The schema worker's import action was still evolving during this task. No partial row-at-a-time import, dual write, fake receipt, or active-cutover flag is supplied. Manifest always records `cutover_ready: false`.

Operational gates: stop/freeze source writers before a real final snapshot; store protected backup/export outside Git and outside public directories; retain failed protected backups for diagnosis without printing contents. Implement/verify a dedicated atomic import RPC supporting every source table, raw data preservation and ownership mappings; obtain actual import receipts and exact readback before enabling Supabase runtime for existing owners. Never auto-switch back to SQLite. Before cutover, backout is simply retaining the unchanged original and leaving the current runtime active; after remote writes, restoring an old SQLite snapshot would lose newer data and requires a separately authorized reconciliation/backout plan.

## Actual TDD and verification results

Commands ran from `/Users/me/Desktop/professional-communication-coach/backend` using the existing `.venv`:

1. First profile tracer: `pytest tests/test_supabase_store.py -q` via `.venv/bin/python -m` → **RED 1 failed**, missing adapter module; minimal transport implementation → **GREEN 1 passed**.
2. Configuration/credential/owner/error/privacy slice → **RED 32 failed, 1 passed** (missing checks/error sanitization); implementation → **GREEN 33 passed**. Synthetic legacy HMAC fixture was lengthened to eliminate the insecure-key test warning.
3. Store CRUD/quota/idempotency/projection slice → **RED 26 failed, 34 passed** (missing methods); implementation → **GREEN 60 passed**.
4. First protected migration tracer → **RED 1 failed**, missing module; backup/export implementation → **GREEN 1 passed**.
5. Migration relationship/schema/owner/import/receipt checks → **RED 18 failed, 3 passed**; implementation → combined **GREEN 81 passed**.
6. SQL-contract refinement (lower enforced quota, optional upload binding) and safe CLI → combined **RED 4 failed, 81 passed**; implementation → **GREEN 85 passed**.
7. Added execution verification using the schema worker's `scripts.verify_postgres.disposable_database`: real local Unix-socket-only PostgreSQL migrations, service RPC SQL and synthetic persistence/replay/detail/quota/control/deletion receipts passed through the adapter using an httpx SQL transport bridge → **86 passed**. This is actual transactional PostgreSQL evidence, **not** live PostgREST, Supabase Auth, remote RLS or remote credentials proof.
8. Explicit SQLite-connection-close regression → **RED 1 failed**; `contextlib.closing` fix → final owned suite **87 passed in 1.56s**.

Final commands:

```sh
uvx ruff format supabase_store.py migration.py tests/test_supabase_store.py tests/test_migration.py
uvx ruff check supabase_store.py migration.py tests/test_supabase_store.py tests/test_migration.py
.venv/bin/python -m pytest tests/test_supabase_store.py tests/test_migration.py -q --tb=short
uvx ruff format --check supabase_store.py migration.py tests/test_supabase_store.py tests/test_migration.py
git diff --check -- supabase_store.py migration.py tests/test_supabase_store.py tests/test_migration.py ../PERSISTENCE_IMPLEMENTATION.md
```

Results: **87 passed**, Ruff checks passed, all four Python files formatted, scoped diff whitespace check passed. All owned tests use synthetic credentials/content.

Whole-suite checkpoint (concurrent workers were modifying unowned integration/schema files): `.venv/bin/python -m pytest -q --tb=short` → **161 passed, 3 failed in 20.91s**. Failures were two unintegrated `test_persistence_cutover.py` cases (app still reported/created SQLite) and `test_postgres_schema.py::test_import_legacy_transaction_and_receipt` (SQL action `import_legacy` not yet supported). Earlier whole-suite checkpoint: **155 passed, 3 failed**, before concurrent upload/import tests/schema completed. These are honest integration blockers, not waived gates; parent must rerun after those writers finish. No unowned file was edited to mask them.
