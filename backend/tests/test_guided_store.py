"""Guided adapter contract; synthetic transports, including real local SQL."""

import importlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from test_guided_postgres import A, B, C, S, W, initial, prompt, rpc

from scripts.verify_postgres import disposable_database

URL = "https://qpheitaamyzcekzvbcox.supabase.co"


def store(handler, **changes):
    settings = SimpleNamespace(
        **(
            dict(
                supabase_url=URL,
                supabase_secret_key="sb_secret_synthetic_test_only",
                supabase_service_role_key="",
            )
            | changes
        )
    )
    return importlib.import_module("guided_store").GuidedStore(
        settings, transport=httpx.MockTransport(handler)
    )


def test_fingerprint_optional_interface_validation_and_safe_conflict():
    calls = []
    candidate = initial() | {"state": "connecting", "prompts": [prompt()]}
    saved = candidate | {"revision": 1}

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["p_payload"].get("request_fingerprint") == "b" * 64:
            return httpx.Response(409, text="raw private provider and SQL diagnostic")
        return httpx.Response(200, json=saved)

    adapter = store(handler)
    assert adapter.commit(A, S, 0, candidate, C, request_fingerprint="a" * 64) == saved
    assert adapter.command_result(A, S, C, request_fingerprint="a" * 64) == saved
    assert all(c["p_payload"]["request_fingerprint"] == "a" * 64 for c in calls)
    for invalid in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, 123, True, {}):
        for invoke in (
            lambda: adapter.command_result(A, S, C, request_fingerprint=invalid),
            lambda: adapter.commit(A, S, 0, candidate, C, request_fingerprint=invalid),
        ):
            with pytest.raises(HTTPException) as error:
                invoke()
            assert error.value.status_code == 422
            assert error.value.detail == "Invalid storage request"
    assert len(calls) == 2
    with pytest.raises(HTTPException) as error:
        adapter.command_result(A, S, C, request_fingerprint="b" * 64)
    assert error.value.status_code == 409 and error.value.detail == "Request conflict"
    with pytest.raises(HTTPException) as error:
        adapter.commit(A, S, 0, candidate, request_fingerprint="a" * 64)
    assert error.value.status_code == 422
    adapter.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_handle",
        "wrong_id",
        "invalid_uuid",
        "naive_time",
        "noninteger_revision",
        "raw_error",
        "missing",
    ],
)
def test_command_receipt_response_validation_never_exposes_raw_diagnostics(mutation):
    value = initial() | {"revision": 1}
    if mutation == "extra_handle":
        value["call_id"] = "private_provider_handle"
    elif mutation == "wrong_id":
        value["id"] = W
    elif mutation == "invalid_uuid":
        value["id"] = "private malformed identifier"
    elif mutation == "naive_time":
        value["created_at"] = "2026-10-01T00:00:00"
    elif mutation == "noninteger_revision":
        value["revision"] = True
    elif mutation == "raw_error":
        value = {"message": "private SQL raw diagnostic"}
    elif mutation == "missing":
        value.pop("goal")
    adapter = store(lambda request: httpx.Response(200, json=value))
    with pytest.raises(HTTPException) as error:
        adapter.command_result(A, S, C, request_fingerprint="a" * 64)
    assert error.value.status_code == 503
    assert error.value.detail == "Invalid storage response"
    adapter.close()


def test_dedicated_adapter_accepts_actual_sql_snapshots_and_command_receipts():
    calls = []
    with disposable_database() as db:
        db.sql(f"INSERT INTO auth.users VALUES ('{A}'),('{B}');")

        def handler(request):
            assert str(request.url) == URL + "/rest/v1/rpc/speechclear_guided_api"
            assert request.headers["apikey"] == "sb_secret_synthetic_test_only"
            assert "authorization" not in request.headers
            body = json.loads(request.content)
            calls.append(body)
            result = rpc(db, body["p_action"], body["p_owner"], body["p_payload"])
            return httpx.Response(200, content=json.dumps(result))

        adapter = store(handler)
        saved = adapter.reserve(A, initial(), 1800, 18000, 300)
        assert adapter.get(A, S) == saved
        assert adapter.list(A) == [saved] and adapter.list(B) == []
        candidate = saved | {"state": "connecting", "prompts": [prompt()]}
        committed = adapter.commit(
            A, S, 0, candidate, command_id=C, request_fingerprint="a" * 64
        )
        assert committed == candidate | {"revision": 1}
        assert (
            adapter.command_result(A, S, C, request_fingerprint="a" * 64) == committed
        )
        assert adapter.command_result(A, S, W) is None
        assert (
            adapter.commit(
                A, S, 0, candidate, command_id=C, request_fingerprint="a" * 64
            )
            == committed
        )
        adapter.close()
        assert adapter._client.is_closed
        assert {c["p_action"] for c in calls} == {
            "reserve",
            "get",
            "list",
            "commit",
            "command_result",
        }


def test_lease_methods_validate_real_receipts_and_ownerless_readiness():
    with disposable_database() as db:
        db.sql(f"INSERT INTO auth.users VALUES ('{A}');")

        def handler(request):
            body = json.loads(request.content)
            return httpx.Response(
                200,
                content=json.dumps(
                    rpc(db, body["p_action"], body["p_owner"], body["p_payload"])
                ),
            )

        adapter = store(handler)
        assert adapter.ready() is True
        saved = adapter.reserve(A, initial(), 1800, 18000, 300)
        lease = adapter.claim_connection(A, S, 0, W)
        assert lease == dict(owner=A, id=S, worker_id=W, call_id=None)
        live = adapter.attach(A, S, W, "rtc_adapter")
        assert live == lease | {"call_id": "rtc_adapter"}
        assert adapter.heartbeat(A, S) == saved
        adapter.usage(A, S, W, 6000)
        assert adapter.watchdog() == [live]
        adapter.release_call(A, S, W, "rtc_adapter", False)
        assert adapter.watchdog() == [live]
        adapter.release_call(A, S, W, "rtc_adapter", True)
        assert adapter.watchdog() == []
        adapter.delete(A, S)
        assert adapter.list(A) == []
        adapter.close()


def test_reservation_replay_after_progress_accepts_authoritative_current_snapshot():
    with disposable_database() as db:
        db.sql(f"INSERT INTO auth.users VALUES ('{A}');")

        def handler(request):
            body = json.loads(request.content)
            return httpx.Response(
                200,
                content=json.dumps(
                    rpc(db, body["p_action"], body["p_owner"], body["p_payload"])
                ),
            )

        adapter = store(handler)
        saved = adapter.reserve(A, initial())
        updated = adapter.commit(
            A, S, 0, saved | {"state": "connecting", "prompts": [prompt()]}
        )
        assert adapter.reserve(A, initial()) == updated
        assert (
            db.scalar("SELECT count(*) FROM speechclear_private.guided_reservations;")
            == "1"
        )
        adapter.close()
