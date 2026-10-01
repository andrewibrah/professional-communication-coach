# Frontend verification — steps 1–3

## Result

**17 frontend tests pass across 6 files; TypeScript and Vite production build pass.** A real headless Chromium smoke check passed for the signed-out/backend-unavailable UI. Live Supabase authentication and OpenAI recording-to-report verification remain pending. No `.env` was read or modified by this lane; no backend sources were changed and no commits were made.

## Spec review before quality review

Reviewed `IMPLEMENTATION_CONTRACT.md`, the actual frontend sources, and backend `app.py`, `models.py`, and `pyproject.toml` read-only.

| Requirement | Implementation / evidence | Boundary |
| --- | --- | --- |
| Desktop React workspace | Overview, studio, history, progress, profile/privacy; browser smoke visits all five | Desktop widths exercised; not a full accessibility audit |
| Real auth, public API config | Supabase JS initialized from `/api/v1/config`; protected APIs acquire a verified user's access token | SDK boundary mocked in tests; live project not authenticated |
| Fail-closed setup | Explicit backend-unavailable/auth-pending states; private generation/save/delete and sign-in submission disabled when unavailable | Chromium exercised actual API-unavailable state, without runtime mocks |
| Six scenarios | API list with clearly labeled offline previews if unavailable | Offline cards are descriptions, not generated sessions |
| Scenario/recording/coaching | Contract-aligned POST scenario, multipart audio with duration and UUID idempotency header, real report rendering | Provider/media boundaries simulated only in tests; no live audio or AI claims |
| Recording boundaries | 30–180 seconds, size/empty validation, automatic stop, track cleanup, stop/cancel without pause | Unit tests cover boundary validation, hard stop, cancellation, late permission grant/denial |
| Same-session retry | First/latest comparison; retrying failed upload retains recording and idempotency key | Component test covers upload failure → retry → fetched saved reports |
| History/trends/profile/privacy | Saved report scores only, profile PUT/read-back, usage, confirmed deletion/read-back | Live persistence/deletion not exercised by this frontend lane |
| Honest integration boundary | UI labels SQLite/direct audio upload; account deletion disabled; no knowledge uploads | Supabase database/private Storage migration still pending |

Frontend endpoints, snake_case fields, report fields, upload form names, and idempotency header were compared to actual backend routes. Profile character limits were corrected against the actual Pydantic schema.

## Material quality fixes and RED → GREEN evidence

### 1. Private data returning after sign-out

Root cause: `refresh()` could resolve after the auth callback had cleared private state and then repopulate sessions, profile, and usage. Initial SDK hydration could also overwrite a newer auth event.

- Added `src/auth-lifecycle.test.tsx`, holding a real `Response` across a simulated SDK sign-out.
- RED command: `npm test -- --run src/auth-lifecycle.test.tsx`.
- Observed failure: the signed-out history still displayed `PRIVATE OWNER A GOAL`.
- Fix: synchronously invalidate owner/request generations, clear private state on identity changes, ignore outdated hydration and refresh results, and unsubscribe/ignore after cleanup.
- GREEN: targeted test passed.

### 2. Private API response crossing an account change

Root cause: the API wrapper checked authentication only before dispatch, not after token acquisition or response decoding.

- Added regression to `src/api.test.ts` holding a private response while the current owner changes.
- RED command: `npm test -- --run src/api.test.ts`.
- Observed failure: promise resolved `{role: 'Private A'}` instead of rejecting.
- Fix: optional API owner scope checked after token acquisition and response decoding; upload completion is also scoped. App supplies an owner-generation counter, separate from refresh-request counters.
- GREEN: API and auth-lifecycle tests passed together.

### 3. Late microphone rejection overriding cancellation

Root cause: a permission request rejected after cancellation, and its catch handler still wrote the recorder's UI state/error.

- Added cancellation/late-denial regression in `src/flow.test.tsx`.
- RED command: `npm test -- --run src/flow.test.tsx`.
- Observed failure: a microphone-denied alert appeared after Cancel recording.
- Fix: ignore rejection from a controller no longer active.
- GREEN: component suite and full suite passed.

