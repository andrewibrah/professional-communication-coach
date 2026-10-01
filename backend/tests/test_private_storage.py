"""Storage HTTP boundary tests; actual remote identity tests remain separate."""

from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from fastapi import HTTPException

OWNER = str(uuid4())
OBJECT = str(uuid4())


def settings():
    return SimpleNamespace(
        supabase_url="https://qpheitaamyzcekzvbcox.supabase.co",
        supabase_secret_key="sb_secret_test_only",
        supabase_service_role_key="",
    )


def test_storage_ignores_inherited_proxies(monkeypatch):
    import private_storage

    captured = {}
    original = httpx.Client

    def factory(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setenv("HTTPS_PROXY", "http://localhost:1")
    monkeypatch.setattr(private_storage.httpx, "Client", factory)
    store = private_storage.PrivateStorage(
        settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    assert captured.get("trust_env") is False
    store.client.close()


@pytest.mark.parametrize(
    "key", ["not-a-jwt", "replace_with_key", "sb_secret_placeholder"]
)
def test_storage_rejects_unclassified_or_placeholder_credentials(key):
    from private_storage import PrivateStorage

    cfg = settings()
    cfg.supabase_secret_key = ""
    cfg.supabase_service_role_key = key
    with pytest.raises(ValueError):
        PrivateStorage(cfg)


def test_storage_rejects_anon_legacy_jwt():
    import jwt
    from private_storage import PrivateStorage

    cfg = settings()
    cfg.supabase_secret_key = ""
    cfg.supabase_service_role_key = jwt.encode(
        {"role": "anon"}, "synthetic-test-signing-key-at-least-32-bytes"
    )
    with pytest.raises(ValueError):
        PrivateStorage(cfg)


def test_download_runtime_prefix_private_folder_and_symlink_rejection(tmp_path):
    from private_storage import PrivateStorage

    store = PrivateStorage(
        settings(),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"controlled audio")
        ),
    )
    metadata = {
        "id": OBJECT,
        "user_id": OWNER,
        "bucket": "temporary-audio",
        "path": OWNER + "/" + OBJECT + "/response.webm",
        "suffix": ".webm",
        "content_type": "audio/webm",
    }
    path = store.download(OWNER, metadata, tmp_path / "audio")
    assert path.name.startswith("speechclear-")
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    (tmp_path / "link").symlink_to(path.parent)
    with pytest.raises(HTTPException):
        store.download(OWNER, metadata, tmp_path / "link")
    path.unlink()


def test_storage_transfer_enforces_total_iteration_deadline(tmp_path, monkeypatch):
    import private_storage
    from private_storage import PrivateStorage

    # The mock transport drains the actual upload iterator, not a fake result.
    ticks = iter([0, 121])
    monkeypatch.setattr(
        private_storage, "monotonic", lambda: next(ticks), raising=False
    )
    store = PrivateStorage(
        settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    path = tmp_path / "controlled.webm"
    path.write_bytes(b"controlled bytes")
    metadata = {
        "id": OBJECT,
        "user_id": OWNER,
        "bucket": "temporary-audio",
        "path": OWNER + "/" + OBJECT + "/response.webm",
        "suffix": ".webm",
        "content_type": "audio/webm",
    }
    with pytest.raises(HTTPException) as error:
        store.upload(OWNER, metadata, path)
    assert error.value.status_code == 503


def test_storage_upload_is_private_nonupserting_and_target_scoped(tmp_path):
    from private_storage import PrivateStorage

    received = []

    def handler(request):
        received.append(request)
        return httpx.Response(
            200,
            json={"Key": "temporary-audio/" + OWNER + "/" + OBJECT + "/response.webm"},
        )

    path = tmp_path / "audio.webm"
    path.write_bytes(b"controlled test bytes")
    store = PrivateStorage(settings(), transport=httpx.MockTransport(handler))
    store.upload(
        OWNER,
        {
            "id": OBJECT,
            "user_id": OWNER,
            "bucket": "temporary-audio",
            "path": OWNER + "/" + OBJECT + "/response.webm",
            "suffix": ".webm",
            "content_type": "audio/webm",
        },
        path,
    )
    request = received[0]
    assert request.url.host == "qpheitaamyzcekzvbcox.supabase.co"
    assert request.headers["x-upsert"] == "false"
    assert "authorization" not in request.headers
    assert request.content == path.read_bytes()


def test_storage_rejects_cross_owner_paths_before_network(tmp_path):
    from private_storage import PrivateStorage

    calls = []
    store = PrivateStorage(
        settings(), transport=httpx.MockTransport(lambda r: calls.append(r))
    )
    path = tmp_path / "audio.webm"
    path.write_bytes(b"audio")
    with pytest.raises(HTTPException) as error:
        store.upload(
            OWNER,
            {
                "id": OBJECT,
                "user_id": str(uuid4()),
                "bucket": "temporary-audio",
                "path": "other/" + OBJECT + "/response.webm",
                "suffix": ".webm",
                "content_type": "audio/webm",
            },
            path,
        )
    assert error.value.status_code == 404
    assert calls == []


def test_download_rejects_oversize_and_unlinks_partial_copy(tmp_path):
    from private_storage import PrivateStorage
    from media import MAX_BYTES

    store = PrivateStorage(
        settings(),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"x" * (MAX_BYTES + 1))
        ),
    )
    metadata = {
        "id": OBJECT,
        "user_id": OWNER,
        "bucket": "temporary-audio",
        "path": OWNER + "/" + OBJECT + "/response.webm",
        "suffix": ".webm",
        "content_type": "audio/webm",
    }
    with pytest.raises(HTTPException) as error:
        store.download(OWNER, metadata, tmp_path)
    assert error.value.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_delete_verifies_exact_object_absence_and_sanitizes_failure():
    from private_storage import PrivateStorage

    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "DELETE":
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"message": "not found"})

    store = PrivateStorage(settings(), transport=httpx.MockTransport(handler))
    metadata = {
        "id": OBJECT,
        "user_id": OWNER,
        "bucket": "temporary-audio",
        "path": OWNER + "/" + OBJECT + "/response.webm",
        "suffix": ".webm",
        "content_type": "audio/webm",
    }
    assert store.delete(OWNER, metadata) is True
    assert methods == ["DELETE", "GET"]
    failed = PrivateStorage(
        settings(),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(500, text="private backend details")
        ),
    )
    with pytest.raises(HTTPException) as error:
        failed.delete(OWNER, metadata)
    assert "private" not in error.value.detail


def test_cleanup_does_not_treat_generic_bad_request_as_object_absence():
    from private_storage import PrivateStorage

    def handler(request):
        if request.method == "DELETE":
            return httpx.Response(200, json=[])
        return httpx.Response(
            400, json={"error": "AccessDenied", "message": "Request denied"}
        )

    store = PrivateStorage(settings(), transport=httpx.MockTransport(handler))
    metadata = {
        "id": OBJECT,
        "user_id": OWNER,
        "bucket": "temporary-audio",
        "path": OWNER + "/" + OBJECT + "/response.webm",
        "suffix": ".webm",
        "content_type": "audio/webm",
    }
    with pytest.raises(HTTPException):
        store.delete(OWNER, metadata)
