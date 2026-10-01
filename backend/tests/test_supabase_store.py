import importlib
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

OWNER = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"
KEY = "33333333-3333-4333-8333-333333333333"
URL = "https://qpheitaamyzcekzvbcox.supabase.co"


def settings(**changes):
    return SimpleNamespace(
        **(
            {
                "supabase_url": URL,
                "supabase_secret_key": "sb_secret_synthetic_test_only",
                "supabase_service_role_key": "",
            }
            | changes
        )
    )


def store(handler, **changes):
    module = importlib.import_module("supabase_store")
    return module.Store(settings(**changes), transport=httpx.MockTransport(handler))


def test_profile_uses_service_rpc_without_bearer_for_modern_secret():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    adapter = store(handler)
    assert adapter.profile(OWNER)["role"] == ""
    request = requests[0]
    assert str(request.url) == URL + "/rest/v1/rpc/speechclear_api"
    assert request.method == "POST"
    assert request.headers["apikey"] == "sb_secret_synthetic_test_only"
    assert "authorization" not in request.headers
    assert json.loads(request.content) == {
        "p_action": "profile",
        "p_owner": OWNER,
        "p_payload": {},
    }


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://qpheitaamyzcekzvbcox.supabase.co",
        URL + ".evil",
        URL + "/evil",
        URL + "?x=1",
        "https://user@qpheitaamyzcekzvbcox.supabase.co",
        URL + ":443",
        "https://other.supabase.co",
    ],
)
def test_configuration_rejects_wrong_target(url):
    with pytest.raises(ValueError, match="Invalid Supabase storage configuration"):
        store(lambda r: pytest.fail("network forbidden"), supabase_url=url)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "placeholder",
        "sb_secret_",
        "sb_secret_placeholder",
        "sb_publishable_test",
        "invalid",
    ],
)
def test_configuration_rejects_missing_or_unprivileged_key(key):
    with pytest.raises(ValueError, match="Invalid Supabase storage configuration"):
        store(lambda r: pytest.fail("network forbidden"), supabase_secret_key=key)


def test_legacy_service_role_key_uses_both_headers():
    import jwt

    key = jwt.encode(
        {"role": "service_role"},
        "synthetic-not-real-key-at-least-32-bytes",
        algorithm="HS256",
    )

    def handler(request):
        assert request.headers["apikey"] == key
        assert request.headers["authorization"] == "Bearer " + key
        return httpx.Response(200, json={})

    assert (
        store(handler, supabase_secret_key="", supabase_service_role_key=key).profile(
            OWNER
        )["role"]
        == ""
    )


@pytest.mark.parametrize("owner", ["bad", OWNER.upper().replace("1", "A"), "", None])
def test_invalid_owner_never_reaches_transport(owner):
    with pytest.raises(HTTPException) as error:
        store(lambda r: pytest.fail("network forbidden")).profile(owner)
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, 403),
        (404, 404),
        (409, 409),
        (429, 429),
        (422, 422),
        (401, 503),
        (500, 503),
        (302, 503),
    ],
)
def test_rpc_errors_do_not_echo_private_response(status, expected):
    with pytest.raises(HTTPException) as error:
        store(
            lambda r: httpx.Response(
                status, json={"message": "PRIVATE sb_secret_synthetic_test_only"}
            )
        ).profile(OWNER)
    assert error.value.status_code == expected
    assert "PRIVATE" not in error.value.detail
    assert "sb_secret" not in error.value.detail
    assert error.value.__cause__ is None


def test_transport_exception_is_sanitized():
    def handler(request):
        raise httpx.ConnectError(
            "PRIVATE sb_secret_synthetic_test_only", request=request
        )

    with pytest.raises(HTTPException) as error:
        store(handler).profile(OWNER)
    assert (error.value.status_code, error.value.detail) == (
        503,
        "Storage temporarily unavailable",
    )


@pytest.mark.parametrize("result", [{"role": 12}, {"unexpected": "PRIVATE"}, [], None])
def test_invalid_profile_response_fails_closed(result):
    with pytest.raises(HTTPException) as error:
        store(lambda r: httpx.Response(200, json=result)).profile(OWNER)
    assert error.value.status_code == 503


SESSION = {
    "id": SID,
    "scenario_id": "introduction",
    "goal": "Practice",
    "context": "Context",
    "question": "Question?",
    "example_response": "Example",
    "created_at": "2026-09-30T12:00:00+00:00",
}
REPORT = {
    "overall_score": 70,
    "category_scores": {
        "clarity": 70,
        "structure": 70,
        "conciseness": 70,
        "audience_fit": 70,
        "professional_tone": 70,
    },
    "communication_strengths": [],
    "transcript_evidence": [{"quote": "Hello", "observation": "Clear"}],
    "filler_words": [],
    "jargon_flags": [],
    "pacing_observations": [],
    "weak_phrasing": [],
    "missed_questions": [],
    "priority_improvement": "Practice",
    "suggested_practice_exercise": "Practice",
    "improved_answer": "Hello",
    "next_time_recommendation": "Practice",
}
ATTEMPT = {
    "id": KEY,
    "session_id": SID,
    "transcript": "Hello world",
    "duration_seconds": 31.0,
    "created_at": SESSION["created_at"],
    "report": REPORT,
}
USAGE = {"daily_used": 1, "daily_limit": 20, "monthly_used": 1, "monthly_limit": 200}