### 4. Recovery event while sign-in modal was already open

Root cause: auth dialog mode was initialized from the recovery prop only on mount.

- Added open-modal recovery rerender regression in `src/flow.test.tsx`.
- RED: expected `Choose a new password`, but the modal remained `Welcome to SpeechClear`.
- Fix: react to recovery changes and clear password/messages before showing the update form.
- GREEN: regression passed.

### 5. Profile input/backend length mismatch

Root cause: most frontend fields allowed 250 characters even where backend validation allowed 200; other fields were unnecessarily constrained.

- Added schema-limit regression in `src/App.test.tsx`.
- RED command: `npm test -- --run src/App.test.tsx`.
- Observed failure: role `maxlength` was 250 instead of 200.
- Fix: explicit per-field limits matching `backend/models.py` (200/1000/500/4000 as appropriate).
- GREEN: full suite/build passed.

Additional coverage in `src/practice-flow.test.tsx` verifies failed-upload retry retains its UUID key and uses the same session, reads back saved attempts, and renders first/latest reports with evidence and priority coaching. Recording tests also verify automatic 180-second stop and a permission grant arriving after cancellation.

## Final execution

From `frontend/`:

```sh
npm ci
npm test -- --run
npm run build
```

Actual output:

- `npm ci`: installed 163 packages, audited 164, reported 0 vulnerabilities.
- Vitest: **6 files passed; 17 tests passed**.
- TypeScript/Vite: successful build, 1627 modules transformed.
- Generated assets: CSS 15.17 kB; JS 497.10 kB (141.84 kB gzip).
- Install warning: transitive `whatwg-encoding@3.1.1` is deprecated. It did not prevent installation, testing, or build.

`uv run --frozen --no-sync uvicorn --help` succeeded from `backend/`, verifying the documented backend CLI/options without loading the credential-bearing app. Backend service startup, backend tests, and live provider integration are not claimed by this lane.

## Real browser smoke

The built-in browser tool could not start because its configured Google Chrome executable was absent. Used the locally cached Playwright/Chromium alternative, without changing app code or installing a browser, and launched a short-lived Vite process on port 5187.

The smoke ran against the actual React app, with no route/data mocks:

- Actual status: `Backend unavailable · You can explore scenarios. Sign-in and practice need the local API.`
- All five navigation screens rendered.
- Six scenario buttons; scenario generation disabled while signed out.
- Sign-in modal opened and closed; submission disabled with missing auth config.
- Empty history/progress states; profile save, delete-history, and account-deletion controls disabled.
- No horizontal overflow at 1440, 1024, and 768 viewport widths.
- No uncaught browser page errors.

Temporary verification artifacts are in the active profile's scratch directory:

- `/Users/me/.hermes/profiles/telegramlite/cache/scratch/frontend-smoke.cjs`
- `/Users/me/.hermes/profiles/telegramlite/cache/scratch/frontend-overview.png`

The script closes Chromium and terminates its Vite process in `finally`. A subsequent socket check confirmed port 5187 was no longer listening. No long-lived server was left running. Screenshot capture is evidence of rendering, not a claim of a comprehensive human visual review.

## Remaining gates

- Live Supabase signup/email confirmation/sign-in, recovery, refresh, verified token behavior, and cross-account use.
- Real browser microphone recording with actual media in supported browsers, OpenAI transcription/report output, quotas, and remote failure cases.
- Live history/profile persistence and deletion read-backs.
- Supabase application database/private Storage integration, production hosting/proxy/HTTPS, account deletion, and any later document-upload feature.
- Claude Code Supabase MCP is configured including Storage; last recorded state is **Pending approval**. This lane did not approve or authenticate it and did not perform remote mutations.

Test fixtures and SDK/media/provider mocks are confined to test files. No fabricated scores, transcripts, or generated sessions were introduced into runtime code.
