"""Server-authoritative Guided Voice orchestration with injected adapters.

Public methods return strict DTOs only. Private handles never enter persistence.
Store calls may be sync (offloaded) or async. No bearer token is retained.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
import hashlib
import json
import re
import time
import unicodedata
from uuid import uuid4
from weakref import WeakValueDictionary
from fastapi import HTTPException
from guided_models import GuidedSession, ConnectionOutput
import guided_coach as coach


async def invoke(fn, *args, **kwargs):
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    result = await asyncio.to_thread(fn, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


@dataclass
class _Handle:
    owner: str
    id: str
    connection: object
    lease_worker_id: str
    nonce: str | None = None
    spoken: str = ""
    response_id: str | None = None
    task: asyncio.Task | None = None
    tokens: int = 0
    auth_expires_at: float | None = None
    expires_at: float | None = None
    last_heartbeat: float = field(default_factory=time.monotonic)
    listening_since: float | None = None
    speech_item: str | None = None
    committed: set = field(default_factory=set)
    seen: set = field(default_factory=set)
    transcript_ok: bool = False
    generation_done: bool = False
    drain_done: bool = False
    usage_seen: set = field(default_factory=set)
    authorized: dict = field(default_factory=dict)
    obsolete_nonces: set = field(default_factory=set)
    commit_requested: bool = False
    evaluation: asyncio.Task | None = None
    epoch: int = 0
    visible_on_speech: bool = True
    prompt_on_speech: str | None = None
    epoch_on_speech: int | None = None
    speech_since: float | None = None
    asr_since: float | None = None
    finish_after_drain: bool = False
    final_playback_since: float | None = None


class GuidedRuntime:
    def __init__(self, settings, store, provider, regular_store, auth=None):
        self.settings, self.store, self.provider = settings, store, provider
        self.regular_store, self.auth = regular_store, auth
        self.worker_id = str(uuid4())
        self._handles, self._locks, self._setups = {}, WeakValueDictionary(), {}
        self._paused = {}
        self._tokens = {}
        self._evaluations = {}
        self._registry_deadlines = {}
        self._worker = None
        self._deadline_worker = None
        self._teardowns = set()
        self._closed = False

    def _lock(self, owner, id):
        return self._locks.setdefault((owner, id), asyncio.Lock())

    async def require_active(self, owner):
        ready = self.store.ready
        ready = await invoke(ready) if callable(ready) else ready
        if not ready or self._closed:
            raise HTTPException(503, "Guided practice unavailable")
        if (
            not self.settings.ai_enabled
            or not self.settings.openai_api_key
            or not getattr(self.settings, "guided_voice_enabled", True)
        ):
            raise HTTPException(503, "Guided practice unavailable")
        await invoke(self.regular_store.require_active, owner)

    def _forget(self, owner, id):
        for registry in (
            self._setups,
            self._tokens,
            self._evaluations,
            self._paused,
            self._registry_deadlines,
        ):
            registry.pop((owner, id), None)

    def _remember(self, owner, session):
        if session.state in coach.TERMINAL:
            self._forget(owner, session.id)
        else:
            self._registry_deadlines[owner, session.id] = datetime.fromisoformat(
                session.expires_at
            ).timestamp()
        return session

    async def get(self, owner, id):
        try:
            session = GuidedSession.model_validate(
                await invoke(self.store.get, owner, id)
            )
        except HTTPException as error:
            if error.status_code == 404:
                self._forget(owner, id)
            raise
        return self._remember(owner, session)

    async def list(self, owner):
        return [
            GuidedSession.model_validate(s)
            for s in await invoke(self.store.list, owner)
        ]

    @staticmethod
    def _fingerprint(data):
        return hashlib.sha256(
            json.dumps(
                data.model_dump(), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    async def _save(self, owner, session, command_id=None, request_fingerprint=None):
        fingerprint = (
            {}
            if request_fingerprint is None
            else {"request_fingerprint": request_fingerprint}
        )
        return self._remember(
            owner,
            GuidedSession.model_validate(
                await invoke(
                    self.store.commit,
                    owner,
                    session.id,
                    session.revision,
                    session.model_dump(),
                    command_id=command_id,
                    **fingerprint,
                )
            ),
        )

    async def create(self, owner, data, scenario):
        await self.require_active(owner)
        async with self._lock(owner, data.command_id):
            draft = coach.new_session(
                data.command_id,
                data.scenario_id,
                data.goal,
                data.prompt_visible,
                max_retries=getattr(self.settings, "guided_max_retries", 2),
            )
            saved = GuidedSession.model_validate(
                await invoke(
                    self.store.reserve,
                    owner,
                    draft.model_dump(),
                    getattr(self.settings, "guided_daily_seconds", 900),
                    getattr(self.settings, "guided_monthly_seconds", 9000),
                    300,
                    request_fingerprint=self._fingerprint(data),
                )
            )
            if saved.prompts or saved.state in coach.TERMINAL:
                return saved
            if not await invoke(
                self.store.claim_preparation, owner, saved.id, self.worker_id
            ):
                latest = await self.get(owner, saved.id)
                if latest.prompts or latest.state in coach.TERMINAL:
                    return latest
                raise HTTPException(409, "Guided preparation pending")
            try:
                profile = await invoke(self.regular_store.profile, owner)

                async def on_usage(response_id, tokens):
                    await invoke(
                        self.store.text_usage, owner, saved.id, response_id, tokens
                    )

                sentences = await self.provider.generate(
                    scenario, data.goal, data.context, profile, on_usage=on_usage
                )
                await self.require_active(owner)
                return await self._save(owner, coach.set_prompts(saved, sentences))
            except Exception:
                try:
                    await self._save(owner, coach.finish(saved, failed=True))
                except Exception:
                    pass
                raise HTTPException(502, "Guided preparation unavailable") from None

    def _unexpired(self, session):
        if (
            datetime.fromisoformat(session.expires_at) <= datetime.now(timezone.utc)
            or session.state in coach.TERMINAL
        ):
            raise HTTPException(409, "Practice has ended")

    async def connect(self, owner, id, data, auth_expires_at=None):
        await self.require_active(owner)
        fingerprint = self._fingerprint(data)
        async with self._lock(owner, id):
            receipt = await invoke(
                self.store.command_result,
                owner,
                id,
                data.command_id,
                request_fingerprint=fingerprint,
            )
            handle = self._handles.get((owner, id))
            if receipt is not None:
                if handle:
                    return ConnectionOutput(
                        sdp=handle.connection.sdp,
                        session=GuidedSession.model_validate(receipt),
                    )
                raise HTTPException(409, "Fresh connection required")
            session = await self.get(owner, id)
            self._unexpired(session)
            if (
                session.revision != data.expected_revision
                or handle
                or session.state not in {"created", "paused", "reconnecting"}
            ):
                raise HTTPException(409, "Refresh practice before reconnecting")
            if not session.prompts or self._setups.get((owner, id), 0) >= 3:
                raise HTTPException(409, "Connection setup unavailable")
            lease_worker_id = str(uuid4())
            await invoke(
                self.store.claim_connection,
                owner,
                id,
                session.revision,
                lease_worker_id,
            )
            self._setups[owner, id] = self._setups.get((owner, id), 0) + 1
            connection = None
            known_call_id = None

            async def on_created(call_id):
                nonlocal known_call_id
                if known_call_id is not None:
                    raise ValueError("Duplicate call setup")
                known_call_id = call_id
                await invoke(self.store.attach, owner, id, lease_worker_id, call_id)

            try:
                session = await self._save(
                    owner, coach.changed(session, state="connecting")
                )
                connection = await self.provider.connect(
                    data.sdp, owner, on_created=on_created
                )
                if connection.call_id != known_call_id:
                    raise ValueError("Call was not durably attached")
                handle = _Handle(
                    owner,
                    id,
                    connection,
                    lease_worker_id,
                    auth_expires_at=auth_expires_at,
                    expires_at=datetime.fromisoformat(session.expires_at).timestamp(),
                )
                self._handles[owner, id] = handle
                await self.require_active(owner)
                session = await self._save(
                    owner,
                    coach.changed(
                        session,
                        state="coach_speaking",
                        status_message="Listen to the target sentence.",
                    ),
                    data.command_id,
                    fingerprint,
                )
                await self._speak(
                    handle, coach.target_speech(session, orientation=True)
                )
                handle.task = asyncio.create_task(self._consume(handle))
                return ConnectionOutput(sdp=connection.sdp, session=session)
            except (Exception, asyncio.CancelledError) as error:
                try:
                    latest = await self.get(owner, id)
                    await self._save(owner, coach.finish(latest, failed=True))
                except Exception:
                    pass
                if connection and (owner, id) not in self._handles:
                    self._handles[owner, id] = _Handle(
                        owner, id, connection, lease_worker_id
                    )
                if (owner, id) in self._handles:
                    await self._terminate(owner, id)
                elif known_call_id is not None:
                    # Adapter also attempts hangup; keep the exact durable lease
                    # pending unless a retry confirms termination.
                    confirmed = False
                    try:
                        confirmed = await self.provider.hangup(known_call_id) is True
                    except Exception:
                        pass
                    try:
                        await invoke(
                            self.store.release_call,
                            owner,
                            id,
                            lease_worker_id,
                            known_call_id,
                            confirmed,
                        )
                    except Exception:
                        pass
                if isinstance(error, asyncio.CancelledError):
                    raise
                raise HTTPException(502, "Guided connection unavailable") from None

    async def _speak(self, handle, text):
        handle.nonce, handle.spoken = str(uuid4()), text
        handle.response_id = None
        handle.transcript_ok = handle.generation_done = handle.drain_done = False
        handle.speech_item = None
        handle.speech_since = handle.asr_since = None
        handle.prompt_on_speech = handle.epoch_on_speech = None
        handle.committed.clear()
        handle.commit_requested = False
        handle.listening_since = None
        await handle.connection.send(
            {
                "type": "response.create",
                "response": {
                    "conversation": "none",
                    "input": [],
                    "output_modalities": ["audio"],
                    "max_output_tokens": 300,
                    "metadata": {"guided_nonce": handle.nonce},
                    "instructions": "Read exactly the following text, with no additions: "
                    + text,
                },
            }
        )

    async def _consume(self, handle):
        try:
            async for event in handle.connection.events():
                await self._dispatch_event(
                    handle.owner, handle.id, event, source=handle
                )
                if self._handles.get((handle.owner, handle.id)) is not handle:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        async with self._lock(handle.owner, handle.id):
            if self._handles.get((handle.owner, handle.id)) is handle:
                await self._fail(handle)

    async def _discard(self, handle):
        handle.epoch += 1
        if handle.evaluation and handle.evaluation is not asyncio.current_task():
            handle.evaluation.cancel()
        if handle.speech_item:
            handle.seen.add(handle.speech_item)
        if handle.nonce:
            handle.obsolete_nonces.add(handle.nonce)
        if handle.nonce and not handle.generation_done:
            cancellation = {"type": "response.cancel"}
            if handle.response_id:
                cancellation["response_id"] = handle.response_id
            await handle.connection.send(cancellation)
        await handle.connection.send({"type": "output_audio_buffer.clear"})
        await handle.connection.send({"type": "input_audio_buffer.clear"})
        handle.nonce = handle.response_id = handle.speech_item = None
        handle.speech_since = handle.asr_since = None
        handle.prompt_on_speech = handle.epoch_on_speech = None
        handle.committed.clear()
        handle.commit_requested = False
        handle.listening_since = None

    async def command(self, owner, id, data):
        fingerprint = self._fingerprint(data)
        if data.action not in {"finish", "pause", "reconnect"}:
            await self.require_active(owner)
        async with self._lock(owner, id):
            handle = self._handles.get((owner, id))
            receipt_checked = False
            try:
                receipt = await invoke(
                    self.store.command_result,
                    owner,
                    id,
                    data.command_id,
                    request_fingerprint=fingerprint,
                )
                receipt_checked = True
                if receipt is not None:
                    return GuidedSession.model_validate(receipt)
                session = await self.get(owner, id)
            except Exception as error:
                if (
                    handle
                    and data.action in {"pause", "reconnect", "finish"}
                    and (receipt_checked or getattr(error, "status_code", None) != 409)
                ):
                    await self._terminate(owner, id)
                raise
            owned_interrupt = handle is not None and data.action in {
                "pause",
                "reconnect",
                "finish",
            }
            if session.revision != data.expected_revision and not owned_interrupt:
                raise HTTPException(409, "Refresh practice before changing it")
            handle = self._handles.get((owner, id))
            if (
                session.state
                in {"connecting", "coach_speaking", "listening", "reviewing"}
                and not handle
            ):
                raise HTTPException(409, "Reconnect required on this worker")
            if data.action != "finish" and not owned_interrupt:
                self._unexpired(session)
            if (
                handle
                and handle.finish_after_drain
                and data.action not in {"finish", "pause", "reconnect", "visibility"}
            ):
                raise HTTPException(409, "Final feedback is playing")
            try:
                if owned_interrupt and session.state in coach.TERMINAL:
                    updated = session
                else:
                    updated = coach.control(
                        session,
                        data.action,
                        None if owned_interrupt else data.prompt_id,
                        data.prompt_visible,
                    )
            except ValueError:
                raise HTTPException(
                    409, "Control unavailable for current practice"
                ) from None
            if data.action == "done":
                if (
                    not handle
                    or not handle.speech_item
                    or handle.speech_item in handle.committed
                    or handle.commit_requested
                    or session.muted
                ):
                    raise HTTPException(409, "No uncommitted speech to submit")
            if data.action == "unmute" and handle:
                updated = coach.changed(
                    updated,
                    state="coach_speaking",
                    status_message="Listen to the same sentence again.",
                )
            if data.action in {"pause", "reconnect", "finish"}:
                if handle and handle.finish_after_drain:
                    # The exercise is already evaluated; interruption cannot reopen it.
                    updated = coach.finish(session)
                try:
                    updated = await self._save(
                        owner, updated, data.command_id, fingerprint
                    )
                    if handle:
                        await self._discard(handle)
                finally:
                    # Persistence and cancellation are not prerequisites for hangup.
                    if handle:
                        await self._terminate(owner, id)
                if data.action == "pause" and updated.state == "paused":
                    self._paused[owner, id] = time.monotonic()
                return updated
            updated = await self._save(owner, updated, data.command_id, fingerprint)
            try:
                if data.action == "done":
                    handle.commit_requested = True
                    handle.asr_since = time.monotonic()
                    handle.speech_since = None
                    await handle.connection.send({"type": "input_audio_buffer.commit"})
                elif data.action == "mute" and handle:
                    await self._discard(handle)
                elif data.action in {"replay", "retry", "unmute"}:
                    if not handle:
                        raise ValueError("Fresh connection required")
                    await self._discard(handle)
                    await self._speak(
                        handle,
                        coach.target_speech(
                            updated, orientation=data.action == "unmute"
                        ),
                    )
                elif data.action == "resume":
                    self._paused.pop((owner, id), None)
            except Exception:
                if handle:
                    await self._fail(handle)
                raise HTTPException(502, "Guided control unavailable") from None
            return updated

    async def heartbeat(self, owner, id):
        async with self._lock(owner, id):
            session = await self.get(owner, id)
            handle = self._handles.get((owner, id))
            if (
                session.state
                in {"connecting", "coach_speaking", "listening", "reviewing"}
                and not handle
            ):
                raise HTTPException(409, "Reconnect required on this worker")
            if handle:
                handle.last_heartbeat = time.monotonic()
            return GuidedSession.model_validate(
                await invoke(self.store.heartbeat, owner, id)
            )

    async def delete(self, owner, id):
        async with self._lock(owner, id):
            session = await self.get(owner, id)
            handle = self._handles.get((owner, id))
            if (
                session.state
                in {"connecting", "coach_speaking", "listening", "reviewing"}
                and not handle
            ):
                raise HTTPException(409, "Reconnect required on this worker")
            try:
                if session.state not in coach.TERMINAL:
                    await self._save(owner, coach.finish(session))
            finally:
                if handle:
                    await self._terminate(owner, id)
            await invoke(self.store.delete, owner, id)
            self._forget(owner, id)

    async def start(self):
        if self._deadline_worker is None:
            self._deadline_worker = asyncio.create_task(self._deadline_loop())
        if self._worker is None:
            await self.watchdog_once()
            self._worker = asyncio.create_task(self._watchdog_loop())

    async def _deadline_loop(self):
        """Local safety has no SQL/business-lock dependency or serial hangups."""
        while True:
            now, wall = time.monotonic(), time.time()
            for (owner, id), expires in list(self._registry_deadlines.items()):
                if wall >= expires or now - self._paused.get((owner, id), now) >= 30:
                    self._forget(owner, id)
            for handle in list(self._handles.values()):
                if (
                    now - handle.last_heartbeat >= 20
                    or (handle.expires_at is not None and wall >= handle.expires_at)
                    or (
                        handle.auth_expires_at is not None
                        and wall >= handle.auth_expires_at
                    )
                    or (
                        handle.final_playback_since is not None
                        and now - handle.final_playback_since >= 15
                    )
                ):
                    task = asyncio.create_task(
                        self._terminate(
                            handle.owner, handle.id, expected=handle, deadline=True
                        )
                    )
                    self._teardowns.add(task)
                    task.add_done_callback(self._teardowns.discard)
            await asyncio.sleep(0.1)

    async def _watchdog_loop(self):
        while True:
            await asyncio.sleep(1)
            try:
                await self.watchdog_once()
            except Exception:
                continue

    async def watchdog_once(self):
        try:
            due = await invoke(self.store.watchdog)
        except Exception:
            # No database authority means no continuing expensive local calls.
            for owner, id in list(self._handles):
                async with self._lock(owner, id):
                    handle = self._handles.get((owner, id))
                    if handle:
                        await self._fail(handle)
            return
        for lease in due:
            owner, id = lease["owner"], lease["id"]
            async with self._lock(owner, id):
                handle = self._handles.get((owner, id))
                if (
                    handle
                    and handle.lease_worker_id == lease["worker_id"]
                    and handle.connection.call_id == lease.get("call_id")
                ):
                    await self._terminate(owner, id)
                else:
                    confirmed = False
                    if lease.get("call_id"):
                        try:
                            confirmed = (
                                await self.provider.hangup(lease["call_id"]) is True
                            )
                        except Exception:
                            pass
                    try:
                        await invoke(
                            self.store.release_call,
                            owner,
                            id,
                            lease["worker_id"],
                            lease.get("call_id"),
                            confirmed,
                        )
                    except Exception:
                        pass
        for owner, id in list(self._handles):
            async with self._lock(owner, id):
                handle = self._handles.get((owner, id))
                if not handle:
                    continue
                try:
                    await self.require_active(owner)
                    session = await self.get(owner, id)
                    self._unexpired(session)
                    if time.monotonic() - handle.last_heartbeat >= 20 or (
                        handle.auth_expires_at is not None
                        and time.time() >= handle.auth_expires_at
                    ):
                        raise ValueError("Authorization or heartbeat expired")
                    if (
                        handle.finish_after_drain
                        and handle.final_playback_since is not None
                        and time.monotonic() - handle.final_playback_since >= 15
                    ):
                        raise ValueError("Final feedback playback expired")
                    if (
                        handle.speech_since is not None
                        and time.monotonic() - handle.speech_since >= 30
                    ) or (
                        handle.asr_since is not None
                        and time.monotonic() - handle.asr_since >= 15
                    ):
                        await self._discard(handle)
                        message = (
                            "I could not confirm a complete sentence. Please try again."
                        )
                        session = await self._save(
                            owner,
                            coach.changed(
                                session,
                                state="coach_speaking",
                                status_message=message,
                            ),
                        )
                        await self._speak(
                            handle, message + " " + coach.target_speech(session)
                        )
                        continue
                    if (
                        session.state == "listening"
                        and not session.muted
                        and handle.speech_item is None
                        and not handle.committed
                        and not handle.commit_requested
                        and handle.listening_since is not None
                        and time.monotonic() - handle.listening_since >= 15
                    ):
                        await self._discard(handle)
                        message = "Would you like to hear it again?"
                        session = await self._save(
                            owner,
                            coach.changed(
                                session, state="coach_speaking", status_message=message
                            ),
                        )
                        await self._speak(
                            handle, message + " " + coach.target_speech(session)
                        )
                except Exception:
                    await self._fail(handle)
        for (owner, id), began in list(self._paused.items()):
            if time.monotonic() - began >= 30:
                async with self._lock(owner, id):
                    try:
                        session = await self.get(owner, id)
                        if session.state == "paused":
                            await self._save(owner, coach.finish(session))
                    finally:
                        self._paused.pop((owner, id), None)

    async def _fail(self, handle):
        try:
            latest = await self.get(handle.owner, handle.id)
            await self._save(handle.owner, coach.finish(latest, failed=True))
        except Exception:
            pass
        finally:
            await self._terminate(handle.owner, handle.id)

    @staticmethod
    def _normalized(text):
        return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())

    @staticmethod
    def _config_safe(handle, session):
        expected = getattr(handle.connection, "session_config", {})
        for key in (
            "instructions",
            "tools",
            "tool_choice",
            "output_modalities",
            "modalities",
            "model",
            "audio",
        ):
            if key not in session:
                continue
            if key in expected:

                def subset(actual, wanted):
                    if isinstance(wanted, dict):
                        return isinstance(actual, dict) and all(
                            k in actual and subset(actual[k], v)
                            for k, v in wanted.items()
                        )
                    return actual == wanted

                if not subset(session[key], expected[key]):
                    return False
            elif key == "instructions" and session[key] != "":
                return False
            elif key == "tools" and session[key] != []:
                return False
            elif key in {"modalities", "output_modalities"} and session[key] != [
                "audio"
            ]:
                return False
            elif key == "tool_choice" and session[key] not in {"none", "auto"}:
                return False
            elif key in {"audio", "model"}:
                return False  # Adapter must publish its non-secret approved session_config.
        return True

    async def _usage(self, handle, key, usage):
        if usage is None or key in handle.usage_seen:
            return
        count = usage.get("total_tokens")
        if type(count) is not int or count < 0:
            raise ValueError("Invalid usage")
        handle.usage_seen.add(key)
        handle.tokens += count
        session_key = (handle.owner, handle.id)
        self._tokens[session_key] = self._tokens.get(session_key, 0) + count
        # SQL stores monotonic per-call totals and sums all lease generations.
        await invoke(
            self.store.usage,
            handle.owner,
            handle.id,
            handle.lease_worker_id,
            handle.tokens,
        )
        if self._tokens[session_key] >= 6000:
            raise ValueError("Usage limit reached")

    async def _listening_if_drained(self, handle, session):
        if (
            session.state == "coach_speaking"
            and handle.transcript_ok
            and handle.generation_done
            and handle.drain_done
        ):
            if handle.finish_after_drain:
                try:
                    return await self._save(handle.owner, coach.finish(session))
                finally:
                    await self._terminate(handle.owner, handle.id)
            handle.listening_since = time.monotonic()
            handle.speech_item = None
            handle.committed.clear()
            return await self._save(
                handle.owner,
                coach.changed(
                    session,
                    state="listening",
                    status_message="Your turn. Repeat the target sentence.",
                ),
            )
        return session

    async def handle_event(self, owner, id, event):
        """Sideband-only entry; never registered as a browser HTTP command."""
        evaluation = await self._dispatch_event(owner, id, event)
        if evaluation:
            await evaluation

    async def _evaluate_completed(self, handle, reviewing, text, item, epoch):
        try:
            prompt = coach.current_prompt(reviewing)

            async def on_usage(response_id, tokens):
                await invoke(
                    self.store.text_usage, handle.owner, handle.id, response_id, tokens
                )

            async with asyncio.timeout(15):
                await invoke(
                    self.store.reserve_evaluation,
                    handle.owner,
                    handle.id,
                    handle.lease_worker_id,
                )
                feedback = await self.provider.evaluate(
                    prompt.id, prompt.text, text, on_usage=on_usage
                )
            async with self._lock(handle.owner, handle.id):
                if (
                    self._handles.get((handle.owner, handle.id)) is not handle
                    or handle.epoch != epoch
                ):
                    return
                await self.require_active(handle.owner)
                current = await self.get(handle.owner, handle.id)
                self._unexpired(current)
                if (
                    current.state != "reviewing"
                    or current.muted
                    or coach.current_prompt(current).id != prompt.id
                ):
                    return
                captured = coach.changed(
                    current, prompt_visible=reviewing.prompt_visible
                )
                updated = coach.complete_turn(captured, feedback, text, item)
                updated = coach.changed(updated, prompt_visible=current.prompt_visible)
                if updated.state == "finished":
                    final_text = (
                        updated.turns[-1].feedback.spoken_feedback
                        + " Practice complete."
                    )
                    updated = coach.changed(
                        updated,
                        state="coach_speaking",
                        status_message="Practice complete. Listen to the final feedback.",
                    )
                    updated = await self._save(handle.owner, updated)
                    handle.finish_after_drain = True
                    handle.final_playback_since = time.monotonic()
                    await self._speak(handle, final_text)
                    return
                updated = await self._save(handle.owner, updated)
                if updated.state in coach.TERMINAL:
                    await self._terminate(handle.owner, handle.id)
                else:
                    await self._speak(
                        handle,
                        updated.status_message + " " + coach.target_speech(updated),
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self._lock(handle.owner, handle.id):
                if self._handles.get((handle.owner, handle.id)) is handle:
                    await self._fail(handle)

    async def _dispatch_event(self, owner, id, event, source=None):
        async with self._lock(owner, id):
            handle = self._handles.get((owner, id))
            if not handle or (source is not None and source is not handle):
                return
            try:
                await self.require_active(owner)
                session = await self.get(owner, id)
                self._unexpired(session)
                kind = event.get("type")
                if kind in {"error", "response.failed"}:
                    raise ValueError("Provider error")
                if kind in {"session.created", "session.updated"}:
                    if not self._config_safe(handle, event.get("session", {})):
                        raise ValueError("Unexpected session configuration")
                    return
                if kind in {
                    "conversation.item.added",
                    "conversation.item.done",
                    "conversation.item.created",
                }:
                    item = event.get("item", {})
                    if item.get("type") in {
                        "function_call",
                        "function_call_output",
                    } or any(
                        part.get("type") == "input_text"
                        for part in item.get("content", [])
                    ):
                        raise ValueError("Unauthorized conversation input")
                    return
                if kind == "response.created":
                    response = event.get("response", {})
                    rid, nonce = (
                        response.get("id"),
                        response.get("metadata", {}).get("guided_nonce"),
                    )
                    if rid in handle.authorized and handle.authorized[rid] == nonce:
                        return
                    if rid and nonce in handle.obsolete_nonces:
                        handle.authorized[rid] = nonce
                        return
                    if (
                        not rid
                        or nonce != handle.nonce
                        or handle.response_id is not None
                    ):
                        raise ValueError("Unauthorized response")
                    handle.response_id = rid
                    handle.authorized[rid] = nonce
                    return
                if kind in {"response.output_item.added", "response.output_item.done"}:
                    if event.get("item", {}).get("type") == "function_call":
                        raise ValueError("Unauthorized tool")
                    return
                if kind in {
                    "response.output_audio_transcript.done",
                    "response.audio_transcript.done",
                }:
                    if event.get("response_id") != handle.response_id:
                        return
                    if self._normalized(
                        event.get("transcript", "")
                    ) != self._normalized(handle.spoken):
                        raise ValueError("Output did not match server text")
                    handle.transcript_ok = True
                    await self._listening_if_drained(handle, session)
                    return
                if kind == "response.done":
                    response = event.get("response", {})
                    rid = response.get("id")
                    if rid not in handle.authorized:
                        raise ValueError("Unauthorized response completion")
                    await self._usage(handle, "response:" + rid, response.get("usage"))
                    if rid != handle.response_id:
                        return
                    if response.get("status") != "completed":
                        raise ValueError("Response incomplete")
                    handle.generation_done = True
                    await self._listening_if_drained(handle, session)
                    return
                if kind == "output_audio_buffer.stopped":
                    if (
                        event.get("response_id") == handle.response_id
                        and handle.response_id
                    ):
                        handle.drain_done = True
                        await self._listening_if_drained(handle, session)
                    return
                if kind == "input_audio_buffer.speech_started":
                    item = event.get("item_id")
                    if item == handle.speech_item:
                        return  # Duplicate starts must not overwrite captured context.
                    if (
                        session.state == "listening"
                        and not session.muted
                        and handle.speech_item is None
                        and isinstance(item, str)
                        and item not in handle.seen
                    ):
                        handle.speech_item = item
                        handle.visible_on_speech = session.prompt_visible
                        handle.prompt_on_speech = coach.current_prompt(session).id
                        handle.epoch_on_speech = handle.epoch
                        handle.speech_since = time.monotonic()
                        handle.listening_since = handle.speech_since
                    elif isinstance(item, str):
                        handle.seen.add(item)
                    return
                if kind == "input_audio_buffer.committed":
                    item = event.get("item_id")
                    if (
                        (
                            session.state == "listening"
                            or (
                                session.state == "reviewing" and handle.commit_requested
                            )
                        )
                        and not session.muted
                        and item == handle.speech_item
                        and item not in handle.committed
                    ):
                        handle.committed.add(item)
                        handle.speech_since = None
                        if handle.asr_since is None:
                            handle.asr_since = time.monotonic()
                        if session.state == "listening":
                            await self._save(
                                owner,
                                coach.changed(
                                    session,
                                    state="reviewing",
                                    status_message="Confirming the sentence.",
                                ),
                            )
                    return
                if kind in {
                    "conversation.item.input_audio_transcription.completed",
                    "conversation.item.input_audio_transcription.failed",
                }:
                    item = event.get("item_id")
                    await self._usage(handle, "asr:" + str(item), event.get("usage"))
                    if (
                        session.state != "reviewing"
                        or session.muted
                        or item != handle.speech_item
                        or item not in handle.committed
                        or item in handle.seen
                        or handle.epoch_on_speech != handle.epoch
                        or handle.prompt_on_speech != coach.current_prompt(session).id
                    ):
                        return
                    handle.seen.add(item)
                    handle.asr_since = None
                    text = event.get("transcript", "")
                    if kind.endswith("failed") or not text.strip():
                        session = await self._save(
                            owner,
                            coach.changed(
                                session,
                                state="coach_speaking",
                                status_message="I could not confirm a complete sentence. Please try again.",
                            ),
                        )
                        await self._speak(
                            handle,
                            session.status_message + " " + coach.target_speech(session),
                        )
                        return
                    if not isinstance(text, str) or len(text) > 4000:
                        raise ValueError("Invalid transcript")
                    reviewing = await self._save(
                        owner,
                        coach.changed(
                            session,
                            state="reviewing",
                            status_message="Reviewing the wording.",
                        ),
                    )
                    captured = coach.changed(
                        reviewing, prompt_visible=handle.visible_on_speech
                    )
                    handle.evaluation = asyncio.create_task(
                        self._evaluate_completed(
                            handle, captured, text, item, handle.epoch
                        )
                    )
                    return handle.evaluation
            except Exception:
                await self._fail(handle)

    async def _terminate(self, owner, id, expected=None, deadline=False):
        if expected is not None and self._handles.get((owner, id)) is not expected:
            return
        handle = self._handles.pop((owner, id), None)
        if deadline:
            self._forget(owner, id)
        if not handle:
            return
        if handle.evaluation and handle.evaluation is not asyncio.current_task():
            handle.evaluation.cancel()
        if handle.task and handle.task is not asyncio.current_task():
            handle.task.cancel()
        confirmed = False
        try:
            confirmed = await self.provider.hangup(handle.connection.call_id) is True
        except Exception:
            pass  # Durable lease remains for watchdog retries when unconfirmed.
        finally:
            try:
                await invoke(
                    self.store.release_call,
                    owner,
                    id,
                    handle.lease_worker_id,
                    handle.connection.call_id,
                    confirmed,
                )
            except Exception:
                pass  # The existing durable lease remains due for reconciliation.
            finally:
                try:
                    await handle.connection.close()
                except Exception:
                    pass
        if deadline:
            # Exact physical hangup is initiated before any SQL reconciliation.
            try:
                latest = await self.get(owner, id)
                await self._save(owner, coach.finish(latest, failed=True))
            except Exception:
                pass

    async def close(self):
        self._closed = True
        if self._deadline_worker:
            self._deadline_worker.cancel()
            await asyncio.gather(self._deadline_worker, return_exceptions=True)
        for task in list(self._teardowns):
            task.cancel()
        await asyncio.gather(*self._teardowns, return_exceptions=True)
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        for owner, id in list(self._handles):
            async with self._lock(owner, id):
                try:
                    await self._save(owner, coach.finish(await self.get(owner, id)))
                except Exception:
                    pass
                await self._terminate(owner, id)
        for resource in (self.provider, self.store):
            close = getattr(resource, "close", None)
            if close:
                try:
                    await invoke(close)
                except Exception:
                    pass
        for owner, id in list(self._registry_deadlines):
            self._forget(owner, id)
