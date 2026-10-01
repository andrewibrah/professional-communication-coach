# PostgreSQL schema and atomic API implementation

## Delivery and scope

Authored locally; **no remote writes, migration applications, fake remote accounts, deployments, commits, `.env` edits, or private-data reads**. Parent applies the migrations through authorized Supabase MCP, in filename order, then verifies the remote catalog and grants. Do not modify the existing `rls_auto_enable` event trigger/function; these migrations enable their own tables explicitly. Its existing security warning remains a separate review item.

Owned files:
- `supabase/migrations/202609300001_speechclear.sql`
- `supabase/migrations/202609300002_atomic_api.sql`
- `supabase/migrations/202609300003_legacy_import.sql`
- `backend/tests/test_postgres_schema.py`
- `backend/scripts/verify_postgres.py`
- `SCHEMA_IMPLEMENTATION.md`

## Schema / access boundary

Public tables: `profiles`, `practice_sessions`, `attempts`, `transcripts`, `coaching_reports`, `usage_records`, `subscriptions`, `audit_events`, `documents`, `object_metadata`, `controls`, `operations`, `global_controls`. Private import receipts are in `speechclear_private.import_receipts`.

Every public table has RLS. Authenticated users get owner-only SELECT for user-owned tables; only `profiles` permits owner INSERT/UPDATE/DELETE. Anonymous application-table access is denied by grants. Generated sessions/attempts/transcripts/reports, quota records, controls, subscriptions, audit, operations, documents and metadata have no authenticated write grants. `global_controls` has no authenticated SELECT or write grant. Service-role credentials remain fully trusted and backend-only.

Ownership is `user_id` with auth-user foreign keys. Child session/attempt/upload relationships use composite ownership FKs, including operation `(attempt_id,session_id,user_id)` binding. Transcripts/reports must equal their validated parent attempt projection via triggers. Owner/history/cleanup indexes cover the principal retrieval paths. Sessions and attempts are checked against strict JSON validators in addition to RPC validation. Profile fields match current Pydantic lengths/defaults. Documents exist but remain disabled; no ingestion/scanning/retrieval feature is claimed.

Buckets `temporary-audio` and `documents` are private, capped at 12 MiB, and MIME-restricted. Creation uses `ON CONFLICT DO NOTHING`; existing privacy, size, or MIME mismatches abort rather than overwrite configuration. No authenticated/anonymous Storage policy is created: even the owner cannot read/list/write the underlying objects directly. The FastAPI relay, not a built-in two-hour signed upload URL, is the intended upload boundary.

## Single public RPC

`public.speechclear_api(p_action text, p_owner uuid, p_payload jsonb DEFAULT '{}') RETURNS jsonb` is SECURITY DEFINER with pinned search path. EXECUTE is explicitly revoked from PUBLIC/anon/authenticated and granted only to `service_role`. Private import helpers are not directly executable by the service role. Identity must be derived by FastAPI from a verified token; the RPC is not intended for user-token calls.

Top-level payloads reject unknown/missing keys; resource UUID strings must be lowercase canonical UUIDs, never repaired by PostgreSQL casts. Optional `delete.id=null` means all history. Except janitor actions, the owner must exist in `auth.users`.

| Action | Payload | Result |
|---|---|---|
| require_active | `{}` | null, or PT403 |
| usage | `{daily, monthly}` | `{daily_used,daily_limit,monthly_used,monthly_limit}` |
| reserve | `{daily, monthly}` | null, atomic ledger reservation |
| profile | `{data?}` | full current profile with defaults |
| save_session | `{data}` | unchanged validated session JSON |
| session | `{id}` | session JSON or PT404 |
| session_detail | `{id}` | session JSON plus ordered `attempts` in one SQL snapshot |
| sessions | `{}` | newest-first session list with `attempt_count`, `latest_score` |
| attempts | `{id}` | oldest-first attempt list; missing session PT404 |
| begin_attempt | `{session,key,daily,monthly,upload_id?}` | null for new claim; saved attempt JSON for completed retry |
| finish_attempt | `{key,attempt}` | unchanged validated attempt JSON |
| fail_attempt | `{key}` | null; processing claim becomes failed, usage retained |
| delete | `{id?}` | null; delete session/history and results, retain usage |
| suspend | `{value: boolean}` | null; control plus audit |
| upload_create | `{session,id,content_type,size_bytes,duration_seconds,suffix}` | full object metadata |
| upload_claim | `{id,session}` | metadata, authorized -> uploading exactly once |
| upload_get | `{id,session?}` | owned usable metadata, or metadata for cached completion |
| upload_state | `{id,state}` | metadata after allowed transition |
| cleanup_list | `{}` | cross-owner safe metadata candidates only |
| cleanup_done | `{id}` | null, tombstone after confirmed Storage deletion |
| import_legacy | seven row arrays plus optional fingerprint (below) | counts/fingerprint/replayed receipt |

