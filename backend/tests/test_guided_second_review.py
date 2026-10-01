"""Second-review regressions; synthetic adapters and disposable SQL only."""

import asyncio
import time
from uuid import uuid4

import pytest
from fastapi import HTTPException
from test_guided_models import ID
from test_guided_runtime import OWNER, create_connected, setup_runtime


@pytest.mark.parametrize("deadline", ["heartbeat", "absolute", "auth"])
def test_local_deadline_guard_ignores_stalled_sql_and_other_hangup(deadline):
    async def run():
        runtime, store, provider, _ = setup_runtime()
        await create_connected(runtime)
        handle = runtime._handles[OWNER, ID]
        entered, blocked = asyncio.Event(), asyncio.Event()
        original_hangup = provider.hangup

        async def stalled_watchdog():
            entered.set()
            await blocked.wait()
            return []

        async def hangup(call_id):
            if call_id == "other-call":
                await blocked.wait()
            return await original_hangup(call_id)

        provider.hangup = hangup
        store.watchdog = stalled_watchdog
        # Startup must establish the local guard before waiting on SQL.
        startup = asyncio.create_task(runtime.start())
        await entered.wait()
        # Hold the business lock and a second physical teardown independently.
        from test_guided_runtime import ConnectionDouble

        other_id = str(uuid4())
        runtime._handles["other-owner", other_id] = type(handle)(
            "other-owner", other_id, ConnectionDouble("other-call"), str(uuid4())
        )
        other = asyncio.create_task(runtime._terminate("other-owner", other_id))
        lock = runtime._lock(OWNER, ID)
        await lock.acquire()
        if deadline == "heartbeat":
            handle.last_heartbeat = time.monotonic() - 21
        elif deadline == "absolute":
            handle.expires_at = time.time() - 1
        else:
            handle.auth_expires_at = time.time() - 1
        try:
            async with asyncio.timeout(0.8):
                while handle.connection.call_id not in provider.hung:
                    await asyncio.sleep(0.01)
            assert (OWNER, ID) not in runtime._handles
        finally:
            lock.release()
            blocked.set()
            await startup
            await other
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("retries", [0, 1, 2])
def test_server_retry_policy_bounds_every_prompt(retries):
    import guided_coach as coach
    from test_guided_models import feedback

    session = coach.new_session(ID, "intro", "Clear", True, max_retries=retries)
    session = coach.set_prompts(session, ["One", "Two", "Three"])
    for position in range(3):
        for attempt in range(retries + 1):
            session = coach.changed(session, state="listening")
            session = coach.complete_turn(
                session,
                feedback(prompt_id=coach.current_prompt(session).id, decision="retry"),
                "Please help me.",
                f"item-{position}-{attempt}",
            )
        if position < 2:
            assert session.prompt_index == position + 1
    assert session.state == "finished"
    assert len(session.turns) == 3 * (retries + 1)


def test_retry_setting_is_bounded_and_passed_to_new_session():
    from app import Settings
    from guided_models import CreateInput
    from pydantic import ValidationError

    for invalid in (-1, 3):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, guided_max_retries=invalid)

    async def run():
        runtime, _, _, _ = setup_runtime()
        runtime.settings.guided_max_retries = 0
        saved = await runtime.create(
            OWNER,
            CreateInput(
                command_id=ID,
                scenario_id="intro",
                goal="Clear",
                context="",
                prompt_visible=True,
            ),
            {},
        )
        assert saved.max_retries == 0
        await runtime.close()

    asyncio.run(run())


def test_missing_sessions_do_not_retain_locks_and_waiters_remain_serialized():
    async def run():
        runtime, _, _, _ = setup_runtime()
        for _ in range(500):
            with pytest.raises(HTTPException):
                await runtime.heartbeat(OWNER, str(uuid4()))
        assert len(runtime._locks) == 0
        entered, release = asyncio.Event(), asyncio.Event()
        order = []

        async def holder():
            async with runtime._lock(OWNER, ID):
                entered.set()
                await release.wait()
                order.append("holder")

        async def waiter():
            async with runtime._lock(OWNER, ID):
                order.append("waiter")

        task = asyncio.create_task(holder())
        await entered.wait()
        waiting = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        assert len(runtime._locks) == 1
        assert order == []
        release.set()
        await asyncio.gather(task, waiting)
        assert order == ["holder", "waiter"]
        assert len(runtime._locks) == 0
        await runtime.close()

    asyncio.run(run())


def test_setup_failure_on_fresh_worker_retains_only_expiring_registry():
    async def run():
        from guided_models import CreateInput, ConnectionInput

        runtime, store, provider, regular = setup_runtime()
        saved = await runtime.create(
            OWNER,
            CreateInput(
                command_id=ID,
                scenario_id="intro",
                goal="Clear",
                context="",
                prompt_visible=True,
            ),
            {},
        )
        fresh = type(runtime)(runtime.settings, store, provider, regular)

        async def unavailable(*args, **kwargs):
            raise HTTPException(503, "Synthetic outage")

        store.commit = unavailable
        with pytest.raises(HTTPException):
            await fresh.connect(
                OWNER,
                ID,
                ConnectionInput(
                    command_id=str(uuid4()),
                    expected_revision=saved.revision,
                    sdp="offer",
                ),
            )
        assert (OWNER, ID) in fresh._registry_deadlines
        await fresh.close()
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["finish", "delete", "expiry", "final_pause"])
def test_terminal_session_cleans_all_runtime_counters(operation):
    async def run():
        from test_guided_runtime import command, listening, final_pending

        runtime, _, provider, _ = setup_runtime()
        if operation == "final_pause":
            await final_pending(runtime, provider)
        else:
            await create_connected(runtime)
            await listening(runtime, provider)
        assert runtime._setups and runtime._tokens
        if operation == "finish":
            await command(runtime, "finish")
        elif operation == "final_pause":
            await command(runtime, "pause")
        elif operation == "delete":
            await runtime.delete(OWNER, ID)
        else:
            runtime._handles[OWNER, ID].last_heartbeat = time.monotonic() - 21
            await runtime.start()
            async with asyncio.timeout(1):
                while runtime._handles:
                    await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
        assert not runtime._tokens
        assert not runtime._setups
        assert not runtime._evaluations
        assert not runtime._paused
        await runtime.close()

    asyncio.run(run())
