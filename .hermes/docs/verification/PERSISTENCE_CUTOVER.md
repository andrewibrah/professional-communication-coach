# Protected Supabase persistence cutover

The default FastAPI runtime uses Supabase only. Missing credentials, an invalid target, or a missing/invalid protected cutover receipt disables private persistence with 503; it never opens SQLite or falls back. SQLite is retained only as an explicitly injected test adapter and a read-only migration source.

## Operator sequence (not executed against the deployed project)

1. Stop all application writers and keep them stopped through verification. Review the three SQL migrations and deploy them through the separately authorized deployment workflow. Verify service-only RPC access, grants/RLS, Auth owners and private Storage configuration before production cutover.
2. Prepare an explicit, complete, one-to-one source-owner → canonical Supabase Auth UUID mapping in a private local JSON file. Do not paste private owners or exports into chat/logs.
3. From `backend/`, prepare a new protected snapshot directory:
   ```sh
   .venv/bin/python migration.py backup-export data/speechclear.sqlite3 data/cutover-backup --owner-map data/owner-map.json
   ```
   The original database is opened read-only and copied with SQLite backup (including committed WAL data). Snapshot directory mode is 0700; backup, export and manifest modes are 0600. Existing directories/files are not overwritten. Output is metadata only.
4. Review and preserve the backup/manifest locally. Configure the backend credentials through the existing secure configuration mechanism; never put secret values on command lines. The exact authorized target is `https://qpheitaamyzcekzvbcox.supabase.co`.
5. Only when remote writes are explicitly authorized, execute:
   ```sh
   .venv/bin/python migration.py import-export data/cutover-backup/export.json --receipt data/supabase-cutover.json
   ```
   The destination receipt must not already exist and its directory must be owned by the operator, mode 0700, and nonsymlinked. A missing immediate directory is created mode 0700. A pre-existing receipt blocks the command before client construction.
6. Start the app only after successful import and receipt creation. Check `/api/v1/health`: `storage` identifies the configured backend; `persistence_ready` and `audio_storage_ready` describe local configuration/receipt readiness, not a live Supabase connectivity or RLS probe. Execute separately authorized two-user/anonymous database and Storage acceptance tests before declaring production readiness.

## Import guarantees and limitations

- Before writing, validate protected-file ownership/modes/no-symlinks, exact export table schema, backup/export/schema SHA-256, integrity, counts, row relationships, owner mapping and every owner's domain data.
- Verify every mapped Auth owner exists and has a timezone-aware email or phone confirmation timestamp using privileged Auth admin GETs before the first write. Revalidate the local snapshot after those callbacks.
- Submit all seven legacy row arrays through the service-only `import_legacy` RPC, atomically **per owner**. Immediately replay the same fingerprint and verify the idempotent replay receipt.
- Read back each imported source ID scoped to its mapped owner. Compare full source fields, normalized JSON and timestamps, and the separate transcript and coaching-report rows. Unrelated existing private rows are not fetched. Counts alone never authorize cutover.
- Create the receipt exclusively, mode 0600, only after all owners pass exact readback. It binds the exact target/project reference, backup/export hashes, timezone-aware verification timestamp and literal-true owner/readback/readiness flags. CLI output contains only a safe success/failure statement, never private rows, owners, provider errors or credentials.
- Multi-owner import is **not** one global transaction. A later owner's failure can leave earlier owners imported. No receipt is created on failure; the app stays fail-closed. Preserve the same protected export, investigate conflicts/readback locally and retry the identical export for idempotent reconciliation. Do not regenerate fingerprints to conceal partial imports, waive readback, or automatically delete remote data.
- `compare_receipt` is a metadata comparison helper, not independent cutover authorization. An operator-owned receipt is a local trust boundary, not a signature or ongoing remote data audit.

## Non-destructive backout

Stop the application first. Preserve/export any new Supabase private data and Storage metadata created since cutover through a separately authorized, protected backup procedure; keep the original SQLite backup/export/manifest and receipt together. Archive/remove the readiness marker so private routes remain disabled. Reconcile newly created data explicitly before any future migration decision. This procedure does not delete remote rows/objects and does not reactivate SQLite automatically. Returning to a legacy runtime would require a separate explicit rollback decision and data reconciliation, not an environment-variable fallback.

## Evidence boundary

Local tests exercise disposable PostgreSQL transactions/authorization with synthetic data and a local HTTP bridge for Auth/REST readback. FastAPI integration tests use explicit injected adapters and real WAV validation. No production import, remote writes, live account tests or cutover was performed by this implementation task.
