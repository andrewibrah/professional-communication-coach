"""Provider contract tests use HTTP/WebSocket doubles, never live credentials."""

import asyncio
import json
import gc
import weakref
import importlib
import importlib.util
from types import SimpleNamespace

import httpx
import pytest


def adapter():
    assert importlib.util.find_spec("voice_provider") is not None, (
        "Realtime provider adapter is not implemented"
    )
    return importlib.import_module("voice_provider")


def settings():
    return SimpleNamespace(
        openai_api_key="test-only-nonsecret-key",
        guided_voice_model="gpt-realtime",
        transcription_model="gpt-4o-mini-transcribe",
        openai_model="gpt-4.1-mini",
    )


def test_server_hangup_is_real_exact_call_request_not_token_expiry():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200)

    async def run():
        provider = adapter().VoiceProvider(
            settings(), http_transport=httpx.MockTransport(respond)
        )
        try:
            assert await provider.hangup("rtc_contract_test") is True
        finally:
            await provider.close()

    asyncio.run(run())
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert (
        str(requests[0].url)
        == "https://api.openai.com/v1/realtime/calls/rtc_contract_test/hangup"
    )
    assert requests[0].headers["authorization"] == "Bearer test-only-nonsecret-key"


AUDIO_SDP = "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=rtpmap:111 opus/48000/2\r\n"


@pytest.mark.parametrize(
    "sdp",
    [
        AUDIO_SDP + "m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n",
        AUDIO_SDP + "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
        AUDIO_SDP + "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n",
        AUDIO_SDP.replace("m=audio 9", "m=audio 0"),
        "invalid-sdp",
    ],
)
def test_non_audio_only_sdp_is_rejected_before_billable_provider_setup(sdp):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(500)

    async def run():
        provider = adapter().VoiceProvider(
            settings(), http_transport=httpx.MockTransport(respond)
        )
        try:
            with pytest.raises(ValueError, match="audio-only"):
                await provider.connect(sdp, "11111111-1111-4111-8111-111111111111")
        finally:
            await provider.close()

    asyncio.run(run())
    assert not requests


def test_audio_only_call_is_durable_before_trusted_sideband_configuration_and_media_answer():
    order, requests = [], []

    class Socket:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.closed = False
            self.sent = []

        async def send(self, text):
            event = json.loads(text)
            self.sent.append(event)
            if event["type"] == "session.update":
                order.append("configured")
                await self.queue.put(
                    json.dumps({"type": "session.updated", "session": event["session"]})
                )

        async def recv(self):
            return await self.queue.get()

        async def close(self):
            self.closed = True

    socket = Socket()

    async def ws_connect(url, **options):
        order.append("attached")
        assert url == "wss://api.openai.com/v1/realtime?call_id=rtc_contract_test"
        assert options["proxy"] is None and options["max_size"] <= 65536
        return socket

    def respond(request):
        requests.append(request)
        assert request.method == "POST" and request.url.path == "/v1/realtime/calls"
        assert b'name="sdp"' in request.content and b'name="session"' in request.content
        assert b'"create_response": false' in request.content
        return httpx.Response(
            201,
            text=AUDIO_SDP,
            headers={"Location": "/v1/realtime/calls/rtc_contract_test"},
        )

    async def persist(call_id):
        assert call_id == "rtc_contract_test"
        order.append("durable")

    async def run():
        provider = adapter().VoiceProvider(
            settings(),
            http_transport=httpx.MockTransport(respond),
            ws_connect=ws_connect,
        )
        try:
            connection = await provider.connect(
                AUDIO_SDP, "11111111-1111-4111-8111-111111111111", on_created=persist
            )
            assert (
                connection.sdp == AUDIO_SDP
                and connection.call_id == "rtc_contract_test"
            )
            assert connection.session_config == provider.session_config()
            await connection.send({"type": "input_audio_buffer.clear"})
            assert socket.sent[-1] == {"type": "input_audio_buffer.clear"}
            await socket.queue.put(
                json.dumps(
                    {"type": "input_audio_buffer.committed", "item_id": "item_test"}
                )
            )
            events = connection.events()
            assert await anext(events) == {
                "type": "input_audio_buffer.committed",
                "item_id": "item_test",
            }
            await events.aclose()
            await connection.close()
            reference = weakref.ref(connection)
            del connection
            gc.collect()
            assert reference() is None, (
                "Closed voice calls must not accumulate in provider memory"
            )
        finally:
            await provider.close()

    asyncio.run(run())
    assert order == ["durable", "attached", "configured"] and socket.closed
    assert len(requests) == 1


