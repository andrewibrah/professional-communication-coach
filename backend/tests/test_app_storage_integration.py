import json
import os
import threading
import time
import pytest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from app import Settings, create_app

TARGET = "https://qpheitaamyzcekzvbcox.supabase.co"
OWNER = "11111111-1111-4111-8111-111111111111"


def configured(tmp_path):
    return Settings(
        _env_file=None,
        supabase_url=TARGET,
        supabase_secret_key="sb_secret_test_private",
        audio_temp_dir=str(tmp_path / "audio"),
        persistence_cutover_receipt=str(tmp_path / "receipt.json"),
        openai_api_key="test",
    )


def receipt(settings):
    path = settings.persistence_cutover_receipt
    with open(path, "w") as output:
        json.dump(
            {
                "target": TARGET,
                "project_ref": "qpheitaamyzcekzvbcox",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "backup_sha256": "a" * 64,
                "export_sha256": "b" * 64,
                "owner_mapping_verified": True,
                "counts_readback_verified": True,
                "cutover_ready": True,
            },
            output,
        )
    os.chmod(path, 0o600)


def authenticated(app):
    app.state.auth.verify = lambda token: {"sub": OWNER}
    app.state.auth.require_confirmed = lambda *args: None
    return TestClient(app), {"Authorization": "Bearer test"}


def test_missing_receipt_blocks_private_routes_without_calling_store(tmp_path):
    settings = configured(tmp_path)
    app = create_app(settings)
    app.state.store.profile = lambda *args: {"role": "must not be returned"}
    client, headers = authenticated(app)
    assert client.get("/api/v1/profile", headers=headers).status_code == 503
    assert client.get("/api/v1/health").json()["persistence_ready"] is False
    assert client.get("/api/v1/health").json()["audio_storage_ready"] is False


def test_protected_receipt_enables_snapshot_and_rechecks_permissions(tmp_path):
    settings = configured(tmp_path)
    receipt(settings)
    app = create_app(settings)
    app.state.store.session_detail = lambda *args: {"id": "snapshot", "attempts": []}
    app.state.store.session = lambda *args: (_ for _ in ()).throw(AssertionError())
    client, headers = authenticated(app)
    assert client.get("/api/v1/sessions/example", headers=headers).json() == {
        "id": "snapshot",
        "attempts": [],
    }
    os.chmod(settings.persistence_cutover_receipt, 0o644)
    assert client.get("/api/v1/sessions/example", headers=headers).status_code == 503


def test_default_attempt_route_dispatches_json_relay_and_rejects_multipart(
    tmp_path, monkeypatch
):
    import app as module

    settings = configured(tmp_path)
    receipt(settings)

    async def process(id, request, user, key):
        return {"upload_id": (await request.json())["upload_id"]}

    monkeypatch.setattr(module, "register_storage_routes", lambda *args: process)
    app = create_app(settings)
    app.state.store.require_active = lambda *args: None
    client, headers = authenticated(app)
    route = "/api/v1/sessions/example/attempts"
    assert client.post(route, headers=headers, json={"upload_id": "test"}).json() == {
        "upload_id": "test"
    }
    assert (
        client.post(
            route, headers=headers, files={"audio": ("test.webm", b"audio")}
        ).status_code
        == 415
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", "https://other.supabase.co"),
        ("project_ref", "other"),
        ("backup_sha256", "invalid"),
        ("export_sha256", "A" * 64),
        ("owner_mapping_verified", 1),
        ("counts_readback_verified", False),
        ("cutover_ready", False),
        ("verified_at", "2026-01-01"),
    ],
)
def test_receipt_rejects_unverified_or_wrong_target(tmp_path, field, value):
    from app import cutover_verified

    settings = configured(tmp_path)
    receipt(settings)
    with open(settings.persistence_cutover_receipt) as source:
        data = json.load(source)
    data[field] = value
    with open(settings.persistence_cutover_receipt, "w") as output:
        json.dump(data, output)
    assert not cutover_verified(settings)


def test_receipt_rejects_symlinks(tmp_path):
    from app import cutover_verified

    settings = configured(tmp_path)
    receipt(settings)
    original = tmp_path / "original.json"
    os.rename(settings.persistence_cutover_receipt, original)
    os.symlink(original, settings.persistence_cutover_receipt)
    assert not cutover_verified(settings)


