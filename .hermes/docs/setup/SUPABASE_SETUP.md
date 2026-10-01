# SpeechClear — Supabase runtime and management setup

Target: `https://qpheitaamyzcekzvbcox.supabase.co`, explicitly authorized development root.

## Current state

Three additive migrations are applied. The original SQLite session/usage were protected, imported and exactly read back; the default API uses Supabase only. Both private buckets exist. Current proof/limitations: [implementation handoff](../handoffs/SUPABASE_IMPLEMENTATION_HANDOFF.md). Real two-account/browser acceptance remains paused, not waived.

## Runtime configuration (backend only)

Privately edit the existing repository-root `.env`; never overwrite it with a template or paste values in chat. [Configuration reference](supabase.env.example) contains empty fields, not credentials.

- `SUPABASE_URL`: exact target above.
- `SUPABASE_PUBLISHABLE_KEY`: public/publishable or legacy anon key; the only Supabase key allowed in browser config.
- `SUPABASE_SECRET_KEY`: modern `sb_secret_` backend key, sent in `apikey`, never treated as a JWT Bearer token.
- `SUPABASE_SERVICE_ROLE_KEY`: alternative legacy service-role JWT. Not required when the modern backend secret is configured; an existing placeholder is not used.
- `SUPABASE_JWT_AUDIENCE`: `authenticated` unless deliberately changed.
- `OPENAI_API_KEY`: backend-only.

Never use `VITE_*` for privileged credentials. `/api/v1/config` exposes only allowlisted public fields. Runtime database URLs are not required by this REST/RPC adapter. MCP OAuth does not supply runtime application credentials.

## Protected readiness gate

Private persistence requires the operator-owned 0600 `backend/data/supabase-cutover.json`, created only after protected import/replay/exact readback. Missing/invalid receipt or configuration returns 503; there is no SQLite fallback/dual-write. Health reports configured backend and local receipt/Storage readiness, not live RLS acceptance.

[Protected import/backout procedure](../verification/PERSISTENCE_CUTOVER.md) defines source-write freeze, 0700 backup directory, 0600 snapshot files, owner mapping, transactional import and non-destructive fail-closed backout. Do not fabricate or manually bypass the receipt.

## Supabase Auth

- Email enabled and confirmation required.
- Local Site URL `http://localhost:5173`; narrowly scoped local redirects only.
- Configure reliable SMTP where required; development-mail restrictions are separate from database access.
- Modern asymmetric JWT signing; backend verifies issuer/audience/signature/expiry and server-confirmed email status.

Live confirmation, password recovery, token refresh and two-account/browser flows require designated secure participation. Supabase advisors currently report leaked-password protection disabled and the pre-existing `rls_auto_enable` execute warnings; these were not silently changed.

## Management

Use JOSE's authenticated project-scoped Supabase MCP for project inspection and additive migrations. Discover current tool schemas and verify `get_project_url` before remote operations; read back exact affected schema/grants/policies/object after writes. Do not use the Supabase CLI. No reset, billing change, public deployment, commit or push is authorized.

Earlier separate Claude/OpenCode registration states are historical and do not describe JOSE's working MCP. The repository-local `.hermes/.mcp.json` is not an application credential.

## Local restart

From backend: `uv run --frozen uvicorn app:app --host 127.0.0.1 --port 8000`.

From frontend: `npm run dev`.

Open `http://localhost:5173`. API must be available for the browser to obtain public Auth configuration; an offline API can cause misleading setup-pending UI even when the account/project exists. Do not recreate the account or replace credentials to repair a deliberately stopped local process.

## Storage/privacy boundary

Five-minute verified-owner/session upload authorization, one-use claim, raw-byte API relay to private Supabase Storage, then opaque JSON processing reference. Server derives paths and validates actual bytes/container/decoded duration. No built-in two-hour signed upload URL is exposed. Durable periodic cleanup is eventual with running workers and available services, not an unconditional 24-hour physical-retention promise during downtime. External-provider retention is separate. Account deletion/document ingestion remain disabled.
