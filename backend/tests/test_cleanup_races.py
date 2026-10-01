"""Deterministic local barriers; PostgreSQL is real, Storage is synthetic."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from test_postgres_schema import A, S, I, session

pytest_plugins = ["test_postgres_schema"]


class SQLStore:
    def __init__(self, db):
        self.db = db
        self.fail_intent = False

    def rpc(self, action, owner, payload):
        if self.fail_intent and action in ("upload_state", "cleanup_done"):
            raise RuntimeError("synthetic SQL unavailable")
        return json.loads(self.db.rpc(action, owner, payload).stdout)


class Objects:
    def __init__(self):
        self.objects = set()

    def delete(self, owner, metadata):
        self.objects.discard(metadata["id"])
        return True


def setup(db):
    db.rpc("save_session", A, {"data": session(S)})
    metadata = json.loads(
        db.rpc(
            "upload_create",
            A,
            {
                "session": S,
                "id": I,
                "content_type": "audio/wav",
                "suffix": ".wav",
                "size_bytes": 10,
                "duration_seconds": 30,
            },
        ).stdout
    )
    return SimpleNamespace(
        state=SimpleNamespace(store=SQLStore(db), storage=Objects())
    ), metadata


def test_stale_janitor_candidate_cannot_cancel_live_generation(db):
    from storage_routes import sweep

    app, metadata = setup(db)
    db.sql(
        "UPDATE object_metadata SET expires_at=clock_timestamp()-interval '1 second';"
    )
    candidate = app.state.store.rpc("cleanup_list", None, {})
    db.sql(
        "UPDATE object_metadata SET state='processing',updated_at=clock_timestamp();"
    )
    app.state.storage.objects.add(I)
    original = app.state.store.rpc
    app.state.store.rpc = lambda action, owner, payload: (
        candidate if action == "cleanup_list" else original(action, owner, payload)
    )
    assert sweep(app) == 0
    assert I in app.state.storage.objects
    assert db.scalar("SELECT state FROM object_metadata;") == "processing"


def test_late_writer_after_tombstone_is_repaired_on_next_sweep(db):
    from storage_routes import sweep

    app, metadata = setup(db)
    db.rpc("upload_state", A, {"id": I, "state": "cleanup_pending"})
    ready, release = Event(), Event()

    def delayed_write():
        ready.set()
        assert release.wait(5)
        app.state.storage.objects.add(I)

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(delayed_write)
        assert ready.wait(5)
        assert sweep(app) == 1
        assert db.scalar("SELECT state FROM object_metadata;") == "deleted"
        release.set()
        writer.result(timeout=5)
    assert I in app.state.storage.objects
    assert sweep(app) == 1
    assert I not in app.state.storage.objects


def test_compensation_deletes_even_when_sql_intent_fails(db):
    from storage_routes import cleanup

    app, metadata = setup(db)
    app.state.storage.objects.add(I)
    app.state.store.fail_intent = True
    with pytest.raises(RuntimeError):
        cleanup(app, A, metadata)
    assert I not in app.state.storage.objects


def test_relay_late_write_compensates_after_tombstone_and_sql_failure(
    db, tmp_path, monkeypatch
):
    import storage_routes
    from fastapi import FastAPI

    app, metadata = setup(db)
    api = FastAPI()
    api.state.store = app.state.store
    api.state.storage = app.state.storage
    ready, release = Event(), Event()

    def blocked_upload(owner, metadata, path):
        ready.set()
        assert release.wait(5)
        app.state.storage.objects.add(I)

    app.state.storage.upload = blocked_upload
    monkeypatch.setattr(storage_routes, "probe", lambda *args: 30)
    storage_routes.register_storage_routes(
        api,
        lambda: (A, "synthetic-token"),
        lambda user: None,
        SimpleNamespace(audio_temp_dir=str(tmp_path)),
    )
    endpoint = next(
        r.endpoint for r in api.routes if getattr(r, "methods", None) == {"PUT"}
    )

    class Request:
        async def stream(self):
            yield b"1234567890"

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(
            asyncio.run, endpoint(S, I, Request(), (A, "synthetic-token"))
        )
        try:
            assert ready.wait(5)
            db.rpc("upload_state", A, {"id": I, "state": "cleanup_pending"})
            assert storage_routes.sweep(app) == 1
            assert db.scalar("SELECT state FROM object_metadata;") == "deleted"
            app.state.store.fail_intent = True
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="synthetic SQL unavailable"):
            writer.result(timeout=5)
    assert I not in app.state.storage.objects
    assert not list(tmp_path.iterdir())


def test_relay_rechecks_deleted_claim_before_physical_write(db, tmp_path, monkeypatch):
    import storage_routes
    from fastapi import FastAPI

    app, metadata = setup(db)
    api = FastAPI()
    api.state.store, api.state.storage = app.state.store, app.state.storage

    def probe_then_delete(*args):
        db.rpc("delete", A, {"id": S})
        return 30

    monkeypatch.setattr(storage_routes, "probe", probe_then_delete)
    writes = []
    app.state.storage.upload = lambda *args: writes.append(args)
    storage_routes.register_storage_routes(
        api,
        lambda: (A, "synthetic-token"),
        lambda user: None,
        SimpleNamespace(audio_temp_dir=str(tmp_path)),
    )
    endpoint = next(
        r.endpoint for r in api.routes if getattr(r, "methods", None) == {"PUT"}
    )

    class Request:
        async def stream(self):
            yield b"1234567890"

    with pytest.raises(AssertionError, match="Upload not found"):
        asyncio.run(endpoint(S, I, Request(), (A, "synthetic-token")))
    assert not writes


def test_raw_stream_has_wall_clock_bound_and_runtime_prefix(tmp_path, monkeypatch):
    import storage_routes
    from test_storage_routes import client, SESSION

    monkeypatch.setattr(storage_routes, "RELAY_DRAIN_SECONDS", 0.02, raising=False)
    c = client(tmp_path)
    root = "/api/v1/sessions/" + SESSION
    auth = c.post(
        root + "/attempt-uploads",
        json={"content_type": "audio/wav", "size_bytes": 10, "duration_seconds": 30},
    ).json()
    endpoint = next(
        r.endpoint for r in c.app.routes if getattr(r, "methods", None) == {"PUT"}
    )
    seen = []

    class Request:
        async def stream(self):
            seen.extend(tmp_path.iterdir())
            await asyncio.sleep(1)
            yield b"1234567890"

    async def run():
        with pytest.raises(HTTPException) as error:
            await endpoint(
                SESSION,
                auth["upload_id"],
                Request(),
                (__import__("test_storage_routes").OWNER, "synthetic-token"),
            )
        assert error.value.status_code == 408

    asyncio.run(run())
    assert seen and seen[0].name.startswith("speechclear-")
    assert not list(tmp_path.iterdir())
