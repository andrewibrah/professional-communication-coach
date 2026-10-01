# Guided Voice SQL/store lane — local verification handoff

## Outcome and scope

Locally accepted; **not remotely applied or live-provider verified**. Preserved the surviving implementation and only edited the new, unapplied Guided migration, dedicated adapter, their tests, and verifier discovery. No Recorded Practice migration edits, credential inspection, remote requests, accounts, commit, push, or deployment.

Changed:
- `supabase/migrations/202610010004_guided_voice.sql`
- `backend/guided_store.py`
- `backend/tests/test_guided_postgres.py`
- `backend/tests/test_guided_store.py`
- `backend/scripts/verify_postgres.py`
- This handoff, `.hermes/docs/verification/GUIDED_SQL_LANE.md`

## Exact integration interfaces

```python
command_result(owner, id, command_id, request_fingerprint=None)
commit(owner, id, expected_revision, data,
       command_id=None, request_fingerprint=None)
```

The RPC payload key is exactly `request_fingerprint`. Its supplied value must be a canonical 64-character lowercase hexadecimal SHA-256 string; invalid values produce safe 422 errors. A supplied fingerprint on commit requires `command_id`. Python `None` preserves legacy omission; explicitly supplying JSON null to the SQL RPC is invalid.

`guided_commands.request_fingerprint` is nullable, CHECK-constrained text. Both lookup and commit reject a mismatch with `PT409` / adapter HTTP 409 `Request conflict`. A fingerprinted receipt cannot be read or replayed without its exact fingerprint. A legacy NULL receipt may be read/replayed only without a fingerprint; supplying one conflicts rather than silently upgrading the receipt. The existing commit snapshot hash additionally prevents changed snapshot replays.

The parent must hash canonical normalized CommandInput/ConnectionInput, including action/connection request identity, and pass the hash to both lookup and commit. This lane does not retain raw SDP or compute request fingerprints from runtime input. Legacy callers remain compatible but UUID-only lookup does not establish raw request/action equality.

Other interfaces remain unchanged. SQL metadata returns exactly `{"schema":"guided_voice","version":1}` and passes the real-SQL adapter readiness test. Lease receipts expose exactly owner/id/worker_id/call_id to the privileged backend; public session DTOs contain no provider handles.

## Observed RED → GREEN

- Baseline: `uv run --frozen pytest tests/test_guided_store.py tests/test_guided_postgres.py -q` — **14 passed**.
- Fingerprint tracer: two new tests failed because the adapter lacked the optional keyword and SQL rejected the unknown key. Added column, validation, lookup/commit equality protection and compatibility semantics; the then-current suite passed **16 tests**.
- Pause tracer: two tests failed because SQL rejected a fresh-heartbeat pause at 25 seconds and late attach did not mark a 31-second paused call pending. Unified pause grace to **30 seconds** in watchdog, heartbeat, claim, commit, and attach; kept heartbeat/claim timeout **20 seconds** and default absolute duration **300 seconds**. Nullable paused timestamps are coalesced to false in attach's nonnullable pending expression.
- Auth deletion tracer: an actual blocked reserve plus actual account deletion reproduced **`ERROR: deadlock detected`** (owner advisory lock versus auth FK transaction lock). Added a SECURITY DEFINER **BEFORE DELETE STATEMENT** boundary on `auth.users` taking the global exclusive lock before any auth row lock; the exact test then passed. Ordinary RPC owner existence is now checked after serialization.
- Composite FK tracer: insertion of owner B's lease into owner A's reservation initially succeeded (`DID NOT RAISE`). Added reservation UNIQUE(id,owner) and composite lease FOREIGN KEY(id,owner); final real-SQL suites pass.

Additional tests exercise existing protections; they are regression/security coverage, not claimed as new RED-driven implementation.

## Real PostgreSQL evidence

Disposable **PostgreSQL 15.14 (Homebrew)**, synthetic UUID owners and role bootstrap, Unix socket only; `SHOW listen_addresses` returned `''`. Clusters were stopped and scratch directories removed by the verifier. This is real PostgreSQL transaction evidence, not real Supabase Auth/account evidence.

Concurrency tests wait for actual `pg_stat_activity.wait_event='advisory'` and nonempty `pg_blocking_pids`, recording distinct backend PIDs before releasing the transaction barrier:

- Two competing reservations: both observed waiting; exactly one commits, the other conflicts as already active; one reservation remains.
- Two same-revision CAS commits: both observed waiting; exactly one commits, the other has a revision conflict; exactly one command receipt exists.
- Daily quota contention: five deleted 300-second reservations retain 1500 seconds of charges; competing reserve+delete transactions both wait on the owner lock. Exactly one additional reservation commits, the other gets quota reached; total remains **1800 seconds**, even with caller limits of 999999. Reserve+delete happens within each transaction so max-active cannot confound the quota result. Deleted history never refunds allowance.
- Quota clock: reserve demonstrably waits on an owner lock; committed created_at is at or after a clock_timestamp captured immediately before release, heartbeat_at equals created_at, and expires_at is exactly 300 seconds later. Database function readback also verifies UTC day/month windows use that same instant and the monthly 18000 hard ceiling.
- Two watchdog workers: the first holds A and waits on B; the second demonstrably waits on the first. B's stale heartbeat is refreshed inside the barrier holder's transaction; both watchdogs recheck after lock acquisition and leave both sessions active. Stable owner ordering avoids an owner-lock cycle.
- Auth deletion/reserve: reserve is stopped inside an actual BEFORE INSERT trigger after taking its owner boundary. Account deletion is observed blocked; releasing the barrier allows both operations to complete, cascades public content, and leaves ended/deleted operational metadata.

