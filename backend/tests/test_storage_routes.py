"""API relay tests with explicit fake persistence/provider; not live RLS proof."""

from uuid import uuid4
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from test_attempts import audio, report


OWNER = str(uuid4())
SESSION = str(uuid4())


class TestStore:
    __test__ = False

    def __init__(self):
        self.rows = {}
        self.ops = {}

    def rpc(self, action, owner, payload):
        if owner != OWNER:
            raise HTTPException(404, "Session not found")
        if action == "upload_create":
            if payload["session"] != SESSION:
                raise HTTPException(404, "Session not found")
            row = payload | {
                "user_id": owner,
                "path": owner + "/" + payload["id"] + "/response" + payload["suffix"],
                "bucket": "temporary-audio",
                "state": "authorized",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=5)
                ).isoformat(),
            }
            self.rows[row["id"]] = row
            return row
        row = self.rows[payload.get("id") or payload.get("upload_id")]
        if action == "upload_claim":
            if row["state"] != "authorized":
                raise HTTPException(409, "Upload authorization unavailable")
            row["state"] = "uploading"
        if action == "upload_write_check":
            if row["state"] != "uploading" or row["session"] != payload["session"]:
                raise HTTPException(409, "Upload authorization unavailable")
        if action == "upload_get":
            if row["session"] != payload["session"]:
                raise HTTPException(404, "Audio upload not found")
        if action == "upload_state":
            row["state"] = payload["state"]
        if action == "cleanup_done":
            row["state"] = "deleted"
        if action == "begin_attempt":
            if payload["key"] in self.ops:
                return self.ops[payload["key"]]
            if row["state"] != "uploaded":
                raise HTTPException(409, "Audio not uploaded")
            self.ops[payload["key"]] = None
        return None if action == "begin_attempt" else row

    def session(self, owner, id):
        return {"id": id, "question": "Greet", "context": "Call"}

    def profile(self, owner):
        return {}

    def finish_attempt(self, owner, key, result):
        self.ops[key] = result
        return result

    def fail_attempt(self, owner, key):
        self.ops.pop(key, None)


class TestStorage:
    __test__ = False

    def __init__(self):
        self.objects = {}
        self.downloads = 0

    def upload(self, owner, metadata, path):
        self.objects[metadata["id"]] = path.read_bytes()

    def download(self, owner, metadata, folder):
        self.downloads += 1
        from pathlib import Path

        path = Path(folder) / ("controlled-" + metadata["id"] + ".wav")
        path.write_bytes(self.objects[metadata["id"]])
        return path

    def delete(self, owner, metadata):
        self.objects.pop(metadata["id"], None)
        return True


def client(tmp_path):
    from storage_routes import register_storage_routes

    app = FastAPI()
    app.state.store = TestStore()
    app.state.storage = TestStorage()
    app.state.ai = SimpleNamespace(
        transcribe=lambda p: "Hello", evaluate=lambda *a: report()
    )
    cfg = SimpleNamespace(
        audio_temp_dir=str(tmp_path), daily_limit=20, monthly_limit=200
    )

    def user():
        return OWNER, "test-only-token"

    process = register_storage_routes(app, user, lambda u: None, cfg)

    @app.post("/api/v1/sessions/{id}/attempts")
    async def attempt(id: str, request: Request):
        return await process(id, request, user(), str(uuid4()))

    return TestClient(app)


def test_authorization_rejects_client_owner_and_has_five_minute_expiry(tmp_path):
    c = client(tmp_path)
    url = "/api/v1/sessions/" + SESSION + "/attempt-uploads"
    r = c.post(
        url,
        json={"content_type": "audio/wav", "size_bytes": 10, "duration_seconds": 30.0},
    )
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"upload_id", "expires_at"}
    expiry = datetime.fromisoformat(r.json()["expires_at"])
    assert 0 < (expiry - datetime.now(timezone.utc)).total_seconds() <= 300
    assert (
        c.post(
            url,
            json={
                "content_type": "audio/wav",
                "size_bytes": 10,
                "duration_seconds": 30.0,
                "user_id": str(uuid4()),
            },
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/sessions/" + str(uuid4()) + "/attempt-uploads",
            json={
                "content_type": "audio/wav",
                "size_bytes": 10,
                "duration_seconds": 30.0,
            },
        ).status_code
        == 404
    )


def test_private_upload_process_validates_wav_media_and_deletes_copies(tmp_path):
    c = client(tmp_path)
    root = "/api/v1/sessions/" + SESSION
    data = audio()
    auth = c.post(
        root + "/attempt-uploads",
        json={
            "content_type": "audio/wav",
            "size_bytes": len(data),
            "duration_seconds": 30.0,
        },
    ).json()
    upload_id = auth["upload_id"]
    assert (
        c.put(root + "/attempt-uploads/" + upload_id, content=data).status_code == 204
    )
    assert upload_id in c.app.state.storage.objects
    result = c.post(root + "/attempts", json={"upload_id": upload_id})
    assert result.status_code == 200, result.text
    assert result.json()["report"]["overall_score"] == 80
    assert c.app.state.storage.objects == {}
    assert list(tmp_path.iterdir()) == []
    assert c.app.state.store.rows[upload_id]["state"] == "deleted"


def test_actual_chromium_streaming_webm_survives_relay_and_processing(tmp_path):
    from pathlib import Path

    c = client(tmp_path)
    root = "/api/v1/sessions/" + SESSION
    data = (Path(__file__).parent / "fixtures/chromium-boundary.webm").read_bytes()
    auth = c.post(
        root + "/attempt-uploads",
        json={
            "content_type": "audio/webm;codecs=opus",
            "size_bytes": len(data),
            "duration_seconds": 30.0031,
        },
    ).json()
    assert (
        c.put(root + "/attempt-uploads/" + auth["upload_id"], content=data).status_code
        == 204
    )
    result = c.post(root + "/attempts", json={"upload_id": auth["upload_id"]})
    assert result.status_code == 200, result.text
    assert 29.85 <= result.json()["duration_seconds"] <= 30.15
    assert c.app.state.storage.objects == {}
    assert list(tmp_path.iterdir()) == []


def test_relay_malformed_media_cleans_authorization_and_local_file(tmp_path):
    c = client(tmp_path)
    root = "/api/v1/sessions/" + SESSION
    data = b"not audio"
    auth = c.post(
        root + "/attempt-uploads",
        json={
            "content_type": "audio/wav",
            "size_bytes": len(data),
            "duration_seconds": 30.0,
        },
    ).json()
    result = c.put(root + "/attempt-uploads/" + auth["upload_id"], content=data)
    assert result.status_code == 422
    assert c.app.state.storage.objects == {}
    assert list(tmp_path.iterdir()) == []
