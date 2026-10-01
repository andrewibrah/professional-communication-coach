# Guided backend lane — verified handoff

## Outcome and ownership

Resumed surviving implementation; no replacement architecture or runtime fixtures. Modified only `backend/guided_models.py`, `guided_coach.py`, `guided_runtime.py`, `guided_routes.py` and their four `backend/tests/test_guided_*.py` counterparts, plus this new evidence file. Parent-owned provider/app/store/SQL and frontend/shared documents were not edited.

- Fixed both reproduced runtime regressions: finish persistence failure no longer skips hangup; reconnect no longer overwrites trusted usage from a previous call.
- Finish/pause/reconnect terminate despite receipt/read/commit or cancellation-send failure. Watchdog database outage terminates local calls rather than skipping enforcement. Release failures leave durable handles for reconciliation; close still attempts both resource closures.
- Each connection uses a fresh UUID lease generation. `provider.connect(sdp, owner, on_created=...)` persists `store.attach` from the callback before sideband setup completes; successful setup does not duplicate attach. Known-call setup failure/cancellation attempts exact-generation hangup/release. Unconfirmed hangup remains retryable.
- Sideband dispatch and watchdog fence the exact connection generation; old callbacks/leases cannot terminate or mutate a reconnected call.
- Runtime tracks session aggregate usage while sending monotonic per-call totals to SQL, whose durable aggregate spans workers. ASR/voice duplicates are counted once; aggregate 6000 terminates.
- Replay interrupts pending playback, including before response.created; obsolete nonces remain eligible only for usage accounting, not progression. Listening requires transcript confirmation, generation completion AND output drain.
- Non-finish commands require confirmed identity; finish/deletion remain independent of AI availability. Expanded transcript-only acoustic-claim rejection. Tests cover empty/failed/uncertain recognition, no overlapping evaluation, speech-start visibility context, pause preemption, late deleted callbacks and immutable targets/finite retries.

## Observed RED → GREEN

`uv run --frozen pytest tests/test_guided_runtime.py -q` initially returned **10 passed, 2 failed**, matching the interrupted-lane failures. Finish-only regression became green first, then usage/setup-callback regressions became green.

Additional observed failing-first slices: watchdog storage outage; stale watchdog/callback generation; replay during pending playback; setup cancellation; provider-close failure; nonconfirmed active command; common transcript-only acoustic claims; terminal receipt/read outages. Each was rerun green before broader verification. Recognition/visibility/delete/usage duplicate tests additionally exercise surviving behavior.

## Final local verification

Run from `backend/`:

- `uv run --frozen pytest tests/test_guided_models.py tests/test_guided_coach.py tests/test_guided_runtime.py tests/test_guided_routes.py -q` → **37 passed** (post-format).
- Same command plus `tests/test_guided_store.py tests/test_guided_postgres.py` → **51 passed**, including disposable PostgreSQL checks.
- `uv run --frozen ruff check guided_models.py guided_coach.py guided_runtime.py guided_routes.py tests/test_guided_models.py tests/test_guided_coach.py tests/test_guided_runtime.py tests/test_guided_routes.py` → **All checks passed**.
- `uv run --frozen ruff format --check` on those eight paths → **8 files already formatted**.
- `uv run --frozen pytest -q` → **287 passed, 5 failed**. All five failures are parent-owned `test_voice_provider.py::test_non_audio_only_sdp_is_rejected_before_billable_provider_setup` cases: `VoiceProvider` lacked `connect` at that in-progress snapshot. No parent file was modified to mask them.

## Parent integration / remaining gates

- Confirmation callable passed to route registration must accept the already-verified identity as its sole argument (sync or async). Runtime stores JWT expiry only, never bearer tokens; parent identity dependency remains responsible for real JWT verification.
- Durable command receipts currently store result snapshots, not request fingerprints. Exact request replay is tested, but same command ID with a different action/payload is not durably rejected across workers/restarts. A store/SQL contract extension is needed if conflict rejection is required; do not claim this property.
- Local pause grace is 30s; current SQL expires paused presence at 20s. SQL remains authoritative; reconcile the intended constant during integration.
- Provider adapter still owns audio-only SDP rejection, initial confirmed GA configuration, actual transport teardown and callback cleanup. The callback cannot eliminate the provider POST-to-Location crash window or guarantee durable attach when the database itself is unavailable.
- All identity/provider evidence here uses explicit synthetic doubles; SQL evidence is disposable local PostgreSQL. No real account, microphone/user speech, live provider, remote migration, deployment, commit/push, secret/environment/private-data reads or network writes were performed. Live browser/provider/two-owner acceptance remains gated.
