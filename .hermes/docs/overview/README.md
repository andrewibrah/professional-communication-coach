# SpeechClear

A desktop-first professional communication practice app built with React, TypeScript, Vite, and FastAPI. This is a **local development alpha covering steps 1–3**, not a completed production release. The `DAY_*` documents describe requirements, not verified delivery.

## Available now

- Overview, practice studio, practice history, progress, and profile/privacy screens.
- Six conversation types: introductions, technical interviews, help desk, cybersecurity explanations, sales, and customer escalations.
- Supabase JS email signup/sign-in, sign-in links, sign-out, email verification instructions, password-reset email, and password updates. The browser obtains public configuration from the API; the SDK manages session refresh.
- Personalized scenario generation, 30–180-second microphone responses, transcription, and structured coaching through the backend's real OpenAI integration when authentication and AI configuration are connected.
- Same-session retries with first/latest reports, transcript evidence, category scores, strengths, priority improvements, rewritten answers, and practice exercises.
- Saved-session history, scores computed from saved reports, professional profile editing, AI-operation usage, and deletion of sessions or all practice history.

Without a working API or configured authentication, the app remains explorable but private actions fail closed. Offline scenario descriptions are labeled previews. There are **no runtime mock reports, sample scores, fake accounts, or auth bypasses**.

## Architecture and limitations

```text
React browser → Vite /api proxy → FastAPI /api/v1
       │                              │
       └── Supabase Auth              ├── owner-scoped Supabase Postgres/RPC
                                      ├── private Supabase Storage (API relay)
                                      └── OpenAI scenario/transcription/coaching
```

The API validates Supabase JWTs; AI operations also require server-confirmed email verification. Application persistence now uses Supabase Postgres through backend-only atomic RPCs, with ownership constraints and Row Level Security. The existing SQLite session/usage records were privately backed up, imported and exactly read back; SQLite is no longer an active runtime store.

Recordings use a five-minute owner-authenticated upload authorization, FastAPI raw-byte relay to private Supabase Storage, and JSON processing reference with a canonical UUID `Idempotency-Key`. Actual media is validated with `ffprobe` and bounded `ffmpeg` decoding. Local copies and raw Storage objects are deleted after processing; periodic durable cleanup retries failed/crashed work and reconciles late writes. Cleanup requires a running API and available services; outages can exceed the 24-hour eligibility deadline. No signed upload URLs or permanent audio replay are exposed. External-provider retention is separate from application deletion.

Three additive Supabase migrations and the protected persistence cutover are applied. **Actual verified two-user isolation and browser/provider end-to-end acceptance remain BLOCKED pending authorized test participation.** Account deletion and knowledge/document uploads remain disabled. This is a local development alpha, not a production release or compliance guarantee. See the [current handoff](../handoffs/SUPABASE_IMPLEMENTATION_HANDOFF.md).

## Local setup

Prerequisites:

- Node.js and npm. Frontend checks in this lane used Node `v24.15.0` and npm `11.12.1`.
- Python 3.11+ and [uv](https://docs.astral.sh/uv/).
- FFmpeg's `ffprobe` and `ffmpeg` on `PATH` for container validation and bounded decoded-duration measurement (`brew install ffmpeg` on macOS). Browser streaming WebM may omit duration metadata; the API measures decoded samples rather than trusting the client. Decoded duration permits only 150 ms of codec/start-stop precision at the 30/180-second boundaries; declared duration remains 30–180 seconds.
- A Supabase project with email authentication and a usable public/publishable key for real accounts.
- An OpenAI API key for live AI practice.

### Configuration

Use [the configuration reference](../setup/supabase.env.example) when privately editing the existing repository-root `.env`; never overwrite it with a template. Backend runtime needs `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` (or a legacy backend service-role key), and `OPENAI_API_KEY`. `SUPABASE_JWT_AUDIENCE` normally remains `authenticated`. See [SUPABASE_SETUP.md](../setup/SUPABASE_SETUP.md). Private persistence additionally requires the protected receipt created only by verified import; missing setup fails closed without SQLite fallback.

Use a public/publishable (or legacy anon) key for browser auth, never a service-role secret. Do not put privileged values in `VITE_*` variables. `/api/v1/config` exposes only public auth configuration and feature/recording limits.

For local auth redirects, configure Supabase's Site URL as `http://localhost:5173` and allow the corresponding local redirect URLs. Enable email confirmation. Restart the API after configuration changes. Configuration flags alone do not prove that live signup, verification, or coaching works; those still require end-to-end validation.

### Backend — terminal 1

```sh
cd /Users/me/Desktop/professional-communication-coach/backend
uv sync --frozen
uv run --frozen uvicorn app:app --host 127.0.0.1 --port 8000
```

The backend loads the root `.env` at startup and serves the API on port 8000. The Uvicorn CLI/options were checked in this frontend lane; the credential-bearing backend was not started or live-authenticated by this lane.

### Frontend — terminal 2

```sh
cd /Users/me/Desktop/professional-communication-coach/frontend
npm ci
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` to `http://127.0.0.1:8000`. Keep the documented localhost origin consistent with Supabase redirects. Browser microphone access requires localhost or HTTPS. Stop development servers with Ctrl+C.

### Frontend checks

```sh
cd /Users/me/Desktop/professional-communication-coach/frontend
npm test -- --run
npm run build
```

Verified in this lane: clean `npm ci`, **17 tests passing across 6 files**, and successful TypeScript/Vite production build. A temporary Chromium smoke check also exercised all five screens, six scenario cards, signed-out controls, the sign-in modal, and widths 1440/1024/768 with no horizontal overflow or uncaught page errors. It tested the honest backend-unavailable state, not live authenticated practice. See [FRONTEND_VERIFICATION.md](../verification/FRONTEND_VERIFICATION.md).

The `dist/` build needs an `/api` reverse proxy on deployment; Vite's development proxy does not apply to arbitrary static hosting. HTTPS and correctly configured Supabase redirects are also required outside localhost.

## Supabase management

JOSE's authenticated project-scoped Supabase MCP connection manages `qpheitaamyzcekzvbcox`. Discover current schemas and verify the project URL before operations. Management OAuth is not an application credential. Use MCP for inspection and additive migrations; do not use the Supabase CLI for this project workflow.

Earlier Claude Code registration notes are historical and do not describe JOSE's current authenticated connection. No public deployment, reset, real-data deletion, commit, or push was performed.

## Next verification gates

1. Connect Supabase credentials privately and exercise signup, confirmation, sign-in, password recovery, refresh, and sign-out against the live project.
2. Exercise a real 30–180-second recording, transcription/coaching, retry, history/profile persistence, quotas, and deletion with real provider responses.
3. Complete actual User A/User B direct database/Storage isolation and browser practice/retry/deletion gates before presenting the implementation as release-complete. Account deletion remains a separate unavailable feature.

[IMPLEMENTATION_CONTRACT.md](../requirements/IMPLEMENTATION_CONTRACT.md) is the integration contract for this alpha.

## Completion-checklist execution receipt

Current independently executed checks: **235 backend tests**, Ruff lint/format, **58 frontend tests**, and TypeScript/Vite build. Live evidence includes applied schema/ACL/bucket readback, exact preserved-data import, anonymous database CRUD denial, and controlled private Storage byte/deletion roundtrip. Actual Chromium audio regression remains intact. These are not live two-user authenticated coaching evidence. See [the current handoff](../handoffs/SUPABASE_IMPLEMENTATION_HANDOFF.md); the [older completion report](../handoffs/SUPABASE_COMPLETION_REPORT.md) is historical.
