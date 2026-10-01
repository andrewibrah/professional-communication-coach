# SpeechClear

Professional communication practice built with React, TypeScript, Vite, FastAPI, and Supabase.

## GitHub Pages preview

The GitHub Actions workflow in [`.github/workflows/pages.yml`](.github/workflows/pages.yml) installs dependencies, runs frontend tests, builds with the repository's Pages base path, and deploys **only `frontend/dist`** on pushes to `main` or manual dispatch. In GitHub repository settings, Pages must use **GitHub Actions** as its build source.

**This deployment is a frontend-only preview.** GitHub Pages cannot run FastAPI or proxy `/api`. Without a separately hosted HTTPS API, the interface is explorable but authentication, saved practice, uploads, and AI coaching are unavailable and fail closed. No mock accounts or fabricated coaching results are supplied. A successful Pages deployment is not production or live-provider acceptance.

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
