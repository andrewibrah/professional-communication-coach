# Bounded security corrections (local verification only)

## Implemented

- **Stale janitor race:** service-only `cleanup_claim` RPC uses the common owner advisory lock, compares the listed `updated_at` generation and rechecks eligibility before returning exact deletion metadata. Sweep deletes only returned claims, never unconditionally converts an old list candidate to cleanup intent.
- **Late/crashed writer reconciliation:** deleted tombstones remain in every `cleanup_list`, including exact bucket/path/suffix/content type and generation. Every sweep deletes and verifies exact absence again. Tombstones must not be purged while late writes remain possible. `cleanup_get` equivalent (`upload_get`) completed replay behavior and `begin_attempt` cached completed results are preserved.
- **Relay:** request-body drain has an asyncio 120-second wall-clock bound; after probing and checking account availability, `upload_write_check` rechecks owner/session, uploading state, authorization expiry, retention deadline and claim age before writing. A late provider write after that check is still possible (TOCTOU), so compensation always attempts physical deletion even when marking SQL cleanup intent fails. Threadpool work is not falsely described as cancelled network I/O. Upload/download use 120-second iteration deadlines plus 30-second HTTP I/O timeouts; upload does not drain the provider response body. These are bounded transport operations, not cross-system atomicity.
- **Local temporary files:** actual relay and download allocations now use `speechclear-`, private folder mode 0700 and mkstemp file mode 0600. Symlinked folder/ancestors are rejected; the configured directory must remain backend-controlled, not writable by untrusted local actors.
- **Storage policy fail-closed:** initial migration rejects any pre-existing `storage.objects` policy and removes none. Broad/public unrelated policies cannot silently OR-combine with new access rules. An operator must explicitly review before retrying.
- **Quota timestamps:** one `clock_timestamp()` is captured after the owner lock and used for UTC daily/monthly boundaries and explicit usage insertion, not transaction-start `now()`.
- **Import sequence race:** all RPCs take a shared global transaction advisory lock; import takes it exclusively, before the per-owner lock. Import holds ACCESS EXCLUSIVE locks on usage/audit tables through sequence adjustment, preventing ordinary direct service inserts from evaluating their identity nextval during setval. Direct operational sequence calls by trusted superuser/service tooling remain outside the runtime contract and must follow the same operational locking discipline.
- **Normalized attempts:** BEFORE UPDATE trigger makes attempt parents immutable, including direct service-role updates; service deletion/cascade remains allowed. Generated tables retain authenticated SELECT-only grants.
- **Privileged transport:** PrivateStorage disables inherited proxy/environment configuration (`trust_env=False`), rejects placeholders/unclassified keys and classifies legacy JWTs as service_role before use. JWT classification is not signature verification; Supabase performs credential verification.

## Exact RED / GREEN evidence

Commands run from `backend/` with frozen existing dependencies; no new dependency, remote write, deploy or commit.

1. `uv run --frozen pytest tests/test_postgres_schema.py -q -k 'cleanup_claim_rechecks or parent_is_immutable or existing_storage_policy'`
   - RED: **3 failed** (missing candidate updated_at; direct service attempt update succeeded; permissive Storage policy migration did not reject).
   - GREEN after SQL changes: **3 passed, 28 deselected**.
2. `uv run --frozen pytest tests/test_postgres_schema.py -q -k 'quota_timestamp or import_crossowner_runtime or import_blocks_direct'`
   - RED: **3 failed** (usage timestamp predates lock release; no global advisory waiter; no direct-insert table waiter).
   - GREEN: **3 passed, 31 deselected**. PostgreSQL `pg_stat_activity` and `pg_blocking_pids` establish real observed advisory/relation contention, and sequence continuation exceeds imported id 100.
3. `uv run --frozen pytest tests/test_cleanup_races.py -q`
   - RED: **4 failed** (stale janitor deleted a live generation; second sweep did not repair a late write; SQL intent failure prevented physical compensation; slow drain returned media error rather than timeout).
   - GREEN integration later includes barrier-held actual relay uploads, deletion/tombstone during the hold, forced SQL failures after release, physical compensation, a crashed/delayed writer repair on the next sweep, and pre-write deletion rejection.
4. `uv run --frozen pytest tests/test_private_storage.py -q`
   - RED credential/proxy slice: **3 failed, 8 passed** (environment proxy flag absent; arbitrary legacy key and anon JWT accepted).
   - RED transfer-deadline slice after transport classification fix: **1 failed, 11 passed** (expired upload iterator accepted).
5. Final owned-file gate: `uv run --frozen pytest tests/test_cleanup_races.py tests/test_storage_routes.py tests/test_postgres_schema.py tests/test_private_storage.py -q && git diff --check`
   - **56 passed in 38.92s**, diff check success.
6. Broader checkpoint: `uv run --frozen pytest -q`
   - **229 passed, 1 failed in 44.31s**. Failure is outside this worker's ownership: `tests/test_app_storage_integration.py::test_lifespan_retries_cleanup_and_closes_clients_and_scopes_local_sweep` expected `Cleanup deferred` in caplog, but caplog was empty. App/admin worker must resolve/recheck this integration gate.

## Evidence boundaries / operational guarantees

PostgreSQL runs in disposable private Unix-socket-only local clusters with synthetic auth/storage bootstrap. Storage transport tests use HTTP doubles and deterministic synthetic object stores, not remote Supabase Storage. Raw media fixtures are controlled local samples. No `.env`, credentials, private source contents or real user account data were read for this work.

Cleanup is **eventual under a running successful cleanup worker** and available SQL/Storage. The 24-hour metadata deadline is eligibility, not an absolute physical-retention promise during downtime/provider outage. A finite physical write may occur after an absence check; recurring durable tombstone reconciliation repairs it. This design does not claim an atomic absent-forever guarantee spanning SQL and object storage.

Remote migrations and anonymous/A/B account/Storage security gates remain **BLOCKED pending explicit user authorization**. Local bootstrap tests do not waive those gates. Migrations are edited pre-application only.