def test_structured_prompt_generation_and_short_transcript_feedback_are_real_provider_requests():
    prompt_id = "33333333-3333-4333-8333-333333333333"
    sentences = [
        "I explain technical issues clearly.",
        "Let us work through the next step.",
        "I will confirm the issue is resolved.",
    ]
    feedback = {
        "prompt_id": prompt_id,
        "strength": "The wording matched.",
        "priority_correction": None,
        "corrected_example": None,
        "decision": "next",
        "evidence_basis": "transcript",
        "evidence_quote": "I explain technical issues",
        "spoken_feedback": "The wording matched. Next sentence.",
    }
    bodies = []

    def respond(request):
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        bodies.append(body)
        result = {"sentences": sentences} if len(bodies) == 1 else feedback
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(result)}
                        ],
                    }
                ]
            },
        )

    async def run():
        provider = adapter().VoiceProvider(
            settings(), http_transport=httpx.MockTransport(respond)
        )
        try:
            assert (
                await provider.generate(
                    {"id": "help-desk", "title": "Help desk"}, "Be clear", "", {}
                )
                == sentences
            )
            assert (
                await provider.evaluate(prompt_id, sentences[0], sentences[0])
                == feedback
            )
        finally:
            await provider.close()

    asyncio.run(run())
    assert len(bodies) == 2
    assert all(
        b["store"] is False
        and b["text"]["format"]["strict"] is True
        and b["max_output_tokens"] <= 800
        for b in bodies
    )


def test_failed_sideband_cleanup_cannot_skip_server_hangup():
    paths = []

    class BrokenSocket:
        async def send(self, text):
            self.session = json.loads(text)["session"] | {
                "instructions": "unapproved configuration"
            }

        async def recv(self):
            return json.dumps({"type": "session.updated", "session": self.session})

        async def close(self):
            raise RuntimeError("Synthetic close failure")

    async def websocket(url, **options):
        return BrokenSocket()

    def respond(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/hangup"):
            return httpx.Response(200)
        return httpx.Response(
            201,
            text=AUDIO_SDP,
            headers={"Location": "/v1/realtime/calls/rtc_cleanup_test"},
        )

    async def run():
        provider = adapter().VoiceProvider(
            settings(),
            http_transport=httpx.MockTransport(respond),
            ws_connect=websocket,
        )
        try:
            with pytest.raises(ValueError, match="configuration not confirmed"):
                await provider.connect(
                    AUDIO_SDP, "11111111-1111-4111-8111-111111111111"
                )
        finally:
            await provider.close()

    asyncio.run(run())
    assert paths == ["/v1/realtime/calls", "/v1/realtime/calls/rtc_cleanup_test/hangup"]


def test_structured_usage_is_observed_before_invalid_output_is_rejected():
    receipts = []

    async def record_usage(response_id, tokens):
        receipts.append((response_id, tokens))

    def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "resp_usage_test",
                "usage": {"total_tokens": 23},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": '{"sentences": []}'}
                        ],
                    }
                ],
            },
        )

    async def run():
        provider = adapter().VoiceProvider(
            settings(), http_transport=httpx.MockTransport(respond)
        )
        try:
            with pytest.raises(ValueError):
                await provider.generate(
                    {"id": "help-desk"}, "Clarity", "", {}, on_usage=record_usage
                )
        finally:
            await provider.close()

    asyncio.run(run())
    assert receipts == [("resp_usage_test", 23)]