Janitor actions may use `p_owner=NULL`; `cleanup_done` locks the actual metadata owner rather than the caller-supplied owner. `cleanup_list` includes `id,user_id,bucket,path,state,session_id,delete_after`, never object bytes or URLs.

## Transaction / quota / validation invariants

The per-owner boundary is `pg_advisory_xact_lock(hashtextextended(owner::text,0))`. Quota/control/completion/deletion/import/upload mutations serialize here across real worker connections. Global controls are read with a shared row lock so an administrative kill-switch update is ordered against active RPCs. `require_active`, reservations, claims, upload authorization and completion fail closed if AI is disabled or the owner is suspended.

Database limits default to **20/day and 200/month**, with CHECK constraints disallowing higher configured limits. Caller limits can only lower those caps. UTC day/month counts are computed under the lock; reservation plus claim/usage is one transaction. Provider failures and history deletion never refund usage.

An operation key is unique per owner. Processing/failed/expired keys cannot be reassigned. A ten-minute lease fences stale completion without changing the adapter's initial tokenless contract. Completed retries return the saved attempt without another usage charge. Finish binds the operation owner and session to the attempt, and an associated upload must still be processing/unexpired. Attempts, transcripts, coaching reports, operation completion and upload cleanup marking commit together; any late write failure rolls all of those back.

Strict reports reject extra keys, wrong JSON types (including boolean/decimal scores), out-of-range integers, oversized arrays/strings, absent evidence, extra nested fields, and evidence quotes not present as exact transcript substrings. All Report/Pydantic fields and bounds are represented. Decoded duration retains the proven browser tolerance **29.85–180.15 seconds**; upload declarations remain 30–180 seconds. Scenario context and example response are each 1–5000 characters; goal 1–1000. SQLSTATE PT403/PT404/PT409/PT422/PT429 use safe application messages; the adapter maps these to HTTP status.

## Upload and retention contract

Metadata path is `{owner}/{object_id}/response{suffix}`. Initial authorization expires after five minutes; raw-audio `delete_after` is at most 24 hours, enforced by CHECK constraints. MIME/suffix pairs are explicit. Claim must occur before authorization expiry, atomically transitions authorized -> uploading, and cannot be reused. Relay validates actual bytes/duration before upload-state/processing; metadata is not authoritative media validation.

`begin_attempt.upload_id` consumes one owned uploaded object and uniquely associates it with the operation. Completion/failure marks cleanup_pending. Session/history deletion marks pending cleanup and detaches metadata before cascading application rows; metadata survives session deletion. `upload_state` permits uploaded/processing/cleanup_pending/deleted only through allowed transitions and cannot revive a deleted object. `cleanup_done` is idempotent for deleted tombstones. Both deleted transitions are trusted backend assertions and must occur only after Storage confirms deletion.

Cleanup excludes live authorization/upload/processing. Candidates are cleanup_pending, beyond the hard retention deadline, expired authorized uploads, or uploading/processing stale for at least ten minutes. Owner-locked cleanup completion rechecks eligibility, preventing a candidate listed earlier from tombstoning a now-live object.

Account deletion requires a separate orchestration path: the metadata owner FK intentionally prevents auth deletion from silently orphaning objects. Purge/reconcile metadata tombstones only after confirmed cleanup; this schema does not claim an implemented account-deletion RPC.

## Legacy import contract