Additional coverage: lower configured monthly quota and cross-owner isolation; independent heartbeat and absolute expiry; no pause-deadline reset on repeated pause; exact late call handles after claim expiry/history deletion/account deletion; abandoned generation replaced before old callback arrives; all resulting live handles queued for termination; three physical setup claims maximum; reconnect token totals 3500+2500 trigger the aggregate 6000 cap; monotonic per-lease usage and exact worker/call release fencing; immutable prompt/turn generation, strict child-parent agreement, cross-owner generated-child rejection; rollback after late child-write failure; deleted command receipts/content; safe adapter malformed-response rejection.

## Security/spec self-review

- Normal authenticated role has owner-only SELECT on Guided sessions/prompts/turns. Neither normal roles nor service_role have direct operational table access or generated table writes. All Guided private helpers deny PUBLIC/anon/authenticated/service_role execution; only the service RPC is callable by service_role.
- Tested actual privilege catalogs and owner SELECTs. A second migration test deliberately installs permissive managed-style default table/function grants first; the Guided migration still removes direct generated writes, operational reads/writes and helper execution. The privileged RPC continues to work.
- Generated prompt/turn inserts must exactly match their committed parent arrays; updates are immutable. Session identity/settings and previous array entries cannot mutate. Lease ownership is bound by a composite FK; operational metadata has no cascading auth/session FK, so deletion cannot erase a call handle before confirmed termination.
- Callback tombstones preserve exact handles even after account/history deletion or abandoned-generation replacement. Deleted content and command receipts disappear; small usage/lease tombstones intentionally survive for quota and provider cleanup.
- All timed eligibility is rechecked under owner serialization, and pause grace is distinct from browser heartbeat expiry. Usage sums **all** connection leases, including ended ones, rather than resetting on reconnect.
- The auth deletion statement lock is deliberately global/exclusive: rare account deletion waits for all shared-global RPCs before locking auth rows. This is broader than per-owner deletion and needs parent review before remote apply. It also protects multi-account deletion from accumulating owner locks in inconsistent row order.
- Ad hoc privileged direct writes outside these RPC/trigger boundaries are not a supported concurrent writer path. Public child deletion/parent mutation by a database superuser cannot be prevented by API-role grants.

## Final commands and results

From `backend/`:

```text
ruff check guided_store.py tests/test_guided_store.py tests/test_guided_postgres.py scripts/verify_postgres.py
  All checks passed!
ruff format --check guided_store.py tests/test_guided_store.py tests/test_guided_postgres.py scripts/verify_postgres.py
  4 files already formatted
uv run --frozen pytest tests/test_guided_store.py tests/test_guided_postgres.py -q
  41 passed in 33.36s
uv run --frozen python scripts/verify_postgres.py
  64 passed in 63.04s
```

The verifier now explicitly discovers both Recorded `test_postgres_schema.py` and Guided `test_guided_postgres.py`. The five barrier/lock-order tests were repeated in three further independent runs: **5 passed** each (5.28s / 5.08s / 5.22s). `git diff --check` passed; an explicit scan of all five owned source files found no trailing whitespace (including untracked source omitted by Git diff).

Recorded migration read-only SHA-256 reference values:

```text
202609300001_speechclear.sql 02c53c58686ad0b94c8581e293cee1b936e6bdf3b455def9e6e383f8540f71ab
202609300002_atomic_api.sql 077676b4dcb03e5d1dd9fb82e8704905b57dbef5ad6148530f4c4961cb4229ab
202609300003_legacy_import.sql 12368b7d68b3da4b9f2dc3c9101a4b4f51d45caea5792f74ca2e505e2cde811b
```

## Remaining gates / limits

- Parent independent spec/security review and full backend/frontend integration regression remain parent-owned. This report does not claim those gates passed.
- Remote Supabase migration apply/catalog readback and authorized real accounts/provider/browser speech/termination are **NOT RUN**. No substitute account or network probe was used.
- The actual 1800 daily hardcap and lower monthly quota are executed. The 18000 monthly hard ceiling is also verified in deployed-local function text; this lane does not claim a live month-boundary crossing or thirty-day usage history experiment.
- SQL records durable termination intent; it does not prove physical provider hangup. Multiple watchdog workers may receive the same pending handle and must perform idempotent termination. Handles are released only with the exact worker/call and confirmed result. Cleanup depends on a running worker/provider availability, and a delayed callback can briefly overlap a newer generation until it is captured and terminated.
- Trusted runtime cumulative usage and normalized request hashing must be integrated by the parent; these cannot be inferred merely from passing SQL/store tests.
