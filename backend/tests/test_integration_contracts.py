import json
import pytest
from fastapi import HTTPException
from test_supabase_store import store
from test_postgres_schema import A, S, I, session

pytest_plugins = ["test_postgres_schema"]


def test_janitor_rpc_accepts_null_owner_only_for_cleanup():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return __import__("httpx").Response(200, json=[])

    adapter = store(handler)
    assert adapter.rpc("cleanup_list", None, {}) == []
    assert seen[0]["p_owner"] is None
    with pytest.raises(HTTPException):
        adapter.rpc("profile", None, {})


def test_upload_rpc_and_cleanup_receipts_include_transport_metadata(db):
    db.rpc("save_session", A, {"data": session(S)})
    payload = {
        "session": S,
        "id": I,
        "content_type": "audio/webm",
        "size_bytes": 10,
        "duration_seconds": 30,
        "suffix": ".webm",
    }
    created = json.loads(db.rpc("upload_create", A, payload).stdout)
    assert created["suffix"] == ".webm"
    db.rpc("upload_state", A, {"id": I, "state": "cleanup_pending"})
    rows = json.loads(db.rpc("cleanup_list", None, {}).stdout)
    assert rows[0]["suffix"] == ".webm"
    assert rows[0]["content_type"] == "audio/webm"