def test_lifespan_retries_cleanup_and_closes_clients_and_scopes_local_sweep(
    tmp_path, monkeypatch, caplog
):
    import app as module

    settings = configured(tmp_path)
    folder = tmp_path / "audio"
    folder.mkdir(mode=0o755)
    stale = folder / "speechclear-stale.webm"
    foreign = folder / "foreign.webm"
    recent = folder / "speechclear-recent.webm"
    for path in (stale, foreign, recent):
        path.write_bytes(b"audio")
    for path in (stale, foreign):
        os.utime(path, (time.time() - 90000,) * 2)
    link = folder / "speechclear-link.webm"
    link.symlink_to(foreign)

    class Resource:
        closed = False

        def close(self):
            self.closed = True

    store, storage = Resource(), Resource()
    calls = []
    done = threading.Event()

    def cleanup(app):
        calls.append("sweep")
        if len(calls) == 1:
            raise RuntimeError("temporary cleanup failure")
        done.set()

    original_sleep = module.asyncio.sleep
    intervals = []

    async def sleep(seconds):
        intervals.append(seconds)
        if len(intervals) > 1:
            await original_sleep(3600)

    monkeypatch.setattr(module, "sweep", cleanup)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    app = create_app(settings, store=store, storage=storage)
    with TestClient(app):
        assert done.wait(3)
        assert folder.stat().st_mode & 0o777 == 0o700
        assert not stale.exists()
        assert foreign.exists() and recent.exists() and link.is_symlink()
    assert store.closed and storage.closed
    assert intervals[0] == 60
    assert "Cleanup deferred" in caplog.text
    assert "temporary cleanup failure" not in caplog.text


def test_raw_upload_body_cap_and_json_processing_cap(tmp_path, monkeypatch):
    import app as module
    from media import MAX_BYTES

    settings = configured(tmp_path)
    receipt(settings)

    async def process(id, request, user, key):
        return {"size": len(await request.body())}

    monkeypatch.setattr(module, "register_storage_routes", lambda *args: process)
    app = create_app(settings)
    app.state.store.require_active = lambda *args: None

    @app.put("/api/v1/attempt-uploads/{id}")
    async def raw(id, request: module.Request):
        return {"size": len(await request.body())}

    client, headers = authenticated(app)
    assert (
        client.put(
            "/api/v1/sessions/example/attempt-uploads/test", content=b"a" * 32769
        ).status_code
        != 413
    )
    assert (
        client.put("/api/v1/attempt-uploads/test", content=b"a" * 32769).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/attempt-uploads/test",
            headers={"Content-Length": str(MAX_BYTES + 1)},
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/v1/sessions/example/attempts",
            headers=headers | {"Content-Type": "application/json"},
            content=b"a" * 32769,
        ).status_code
        == 413
    )


def test_receipt_rejects_symlink_parent(tmp_path):
    from app import cutover_verified

    settings = configured(tmp_path)
    receipt(settings)
    link = tmp_path / "alias"
    link.symlink_to(tmp_path, target_is_directory=True)
    settings.persistence_cutover_receipt = str(link / "receipt.json")
    assert not cutover_verified(settings)


def test_local_sweep_rejects_unprotected_directory_and_symlink_parent(tmp_path):
    from app import sweep_local_audio

    folder = tmp_path / "audio"
    folder.mkdir(mode=0o755)
    old = folder / "speechclear-stale.webm"
    old.write_bytes(b"synthetic")
    os.utime(old, (time.time() - 90000,) * 2)
    sweep_local_audio(folder)
    assert old.exists()
    folder.chmod(0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(folder, target_is_directory=True)
    sweep_local_audio(alias)
    assert old.exists()
    sweep_local_audio(folder)
    assert not old.exists()


def test_real_create_app_upload_relay_and_processing(tmp_path):
    from types import SimpleNamespace
    from uuid import uuid4
    from test_storage_routes import (
        TestStore,
        TestStorage,
        OWNER as route_owner,
        SESSION,
    )
    from test_attempts import audio, report

    settings = configured(tmp_path)
    store, storage = TestStore(), TestStorage()
    store.require_active = lambda owner: None
    app = create_app(settings, store=store, storage=storage)
    app.state.auth.verify = lambda token: {"sub": route_owner}
    app.state.auth.require_confirmed = lambda *args: None
    app.state.ai = SimpleNamespace(
        transcribe=lambda path: "Hello", evaluate=lambda *args: report()
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer test"}
    root = "/api/v1/sessions/" + SESSION
    data = audio()
    response = client.post(
        root + "/attempt-uploads",
        headers=headers,
        json={
            "content_type": "audio/wav",
            "size_bytes": len(data),
            "duration_seconds": 30.0,
        },
    )
    assert response.status_code == 200, response.text
    upload_id = response.json()["upload_id"]
    assert (
        client.put(
            root + "/attempt-uploads/" + upload_id, headers=headers, content=data
        ).status_code
        == 204
    )
    result = client.post(
        root + "/attempts",
        headers=headers | {"Idempotency-Key": str(uuid4())},
        json={"upload_id": upload_id},
    )
    assert result.status_code == 200, result.text
    assert result.json()["report"]["overall_score"] == 80
    assert storage.objects == {} and store.rows[upload_id]["state"] == "deleted"
    assert list((tmp_path / "audio").iterdir()) == []
