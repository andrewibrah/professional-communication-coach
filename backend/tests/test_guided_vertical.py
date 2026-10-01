"""Real PostgreSQL + real app/adapters; provider events and identity are TEST DOUBLES.

This verifies integrated contracts, not real speech, browser media, or live Auth.
"""

import asyncio
import json
import time
from uuid import uuid4

import httpx
import jwt
from fastapi.testclient import TestClient

from app import Settings, UnavailableStore, create_app
from guided_store import GuidedStore
from scripts.verify_postgres import disposable_database
from supabase_store import Store
from test_guided_postgres import A, B, rpc
from test_voice_provider import AUDIO_SDP
from voice_provider import VoiceProvider

TARGETS = [
    "I help customers understand technical issues.",
    "Let us work through the next step.",
    "I will confirm that the issue is resolved.",
]


def test_real_sql_app_provider_adapter_retry_advance_final_feedback_and_teardown():
    with disposable_database() as database:
        database.sql(f"INSERT INTO auth.users VALUES ('{A}'),('{B}');")
        sockets, hangups, responses = [], [], []

        def sql_transport(request):
            body = json.loads(request.content)
            if request.url.path.endswith("speechclear_guided_api"):
                result = rpc(
                    database,
                    body["p_action"],
                    body["p_owner"],
                    body["p_payload"],
                    check=False,
                )
                if result.returncode:
                    # Test-only PostgREST error projection for the exact SQL not-found.
                    assert "Guided session not found" in result.stderr, result.stderr
                    return httpx.Response(
                        404, json={"detail": "Synthetic SQL not found"}
                    )
                value = json.loads(result.stdout)
            else:
                value = json.loads(
                    database.rpc(
                        body["p_action"], body["p_owner"], body["p_payload"]
                    ).stdout
                )
            return httpx.Response(
                200,
                content=json.dumps(value),
                headers={"Content-Type": "application/json"},
            )

        class SidebandDouble:
            def __init__(self):
                self.queue = asyncio.Queue()
                self.closed = False
                self.count = 0

            async def send(self, text):
                event = json.loads(text)
                if event["type"] == "session.update":
                    await self.put(
                        {"type": "session.updated", "session": event["session"]}
                    )
                elif event["type"] == "response.create":
                    self.count += 1
                    response_id = "resp_test_" + str(self.count)
                    response = event["response"]
                    spoken = response["instructions"].split(
                        "Read exactly the following text, with no additions: ", 1
                    )[1]
                    responses.append(spoken)
                    await self.put(
                        {
                            "type": "response.created",
                            "response": {
                                "id": response_id,
                                "metadata": response["metadata"],
                            },
                        }
                    )
                    await self.put(
                        {
                            "type": "response.output_audio_transcript.done",
                            "response_id": response_id,
                            "transcript": spoken,
                        }
                    )
                    await self.put(
                        {
                            "type": "response.done",
                            "response": {
                                "id": response_id,
                                "status": "completed",
                                "usage": {"total_tokens": 10},
                            },
                        }
                    )
                    await self.put(
                        {
                            "type": "output_audio_buffer.stopped",
                            "response_id": response_id,
                        }
                    )

            async def put(self, event):
                await self.queue.put(json.dumps(event))

            async def recv(self):
                return await self.queue.get()

            async def close(self):
                self.closed = True

        async def websocket(url, **options):
            socket = SidebandDouble()
            sockets.append(socket)
            return socket

        evaluations = 0

        def provider_transport(request):
            nonlocal evaluations
            if request.url.path.endswith("/hangup"):
                hangups.append(request.url.path)
                return httpx.Response(200)
            if request.url.path == "/v1/realtime/calls":
                return httpx.Response(
                    201,
                    text=AUDIO_SDP,
                    headers={"Location": "/v1/realtime/calls/rtc_sql_test"},
                )
            body = json.loads(request.content)
            data = json.loads(body["input"][1]["content"])
            if body["text"]["format"]["name"] == "PromptBatch":
                value = {"sentences": TARGETS}
            else:
                evaluations += 1
                retry = evaluations == 1
                value = {
                    "prompt_id": data["prompt_id"],
                    "strength": None if retry else "The full wording matched.",
                    "priority_correction": "Keep the complete wording."
                    if retry
                    else None,
                    "corrected_example": data["target"] if retry else None,
                    "decision": "retry" if retry else "next",
                    "evidence_basis": "transcript",
                    "evidence_quote": data["transcript"],
                    "spoken_feedback": "Keep the complete wording."
                    if retry
                    else "The full wording matched.",
                }
            return httpx.Response(
                200,
                json={
                    "id": "resp_structured_" + str(evaluations),
                    "usage": {"total_tokens": 20},
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps(value)}
                            ],
                        }
                    ],
                },
            )

        settings = Settings(
            _env_file=None,
            supabase_url="https://qpheitaamyzcekzvbcox.supabase.co",
            supabase_publishable_key="sb_publishable_synthetic_test_only",
            supabase_secret_key="sb_secret_synthetic_test_only",
            openai_api_key="synthetic-provider-key",
        )
        regular = Store(settings, transport=httpx.MockTransport(sql_transport))
        guided = GuidedStore(settings, transport=httpx.MockTransport(sql_transport))
        provider = VoiceProvider(
            settings,
            http_transport=httpx.MockTransport(provider_transport),
            ws_connect=websocket,
        )
        application = create_app(
            settings,
            store=regular,
            storage=UnavailableStore(),
            guided_store=guided,
            voice_provider=provider,
        )
        token = jwt.encode(
            {"sub": A, "exp": time.time() + 3600},
            "synthetic-jwt-test-only-32-characters",
            algorithm="HS256",
        )
        application.state.auth.verify = lambda value: {
            "sub": A,
            "exp": time.time() + 3600,
        }
        application.state.auth.require_confirmed = lambda value, subject: None
        headers = {"Authorization": "Bearer " + token}

        with TestClient(application) as client:
            assert client.get("/api/v1/config").json()["guided_voice_available"] is True
            start = client.post(
                "/api/v1/guided-sessions",
                headers=headers,
                json={
                    "command_id": str(uuid4()),
                    "scenario_id": "help-desk",
                    "goal": "Clarity",
                    "context": "",
                    "prompt_visible": True,
                },
            )
            assert start.status_code == 200, start.json()
            session = start.json()
            path = "/api/v1/guided-sessions/" + session["id"]
            connected = client.post(
                path + "/connection",
                headers=headers,
                json={
                    "command_id": str(uuid4()),
                    "expected_revision": session["revision"],
                    "sdp": AUDIO_SDP,
                },
            )
            assert connected.status_code == 200, connected.json()

            def wait_state(state, min_turns=0):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    response = client.get(path, headers=headers)
                    assert response.status_code == 200, response.json()
                    value = response.json()
                    if value["state"] == state and len(value["turns"]) >= min_turns:
                        return value
                    assert value["state"] != "failed", value["status_message"]
                    time.sleep(0.1)
                raise AssertionError("Authoritative state did not reach " + state)

            session = wait_state("listening")
            first_prompt = session["prompts"][0]["id"]
            toggle = client.post(
                path + "/commands",
                headers=headers,
                json={
                    "command_id": str(uuid4()),
                    "expected_revision": session["revision"],
                    "prompt_id": first_prompt,
                    "action": "visibility",
                    "prompt_visible": False,
                },
            )
            assert toggle.status_code == 200
            assert toggle.json()["turns"] == []
            for attempt in range(4):
                session = wait_state("listening", attempt)
                item = "item_test_" + str(attempt)
                target = session["prompts"][session["prompt_index"]]["text"]
                text = "I help customers." if attempt == 0 else target
                client.portal.call(
                    sockets[0].put,
                    {"type": "input_audio_buffer.speech_started", "item_id": item},
                )
                client.portal.call(
                    sockets[0].put,
                    {"type": "input_audio_buffer.committed", "item_id": item},
                )
                client.portal.call(
                    sockets[0].put,
                    {
                        "type": "conversation.item.input_audio_transcription.completed",
                        "item_id": item,
                        "transcript": text,
                        "usage": {"total_tokens": 3},
                    },
                )
                if attempt == 0:
                    retry = wait_state("listening", 1)
                    assert (
                        retry["prompt_index"] == 0
                        and retry["prompts"][0]["id"] == first_prompt
                    )
                    assert retry["turns"][0]["prompt_visible"] is False
            finished = wait_state("finished")
            assert len(finished["turns"]) == 4
            assert (
                finished["recap"]["practiced_exercises"] == 3
                and finished["recap"]["completed_attempts"] == 4
            )
            assert responses[-1] == "The full wording matched. Practice complete."
            cleanup_deadline = time.monotonic() + 2
            while not sockets[0].closed and time.monotonic() < cleanup_deadline:
                time.sleep(0.01)
            assert (
                hangups == ["/v1/realtime/calls/rtc_sql_test/hangup"]
                and sockets[0].closed
            )
            assert "call_id" not in finished
            assert (
                database.scalar("SELECT count(*) FROM public.practice_sessions;") == "0"
            )
            assert database.scalar("SELECT count(*) FROM public.guided_turns;") == "4"
            assert client.delete(path, headers=headers).status_code == 204
            assert client.get(path, headers=headers).status_code == 404
            assert database.scalar("SELECT count(*) FROM public.guided_turns;") == "0"
            assert (
                database.scalar(
                    "SELECT count(*) FROM speechclear_private.guided_leases WHERE ended;"
                )
                == "1"
            )
