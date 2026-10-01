from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
from test_flow import client_for


def test_atomic_quota_reservations(tmp_path):
    from store import Store

    store = Store(str(tmp_path / "db"))

    def reserve(_):
        try:
            store.reserve("alice", 3, 5)
            return True
        except HTTPException as e:
            assert e.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(reserve, range(20))) == 3
    assert store.usage("alice", 3, 5)["daily_used"] == 3


def test_suspension_kill_switch_email_verification(tmp_path):
    c = client_for(tmp_path)
    h = {"Authorization": "Bearer alice"}
    body = {"scenario_id": "help-desk", "goal": "Clear"}
    c.app.state.settings.ai_enabled = False
    assert c.post("/api/v1/sessions", headers=h, json=body).status_code == 503
    c.app.state.settings.ai_enabled = True
    c.app.state.store.suspend("alice", True)
    assert c.post("/api/v1/sessions", headers=h, json=body).status_code == 403
    c.app.state.store.suspend("alice", False)

    def unconfirmed(*args):
        raise HTTPException(403, "Verify email")

    c.app.state.auth.require_confirmed = unconfirmed
    assert c.post("/api/v1/sessions", headers=h, json=body).status_code == 403
    assert c.get("/api/v1/usage", headers=h).json()["daily_used"] == 0


def test_body_bound_and_safe_validation_errors(tmp_path):
    c = client_for(tmp_path)
    response = c.put(
        "/api/v1/profile",
        headers={"Authorization": "Bearer alice"},
        json={"role": 123, "secret": "dont-reflect-me"},
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert "dont-reflect-me" not in response.text
    response = c.post(
        "/api/v1/sessions/x/attempts",
        headers={
            "Authorization": "Bearer alice",
            "Content-Type": "application/octet-stream",
        },
        content=b"x" * (12582912 + 65537),
    )
    assert response.status_code == 413


def test_per_user_and_ip_rate_limits(tmp_path):
    c = client_for(tmp_path)
    c.app.state.settings.user_rate_limit = 2
    assert (
        c.get("/api/v1/profile", headers={"Authorization": "Bearer alice"}).status_code
        == 200
    )
    assert (
        c.get("/api/v1/profile", headers={"Authorization": "Bearer alice"}).status_code
        == 200
    )
    assert (
        c.get("/api/v1/profile", headers={"Authorization": "Bearer alice"}).status_code
        == 429
    )
    c.app.state.settings.ip_rate_limit = 1
    assert c.get("/api/v1/health").status_code == 429
