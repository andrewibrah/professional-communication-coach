"""Durable spending proofs: actual disposable SQL, synthetic provider only."""

import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException
from scripts.verify_postgres import disposable_database
from test_guided_postgres import A, B, S, W, rpc
from test_guided_runtime import ProviderDouble, RegularDouble, setup_runtime
from test_guided_store import store


@pytest.fixture
def database():
    with disposable_database() as db:
        db.sql(f"INSERT INTO auth.users VALUES ('{A}'),('{B}');")
        yield db


def adapter(db):
    def handler(request):
        body = json.loads(request.content)
        result = rpc(
            db, body["p_action"], body["p_owner"], body["p_payload"], check=False
        )
        if result.returncode:
            status = (
                429 if "limit" in result.stderr or "quota" in result.stderr else 409
            )
            return httpx.Response(status, json={"detail": "Synthetic SQL rejection"})
        return httpx.Response(
            200,
            content=json.dumps(json.loads(result.stdout)),
            headers={"Content-Type": "application/json"},
        )

    return store(handler)


def test_two_native_workers_claim_only_one_preparation_and_match_context(database):
    async def run():
        from guided_models import CreateInput
        from guided_runtime import GuidedRuntime

        entered, release = asyncio.Event(), asyncio.Event()

        class Provider(ProviderDouble):
            async def generate(self, *args, **kwargs):
                self.generated += 1
                entered.set()
                await release.wait()
                return ["One", "Two", "Three"]

        settings = setup_runtime()[0].settings
        provider = Provider()
        first = GuidedRuntime(settings, adapter(database), provider, RegularDouble())
        second = GuidedRuntime(settings, adapter(database), provider, RegularDouble())
        data = CreateInput(
            command_id=S,
            scenario_id="intro",
            goal="Clear",
            context="private ephemeral context",
            prompt_visible=True,
        )
        pending = asyncio.create_task(first.create(A, data, {}))
        await entered.wait()
        try:
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(second.create(A, data, {}), timeout=1)
            assert error.value.status_code == 409
        finally:
            release.set()
        saved = await pending
        assert (await second.create(A, data, {})) == saved
        with pytest.raises(HTTPException) as mismatch:
            await second.create(
                A, data.model_copy(update={"context": "different context"}), {}
            )
        assert mismatch.value.status_code == 409
        assert provider.generated == 1
        assert (
            database.scalar(
                "SELECT count(*) FROM speechclear_private.guided_reservations;"
            )
            == "1"
        )
        assert "private ephemeral context" not in database.scalar(
            "SELECT row_to_json(r) FROM speechclear_private.guided_reservations r;"
        )
        await first.close()
        await second.close()

    asyncio.run(run())


def test_text_usage_deduplicates_and_aggregates_with_all_voice_generations(database):
    from test_guided_postgres import reserve, T

    saved = reserve(database)
    assert (
        rpc(database, "text_usage", A, dict(id=S, response_id="resp-prep", tokens=100))
        is None
    )
    assert (
        rpc(database, "text_usage", A, dict(id=S, response_id="resp-prep", tokens=100))
        is None
    )
    with pytest.raises(AssertionError, match="conflict"):
        rpc(database, "text_usage", A, dict(id=S, response_id="resp-prep", tokens=101))
    for worker, tokens in [(W, 2000), (T, 3000)]:
        rpc(
            database,
            "claim_connection",
            A,
            dict(id=S, expected_revision=saved["revision"], worker_id=worker),
        )
        rpc(
            database,
            "attach",
            A,
            dict(id=S, worker_id=worker, call_id="call-" + worker),
        )
        rpc(database, "usage", A, dict(id=S, worker_id=worker, tokens=tokens))
        if worker == W:
            rpc(
                database,
                "release_call",
                A,
                dict(id=S, worker_id=worker, call_id="call-" + worker, confirmed=True),
            )
    rpc(database, "text_usage", A, dict(id=S, response_id="resp-eval", tokens=900))
    assert (
        database.scalar(
            "SELECT text_tokens FROM speechclear_private.guided_reservations;"
        )
        == "1000"
    )
    due = rpc(database, "watchdog", None)
    assert [item["worker_id"] for item in due] == [T]
    assert rpc(database, "get", A, {"id": S})["state"] == "failed"
    for role in ("anon", "authenticated"):
        assert rpc(
            database,
            "text_usage",
            A,
            dict(id=S, response_id="forged", tokens=1),
            role=role,
            check=False,
        ).returncode