@pytest.mark.parametrize(
    "method,args,payload,result",
    [
        ("save_session", (SESSION,), {"data": SESSION}, SESSION),
        ("session", (SID,), {"id": SID}, SESSION),
        ("session_detail", (SID,), {"id": SID}, SESSION | {"attempts": [ATTEMPT]}),
        ("sessions", (), {}, [SESSION | {"attempt_count": 1, "latest_score": 70}]),
        ("attempts", (SID,), {"id": SID}, [ATTEMPT]),
        ("require_active", (), {}, None),
        ("reserve", (20, 200), {"daily": 20, "monthly": 200}, None),
        ("usage", (20, 200), {"daily": 20, "monthly": 200}, USAGE),
        (
            "begin_attempt",
            (SID, KEY, 20, 200),
            {"session": SID, "key": KEY, "daily": 20, "monthly": 200},
            None,
        ),
        (
            "begin_attempt",
            (SID, KEY, 20, 200),
            {"session": SID, "key": KEY, "daily": 20, "monthly": 200},
            ATTEMPT,
        ),
        ("finish_attempt", (KEY, ATTEMPT), {"key": KEY, "attempt": ATTEMPT}, ATTEMPT),
        ("fail_attempt", (KEY,), {"key": KEY}, None),
        ("delete", (SID,), {"id": SID}, None),
        ("delete", (), {}, None),
        ("suspend", (True,), {"value": True}, None),
    ],
)
def test_store_methods_match_jsonb_contract(method, args, payload, result):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, content=json.dumps(result))

    assert getattr(store(handler), method)(OWNER, *args) == result
    assert calls == [{"p_action": method, "p_owner": OWNER, "p_payload": payload}]


@pytest.mark.parametrize(
    "method,args,result",
    [
        ("session", (SID,), SESSION | {"id": KEY}),
        ("session", (SID,), SESSION | {"goal": 123}),
        ("sessions", (), [SESSION | {"attempt_count": True, "latest_score": 70}]),
        (
            "session_detail",
            (SID,),
            SESSION | {"attempts": [ATTEMPT | {"session_id": KEY}]},
        ),
        ("attempts", (SID,), [ATTEMPT | {"report": REPORT | {"overall_score": 101}}]),
        ("attempts", (SID,), [ATTEMPT | {"transcript": "No matching evidence"}]),
        ("attempts", (SID,), [ATTEMPT | {"duration_seconds": float("inf")}]),
        ("usage", (20, 200), USAGE | {"daily_used": True}),
        ("usage", (20, 200), USAGE | {"daily_limit": 999}),
        ("require_active", (), {"unexpected": "private"}),
    ],
)
def test_invalid_response_is_sanitized(method, args, result):
    with pytest.raises(HTTPException) as error:
        getattr(
            store(lambda r: httpx.Response(200, content=json.dumps(result))), method
        )(OWNER, *args)
    assert error.value.status_code == 503
    assert error.value.detail == "Invalid storage response"


def test_invalid_attempt_is_rejected_before_write():
    with pytest.raises(HTTPException) as error:
        store(lambda r: pytest.fail("network forbidden")).finish_attempt(
            OWNER, KEY, ATTEMPT | {"report": REPORT | {"overall_score": 101}}
        )
    assert error.value.status_code == 422


def test_internal_storage_rpc_can_return_arbitrary_json():
    assert store(lambda r: httpx.Response(200, json={"status": "reserved"})).rpc(
        "storage_reserve", OWNER, {"session": SID}
    ) == {"status": "reserved"}


def test_usage_accepts_lower_server_enforced_limits():
    result = USAGE | {"daily_limit": 10, "monthly_limit": 100}
    assert (
        store(lambda r: httpx.Response(200, json=result)).usage(OWNER, 20, 200)
        == result
    )


def test_begin_attempt_accepts_optional_upload_binding():
    def handler(request):
        assert json.loads(request.content)["p_payload"]["upload_id"] == KEY
        return httpx.Response(200, content="null")

    assert store(handler).begin_attempt(OWNER, SID, KEY, 20, 200, upload_id=KEY) is None


def test_adapter_validates_actual_disposable_postgres_receipts():
    # Local SQL transport bridge: real transactional SQL, not live PostgREST/Auth.
    from scripts.verify_postgres import disposable_database

    with disposable_database() as db:
        db.sql(f"INSERT INTO auth.users(id) VALUES ('{OWNER}')")

        def handler(request):
            body = json.loads(request.content)
            result = db.rpc(body["p_action"], body["p_owner"], body["p_payload"])
            return httpx.Response(200, content=result.stdout.strip())

        adapter = store(handler)
        assert adapter.profile(OWNER, {"role": "Synthetic"})["role"] == "Synthetic"
        adapter.require_active(OWNER)
        adapter.reserve(OWNER, 20, 200)
        assert adapter.save_session(OWNER, SESSION) == SESSION
        assert adapter.session(OWNER, SID) == SESSION
        assert adapter.begin_attempt(OWNER, SID, KEY, 20, 200) is None
        assert adapter.finish_attempt(OWNER, KEY, ATTEMPT) == ATTEMPT
        assert adapter.begin_attempt(OWNER, SID, KEY, 20, 200) == ATTEMPT
        assert adapter.attempts(OWNER, SID) == [ATTEMPT]
        assert adapter.session_detail(OWNER, SID) == SESSION | {"attempts": [ATTEMPT]}
        assert adapter.sessions(OWNER) == [
            SESSION | {"attempt_count": 1, "latest_score": 70}
        ]
        assert adapter.usage(OWNER, 20, 200)["daily_used"] == 2
        adapter.suspend(OWNER, True)
        assert (
            db.scalar(f"SELECT suspended FROM public.controls WHERE user_id='{OWNER}'")
            == "t"
        )
        adapter.suspend(OWNER, False)
        adapter.delete(OWNER, SID)
        assert adapter.sessions(OWNER) == []
        assert db.scalar("SELECT count(*) FROM public.attempts") == "0"
