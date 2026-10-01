# Guided Voice frontend lane verification

## Delivered scope

Frontend-only implementation. No backend, migrations, shared documentation, credentials, environment/private storage, live account/provider requests, auth bypass, commits, pushes, or deployment changes.

New runtime files:
- `frontend/src/guided-types.ts`: bounded exact-key DTO/list/connection validators and optional guided availability validation; no provider handles or secrets.
- `frontend/src/guided-api.ts`: authenticated wrapper around the existing owner-scoped `Api.get`, preserving its receiver/token/owner checks; explicit UUID command IDs, expected revisions and current prompt IDs.
- `frontend/src/voice-session.ts`: audio-only WebRTC transport and rejection-safe controller/mutation lane, polling/heartbeat, cancellation, local gating, recovery, and teardown.
- `frontend/src/GuidedSessionView.tsx`: honest setup, structured prompt suppression, controls, recap and separate owner-guided history/readback/deletion verification.

Integration changes: `frontend/src/App.tsx`, `frontend/src/types.ts`, `frontend/src/styles.css`. Recorded Practice remains the default; its existing recording controller, authenticated upload API, 30–180-second validation and report flow were not modified. Recorded report/history links explicitly select Recorded Practice even after Guided Voice was selected. Guided sessions do not enter `/100` averages.

Test-only files: `guided-api.test.ts`, `voice-session.test.ts`, `guided-view.test.tsx`, `guided-app.test.tsx`, `guided-lifecycle.test.ts`, `guided-safety.test.ts`, and clearly labeled `guided-test-doubles.ts`. No fixture is imported by application runtime.

## Security contract applied

The superseding contract is **audio-only WebRTC, no provider data channel**. Offers and answers reject application/SCTP/video and require exactly one active audio section. The browser has no provider captions, transcription event listener or provider response/session control path. Authoritative scoring, prompt progression, audio completion and orientation remain backend responsibilities.

Microphone transmission requires an authenticated authoritative `listening` snapshot, successful remote `Audio.play()`, and a 500 ms conservative media-tail grace. This grace is a bounded heuristic, **not proof that a human heard the complete audio**. Backend `output_audio_buffer.stopped` must control the trusted listening transition. There is no browser `response.done` shortcut or provider event-based scoring.

Hidden mode structurally omits target, transcript, free-form strength/correction, corrected example, evidence quote, spoken feedback, server status payload and target-derived recap. It uses generic statuses, enum decision labels, correction-presence labels and counts. No CSS-only hiding or hidden-target live region exists. Local hide preference is immediate and is not overwritten by stale authoritative visibility. Toggle retains focus and does not replace the peer/session/target or reset attempts. No guided content is written to localStorage, sessionStorage or IndexedDB.

Pause and End release media synchronously before awaiting persistence. End aborts a lost SDP request so an older connection cannot delay finish or publish late state. Resume/reconnect reacquire permission directly in their explicit gestures, fetch authority, enforce expiry and create a fresh connection; a paused GET does not accidentally stop the fresh microphone. Paused sessions retain their 2-second heartbeat lease within the absolute server limit. Polls, heartbeat and commands do not overlap.

Failed/ambiguous mutations reload authority and explain that no turn was automatically replayed. No automatic mutation resend exists; every explicit action has a fresh UUID. Logout attempts immediately remove active guided content and prevent restarting until the sign-out result, including sign-out failure. Owner replacement invalidates pending work and skips best-effort finish under the new owner. Unmount/navigation/pagehide release tracks, peer, Audio source, handlers, timers and pending requests; best-effort finish is bounded to 3 seconds under the original owner, otherwise server heartbeat lease applies.

## Observed RED → GREEN slices

Observed failing tests preceded production changes for: missing guided API/validators; missing transport/controller; hidden DOM and honest setup; finished-history readback/deletion; mode integration; End during lost SDP exchange; mute racing an in-flight poll; paused resume stopping freshly acquired media; stale Audio.play rejection after replay; permission error/cancelled permission UI; paused heartbeat; recorded-history mode selection; sign-out pending content suppression; and recovery after an unconfirmed finish. Targeted reruns passed after each correction. Additional regression tests exercise non-listening states, bounded ICE/peer waits, autoplay recovery, owner races, stale revisions, finite completion, expiry, history owner changes and storage suppression.

## Final execution

From `frontend/`:

```
npm test
Test Files  12 passed (12)
Tests       109 passed (109)

npm run build
tsc -b && vite build
1631 modules transformed
build succeeded
CSS 16.74 kB (gzip 4.74 kB)
JS 528.71 kB (gzip 150.43 kB)
```

Nonblocking build warning: the main JS chunk exceeds Vite's 500 kB recommendation. No build/type/test failures remain.

An executed runtime source guard also confirmed no `createDataChannel`, `speechSynthesis`, provider response/session control strings, `localStorage`, `sessionStorage`, or `indexedDB` in the four new runtime files.

## Verification limits / handoff

- Browser smoke could not run: `agent-browser` is not installed; the browser tool reported missing Chromium, and an alternate local Chrome/Playwright discovery found neither available. The isolated static build server answered HTTP 200 and was stopped after the attempted smoke. No browser screenshot or accessibility-tree proof is claimed.
- No live provider or account access was attempted, as required. Native transport source and test-double lifecycle execution are verified, but real provider negotiation, sideband-authoritative transitions, human-hearing quality, autoplay behavior in a real browser and live two-account RLS remain parent integration/release checks.
- The shared `Api.get` does not expose HTTP status as a typed error. The wrapper sanitizes guided failures; the controller reloads authoritative state after *any* unconfirmed mutation, which includes 409, without automatically replaying evaluated turns.
- Backend lease, max lifetime, permissions, provider cancellation and resume orientation remain authoritative server obligations. UI timer is informational, not a fabricated completion/scoring result.
