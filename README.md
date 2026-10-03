# SpeechClear

Professional communication practice built with React, TypeScript, Vite, FastAPI, and Supabase.

## GitHub Pages preview

The GitHub Actions workflow in [`.github/workflows/pages.yml`](.github/workflows/pages.yml) installs dependencies, runs frontend tests, builds with the repository's Pages base path, and deploys **only `frontend/dist`** on pushes to `main` or manual dispatch. In GitHub repository settings, Pages must use **GitHub Actions** as its build source.

**This deployment hosts the frontend and connects directly to Supabase Auth.** Public repository variables `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` are embedded at build time, so sign-in does not depend on FastAPI. Only `sb_publishable_*` browser keys are accepted by the static fallback; never configure a secret/service-role key. Local development still prefers `/api/v1/config` when available.

GitHub Pages cannot run FastAPI or proxy `/api`. Saved practice, uploads, and AI coaching remain unavailable without a separately hosted HTTPS API. No mock accounts or fabricated coaching results are supplied. A successful Pages deployment is not production or live-provider acceptance.

In Supabase Authentication URL Configuration, allow the exact redirect URL `https://andrewibrah.github.io/professional-communication-coach/` while preserving local redirects. The frontend now requests this repository-aware URL for signup confirmation, password recovery, and sign-in emails. If it is not allowed, Supabase can fall back to the existing Site URL; changing the frontend alone does not modify project settings. Existing email/password sign-in does not need an email redirect. Actual account and email-delivery acceptance remains user-tested.

Local build matching a project Pages URL:

```sh
cd frontend
npm ci
npm test
npm run build -- --base /professional-communication-coach/
```

To enable the full app later, separately deploy the FastAPI backend and add an explicit HTTPS API-origin configuration to the frontend's public-config fetch, authenticated requests, and upload relay. Configure backend CORS for the exact Pages origin and Supabase authentication redirect URLs for the full Pages URL. The current frontend deliberately retains its existing same-origin `/api` behavior; no external API URL has been supplied. Never embed backend credentials in the frontend or Actions artifact.

## Local development and verification

See the [application overview and setup](.hermes/docs/overview/README.md), [documentation index](.hermes/docs/README.md), and [user guide](.hermes/docs/guides/SPEECHCLEAR_USER_GUIDE.md).

Run frontend checks with `cd frontend && npm test && npm run build`. The local Vite server proxies `/api` to FastAPI on port 8000; this development proxy is not part of the static build.

The backend, database migrations, and tests are included as source, not deployed by this Pages workflow. Existing live-account/provider verification limitations remain documented in the [engineering log](.hermes/docs/execution/doc.md).

Environment files, private runtime data, generated builds, dependencies, TypeScript build caches, and local MCP configuration are excluded from Git.
