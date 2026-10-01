# Frontend private Storage upload handshake

## Implemented contract

`Api.upload<T>(sessionId, blob, seconds, onProgress, key, signal?)` retains its public interface. It now owns three same-origin, owner-authenticated requests:

1. `POST /api/v1/sessions/{encodedSessionId}/attempt-uploads` sends JSON `{content_type, size_bytes, duration_seconds}` with a bearer token and the original canonical UUID `Idempotency-Key`. The response must contain a canonical lowercase UUID `upload_id` and a parseable `expires_at` strictly in the future, at most six minutes ahead. The server contract is a five-minute authorization; the extra minute is client clock tolerance, not an extension of server authority.
2. `PUT /api/v1/sessions/{encodedSessionId}/attempt-uploads/{upload_id}` sends the raw Blob using XMLHttpRequest, bearer authentication, and the Blob's original Content-Type. Only HTTP 204 acknowledges successful upload. Progress reflects the actual byte transfer; it is capped at 99 until the server acknowledges it, then becomes 100 for processing.
3. `POST /api/v1/sessions/{encodedSessionId}/attempts` sends JSON `{upload_id}` with the same canonical idempotency key and returns the existing Attempt JSON contract.

The frontend does **not** upload directly to Supabase, obtain signed Storage URLs, expose private object paths, or use a two-hour capability URL. All media passes through the authenticated API relay. Private Supabase Storage is backend-only; browser-user JWT Storage upload policies are not needed for this design. Database ownership checks, authoritative five-minute expiry, atomic `authorized -> uploading` consumption, media inspection, provider calls, and object deletion are server responsibilities, not client guarantees.

## Client safety and retry semantics

- Preserves native fetch's global receiver and the existing injected auth/owner-generation contract; `Api.get` is unchanged.
- Checks owner generation and cancellation before authentication and subsequent network stages, after token resolution, response arrival, JSON decoding, and byte completion. Does not refresh session data after SessionView unmounts while upload is completing.
- Rejects malformed keys without normalization. Session IDs remain opaque strings and are URL-encoded, preserving existing non-UUID test/UI contracts.
- Checks nonempty supported audio, finite 30–180 second duration, and the 12 MiB client limit before authorization. The backend must independently enforce these constraints.
- Keeps only upload metadata in Api-instance memory, scoped by owner generation and `[sessionId, key]`. Once a 204 is acknowledged, retries skip authorization and byte transfer and replay only processing, even after upload authorization expiry. This supports completed-attempt idempotent replay after the Storage object has been deleted.
- Records byte acknowledgement before calling the 100% progress callback, so cancellation at that callback does not lose the uploaded receipt. Cancelled/failed byte transfer discards its unacknowledged receipt and obtains a fresh authorization on retry; it does not reuse a potentially consumed authorization.
- Does not render backend upload/processing error payloads, signed URLs, bucket paths, or private provider details. HTTP errors use local messages.
- Explicit processing failure/unavailability responses (400/404/410/422/502) require a new recording. A processing 409 is conservatively treated as already-processing **or** unavailable: the UI directs the user to check practice history before a new recording instead of promising a safe retry of a failed key. Transport/lost-response errors retain the recording/key for processing-only replay. No production fixture or fake report is introduced.

## UI contracts retained

Recording controls, duration constraints, retrying a transport failure with the same key, and first-versus-latest feedback comparisons remain intact. A terminal processing failure removes the stale submit action and offers a fresh recording; it does not report success or refresh session data. Successful feedback still refreshes the authoritative session.

## Local TDD evidence

All commands ran in `/Users/me/Desktop/professional-communication-coach/frontend` without a live account, remote Storage, provider, migration, deployment, or commit.

Observed RED runs before the corresponding production changes:

- Initial handshake test: `npm test -- src/api.test.ts` — **1 failed, 5 passed**; legacy multipart upload rejected the expected three-stage response as unreadable.
- Authorization/key validation slice — **8 failed, 6 passed**.
- Processing replay/terminal failure slice — **2 failed, 14 passed**.
- `npm test -- src/practice-flow.test.tsx` — **2 failed, 1 passed**; terminal failure still offered resubmission and unmount still triggered a session refresh.
- Audio validation/unavailable-key slice — **7 failed, 16 passed**.
- Cancellation immediately after byte acknowledgement — **1 failed, 38 passed**, due to sending bytes twice.
- Cancellation during byte relay — **1 failed, 39 passed**, due to retaining consumed authorization.
- Already-cancelled token-provider guard — **1 failed, 40 passed**, due to calling the token provider.
- Owner change after JSON decoding but before the public upload return — **1 failed, 41 passed**, due to resolving a private old-owner result instead of rejecting.

Final verification (run after all production/test changes):

```text
npm test
Test Files  6 passed (6)
Tests       57 passed (57)
Duration    1.13s

npm run build
> tsc -b && vite build
vite v6.4.3 building for production...
✓ 1627 modules transformed.
dist/index.html                   0.44 kB │ gzip:   0.31 kB
dist/assets/index-fIEM8lK6.css    15.17 kB │ gzip:   4.41 kB
dist/assets/index-CjPQ0WWo.js    499.23 kB │ gzip: 142.57 kB
✓ built in 1.09s

git diff --check
(no output; exit 0)
```

API suite now contains 42 tests, including transport receiver preservation, authenticated metadata/bytes/processing, opaque session encoding, malformed/expired/long-lived authorization, client size/duration/MIME limits, owner changes at each stage, cancellation boundaries, generation-scoped receipts, private HTTP payload isolation, processing-only replay, terminal failures, and consumed-authorization recovery. Practice-flow suite contains 3 tests. The full 57-test run includes the existing auth-lifecycle, app, flow, and recording suites. TypeScript compilation includes `src` and therefore the test sources too. No warnings appeared in the final test/build output.

`git diff --check` has limited scope here: the initial repository state had frontend files untracked, so that command is not proof of a tracked change diff. Test and TypeScript/build results are the substantive execution evidence.

## Limits / remaining external verification

- Tests use local mocked network/recorder boundaries; they do not prove live JWT verification, database ownership/RLS, private bucket isolation, atomic authorization consumption, real microphone/browser transfer, quota accounting, provider behavior, or actual object cleanup. These require separate authorized server/browser verification; live account tests were expressly not run.
- Upload receipts are memory-only. Reloading the tab, recreating the Api instance, or switching owner generation discards retry metadata; this is not a durable cross-reload resume protocol.
- The frontend cannot distinguish a running attempt from a failed/unavailable key using the backend's generic processing 409 alone. It explicitly describes that ambiguity and directs the user to practice history rather than claiming a report exists.
- An interrupted byte relay may already have consumed its server authorization. A subsequent client retry creates another short-lived authorization; cleanup of any previous private object is the backend's durable cleanup responsibility.
- The API relay adds server bandwidth/latency compared with direct browser-to-Storage upload. This is an intentional tradeoff for short-lived identity-bound authorization, not a direct-to-Supabase signed-upload implementation.

## Owned files

Modified `frontend/src/api.ts`, `frontend/src/api.test.ts`, `frontend/src/SessionView.tsx`, and `frontend/src/practice-flow.test.tsx`. Created this verification document. No environment/configuration, backend/app.py, doc.md, authentication implementation, remote services, or public deployment were modified by this frontend task. Build regenerated ignored local `frontend/dist` output.
