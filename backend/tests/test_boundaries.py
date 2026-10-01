import asyncio
from uuid import uuid4
from test_attempts import setup, audio


def test_cross_owner_attempt_missing_key_and_deleted_history(tmp_path):
    c, h, s = setup(tmp_path)
    url = "/api/v1/sessions/" + s["id"] + "/attempts"
    payload = {"audio": ("a.wav", audio(), "audio/wav")}
    assert (
        c.post(
            url, headers=h, files=payload, data={"duration_seconds": "30"}
        ).status_code
        == 422
    )
    assert (
        c.post(
            url,
            headers={"Authorization": "Bearer bob", "Idempotency-Key": str(uuid4())},
            files=payload,
            data={"duration_seconds": "30"},
        ).status_code
        == 404
    )
    assert (
        c.post(
            url,
            headers=h | {"Idempotency-Key": str(uuid4())},
            files=payload,
            data={"duration_seconds": "30"},
        ).status_code
        == 200
    )
    assert (
        c.delete("/api/v1/history", headers={"Authorization": "Bearer bob"}).status_code
        == 204
    )
    assert c.get("/api/v1/sessions/" + s["id"], headers=h).status_code == 200
    assert c.delete("/api/v1/history", headers=h).status_code == 204
    with c.app.state.store.connect() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM attempts WHERE user_id=?", ("alice",)
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM operations WHERE user_id=?", ("alice",)
            ).fetchone()[0]
            == 0
        )
    assert c.get("/api/v1/usage", headers=h).json()["daily_used"] == 2


def test_chunked_oversize_stream_is_stopped_without_content_length(tmp_path):
    c, h, s = setup(tmp_path)

    async def request():
        sent = []
        chunks = 0

        async def receive():
            nonlocal chunks
            chunks += 1
            return {"type": "http.request", "body": b"x" * 65536, "more_body": True}

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/sessions/" + s["id"] + "/attempts",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "server": ("test", 80),
            "client": ("test", 1),
            "headers": [
                (b"authorization", b"Bearer alice"),
                (b"idempotency-key", str(uuid4()).encode()),
                (b"content-type", b"multipart/form-data; boundary=test"),
            ],
        }
        # Include an initial valid file part so parsing actually consumes the stream.
        original = receive
        first = True

        async def multipart_receive():
            nonlocal first
            if first:
                first = False
                return {
                    "type": "http.request",
                    "body": b'--test\r\nContent-Disposition: form-data; name="audio"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n',
                    "more_body": True,
                }
            return await original()

        await c.app(scope, multipart_receive, send)
        assert (
            next(m["status"] for m in sent if m["type"] == "http.response.start") == 413
        )
        assert chunks < 200

    asyncio.run(request())