`import_legacy` takes arrays `profiles,sessions,attempts,usage,controls,audit,operations`; all seven are required, including empty arrays. Optional `fingerprint` is a lowercase 64-hex identifier; otherwise it is SHA-256 of the canonical JSONB payload without that field. Each row's `user_id` must equal mapped `p_owner` (an existing Auth UUID); owner mapping/backup/export is the parent's responsibility.

Row projections preserve SQLite columns:
- profiles `{user_id,data}`
- sessions `{id,user_id,data}`
- attempts `{id,user_id,session_id,data}`
- usage `{id,user_id,created_at}`
- controls `{user_id,suspended}` (boolean or original integer 0/1)
- audit `{id,user_id,action,created_at}`
- operations `{user_id,key,session_id,state,attempt_id}`

`data` may be decoded JSON or the original JSON string. IDs, payloads, timestamps, operation state, attempts, usage and original audit records are preserved; normalized transcript/report rows are derived transactionally. No existing application row is overwritten. Source ID conflicts fail for operator reconciliation rather than silently dropping records. Imported in-flight operations retain state but receive an expired lease because there is no trusted surviving worker. Receipt hashes detect same-fingerprint/different-payload conflicts; exact replay returns counts without duplicate writes. Identity sequences advance monotonically past imported IDs; PostgreSQL sequence advancement itself is nontransactional, but imported rows and receipt are transactional.

## Real verification and TDD evidence

Local server: **PostgreSQL 15.14 (Homebrew)**, not mocks or a remote test account. Minimal bootstrap supplies `auth.users`, `auth.uid()`, roles and Storage catalog tables; it does not emulate deployed Auth, PostgREST HTTP or Storage object bytes.

Observed RED -> GREEN slices:
1. Schema test failed with absent `profiles`/RLS inventory -> schema and actual owner profile CRUD passed.
2. Atomic contract failed because `speechclear_api` did not exist -> quota/claim/completion/cache/read/deletion contract passed.
3. Upload test failed `Unknown action` -> authorization/claim/single-use/cleanup passed.
4. Legacy import failed `Unknown action` -> preservation, replay, owner mapping and transactional rollback passed.
5. Hardening regressions: noncanonical UUIDs were accepted, null key leaked a constraint detail, and deleted uploads could finish -> five failing cases turned green after validation/fencing.
6. Existing MIME bucket mismatch was not rejected and trusted child writes could alter normalized report/transcript -> two failing tests turned green after configuration verification/child triggers.

Final targeted suite: **28 passed**. Additional tests execute anon/User A/User B SELECT and denied generated-data writes, direct owner profile writes, denied RPC calls, cross-owner references, empty/oversized/unmatched reports, late child failure rollback, session binding, expired leases, real concurrent quota and same-key claims, monthly quota, upload expiry/deletion/24h constraints, import late-FK rollback and cleanup on a deliberate verifier exception. The concurrency barrier explicitly observes an advisory-lock waiter in `pg_stat_activity` with nonempty `pg_blocking_pids`, rather than inferring contention from two launched threads.

Reproduce from the repository:
```sh
cd backend
uv run --frozen python scripts/verify_postgres.py
uvx ruff check scripts/verify_postgres.py tests/test_postgres_schema.py
uvx ruff format --check scripts/verify_postgres.py tests/test_postgres_schema.py
```

The verifier scrubs inherited PG connection/credential variables, overrides credential/service config paths with private absent files, uses a private 0700 scratch directory and Unix socket only, asserts empty listen_addresses, applies migrations transactionally, and stops/removes the cluster in finally. Tests prove PID and directory removal on injected failure. Homebrew's first PATH `initdb` came from client-only libpq and lacked `postgres`; verifier selects an installed PostgreSQL server binary directory instead. It never installs a server or connects to an existing database.

An intermediate full backend run returned **174 passed, 2 failed** in concurrently authored `tests/test_persistence_cutover.py`: existing app startup still selected SQLite/created the file. Those app/adaptor files are outside this worker's ownership; no claim is made that the parent integration/release gate passes. Remote catalog/RLS/Storage readback, actual HTTP status mapping, live Auth A/B access, actual Storage bytes/deletion, and provider/browser end-to-end remain parent verification work.
