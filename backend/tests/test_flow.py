from fastapi.testclient import TestClient


def client_for(tmp_path):
    from app import create_app, Settings
    from store import Store

    app = create_app(
        Settings(
            _env_file=None,
            db_path=str(tmp_path / "db"),
            audio_temp_dir=str(tmp_path / "audio"),
            supabase_url="https://test.supabase.co",
            supabase_publishable_key="sb_publishable_test",
            openai_api_key="test",
        ),
        store=Store(str(tmp_path / "db")),
    )
    app.state.auth.verify = lambda token: {"sub": token}
    app.state.auth.require_confirmed = lambda token, subject: None
    return TestClient(app)


def test_profile_is_private_persistent_and_strict(tmp_path):
    c = client_for(tmp_path)
    a = {"Authorization": "Bearer alice"}
    b = {"Authorization": "Bearer bob"}
    assert c.get("/api/v1/profile", headers=a).json()["role"] == ""
    assert (
        c.put("/api/v1/profile", headers=a, json={"role": "Engineer"}).json()["role"]
        == "Engineer"
    )
    assert c.get("/api/v1/profile", headers=b).json()["role"] == ""
    assert (
        c.put("/api/v1/profile", headers=a, json={"user_id": "bob"}).status_code == 422
    )
    assert c.get("/api/v1/profile").status_code == 401


def test_session_generation_history_ownership_and_deletion(tmp_path):
    c = client_for(tmp_path)
    c.app.state.ai.scenario = lambda *args: {
        "context": "A customer call",
        "example_response": "I would clarify the issue.",
    }
    a = {"Authorization": "Bearer alice"}
    b = {"Authorization": "Bearer bob"}
    result = c.post(
        "/api/v1/sessions",
        headers=a,
        json={"scenario_id": "help-desk", "goal": "Be clear"},
    )
    assert result.status_code == 200, result.text
    session = result.json()
    assert session["context"] == "A customer call"
    assert (
        c.get("/api/v1/sessions", headers=a).json()["sessions"][0]["attempt_count"] == 0
    )
    assert c.get("/api/v1/sessions/" + session["id"], headers=b).status_code == 404
    assert c.delete("/api/v1/sessions/" + session["id"], headers=b).status_code == 404
    assert c.get("/api/v1/usage", headers=a).json()["daily_used"] == 1
    assert c.delete("/api/v1/sessions/" + session["id"], headers=a).status_code == 204
    assert c.get("/api/v1/sessions/" + session["id"], headers=a).status_code == 404
    assert c.delete("/api/v1/history", headers=a).status_code == 204
    with c.app.state.store.connect() as db:
        events = [
            row["action"]
            for row in db.execute(
                "SELECT action FROM audit WHERE user_id=?", ("alice",)
            )
        ]
    assert "session_deleted" in events
    assert "history_deleted" in events