@pytest.mark.parametrize("invalid_output", [False, True])
def test_runtime_accounts_invalid_text_response_before_failure_and_hangup(
    database, invalid_output
):
    async def run():
        from guided_models import CreateInput, ConnectionInput
        from guided_runtime import GuidedRuntime
        from uuid import uuid4

        class Provider(ProviderDouble):
            async def generate(self, *args, on_usage=None):
                await on_usage("resp-prep", 1000)
                return ["One", "Two", "Three"]

            async def evaluate(self, prompt_id, target, transcript, on_usage=None):
                from test_guided_models import feedback

                await on_usage("resp-invalid", 5000)
                if invalid_output:
                    raise ValueError("Synthetic invalid provider output")
                return feedback(
                    prompt_id=prompt_id,
                    evidence_quote=None,
                    strength=None,
                    evidence_basis="uncertain",
                    decision="clarify",
                )

        provider = Provider()
        runtime = GuidedRuntime(
            setup_runtime()[0].settings, adapter(database), provider, RegularDouble()
        )
        saved = await runtime.create(
            A,
            CreateInput(
                command_id=S,
                scenario_id="intro",
                goal="Clear",
                context="",
                prompt_visible=True,
            ),
            {},
        )
        await runtime.connect(
            A,
            S,
            ConnectionInput(
                command_id=str(uuid4()), expected_revision=saved.revision, sdp="offer"
            ),
        )
        await playback(runtime, provider)
        await runtime.handle_event(
            A, S, dict(type="input_audio_buffer.speech_started", item_id="i")
        )
        await runtime.handle_event(
            A, S, dict(type="input_audio_buffer.committed", item_id="i")
        )
        await runtime.handle_event(
            A,
            S,
            dict(
                type="conversation.item.input_audio_transcription.completed",
                item_id="i",
                transcript="fragment",
            ),
        )
        assert provider.hung == ["call-0"]
        assert (await runtime.get(A, S)).state == "failed"
        assert (
            database.scalar(
                "SELECT text_tokens FROM speechclear_private.guided_reservations;"
            )
            == "6000"
        )
        assert (
            database.scalar(
                "SELECT count(*) FROM speechclear_private.guided_text_usage;"
            )
            == "2"
        )
        await runtime.close()

    asyncio.run(run())


async def playback(runtime, provider):
    request = [
        e for e in provider.connections[-1].sent if e["type"] == "response.create"
    ][-1]["response"]
    rid = "resp-" + request["metadata"]["guided_nonce"]
    for event in [
        dict(
            type="response.created", response=dict(id=rid, metadata=request["metadata"])
        ),
        dict(
            type="response.output_audio_transcript.done",
            response_id=rid,
            transcript=request["instructions"].split("no additions: ", 1)[1],
        ),
        dict(
            type="response.done",
            response=dict(id=rid, status="completed", usage={"total_tokens": 10}),
        ),
        dict(type="output_audio_buffer.stopped", response_id=rid),
    ]:
        await runtime.handle_event(A, S, event)


def test_evaluation_budget_survives_new_native_worker_and_uncertain_results(database):
    async def run():
        from guided_models import CreateInput, ConnectionInput, CommandInput
        from guided_runtime import GuidedRuntime
        from test_guided_models import feedback
        from uuid import uuid4

        class Provider(ProviderDouble):
            async def evaluate(self, prompt_id, target, transcript, **kwargs):
                self.evaluated.append(transcript)
                return feedback(
                    prompt_id=prompt_id,
                    evidence_basis="uncertain",
                    evidence_quote=None,
                    strength=None,
                    decision="clarify",
                )

        provider = Provider()
        settings = setup_runtime()[0].settings
        first = GuidedRuntime(settings, adapter(database), provider, RegularDouble())
        second = GuidedRuntime(settings, adapter(database), provider, RegularDouble())
        saved = await first.create(
            A,
            CreateInput(
                command_id=S,
                scenario_id="intro",
                goal="Clear",
                context="",
                prompt_visible=True,
            ),
            {},
        )
        await first.connect(
            A,
            S,
            ConnectionInput(
                command_id=str(uuid4()), expected_revision=saved.revision, sdp="offer"
            ),
        )
        runtime = first
        for index in range(13):
            if index == 6:
                current = await first.get(A, S)
                paused = await first.command(
                    A,
                    S,
                    CommandInput(
                        command_id=str(uuid4()),
                        expected_revision=current.revision,
                        action="pause",
                        prompt_id=None,
                    ),
                )
                await second.connect(
                    A,
                    S,
                    ConnectionInput(
                        command_id=str(uuid4()),
                        expected_revision=paused.revision,
                        sdp="offer",
                    ),
                )
                runtime = second
            await playback(runtime, provider)
            item = f"uncertain-{index}"
            await runtime.handle_event(
                A, S, dict(type="input_audio_buffer.speech_started", item_id=item)
            )
            await runtime.handle_event(
                A, S, dict(type="input_audio_buffer.committed", item_id=item)
            )
            await runtime.handle_event(
                A,
                S,
                dict(
                    type="conversation.item.input_audio_transcription.completed",
                    item_id=item,
                    transcript="fragment",
                ),
            )
        assert len(provider.evaluated) == 12
        ended = await second.get(A, S)
        assert ended.state == "failed" and not ended.turns
        assert (
            database.scalar(
                "SELECT evaluations FROM speechclear_private.guided_reservations;"
            )
            == "12"
        )
        await first.close()
        await second.close()

    asyncio.run(run())
