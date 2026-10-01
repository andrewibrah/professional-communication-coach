"""App integration with explicit test-only identity/store/provider boundaries."""

from fastapi.testclient import TestClient

from app import Settings, create_app


def test_guided_routes_registered_fail_closed_without_changing_recorded_contract():
    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:
        cfg = client.get("/api/v1/config").json()
        assert cfg.get("guided_voice_available") is False
        assert cfg["min_recording_seconds"] == 30
        assert cfg["max_recording_seconds"] == 180
        assert client.post("/api/v1/guided-sessions", json={}).status_code == 401
        assert client.get("/api/v1/guided-sessions").status_code == 401
        assert (
            client.post(
                "/api/v1/guided-sessions/11111111-1111-4111-8111-111111111111/connection",
                json={},
            ).status_code
            == 401
        )
        assert "openai_api_key" not in cfg and "supabase_secret_key" not in cfg
