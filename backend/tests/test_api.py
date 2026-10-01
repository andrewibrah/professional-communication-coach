from fastapi.testclient import TestClient


def test_public_config_and_fail_closed(tmp_path):
    from app import create_app, Settings

    client = TestClient(
        create_app(Settings(_env_file=None, db_path=str(tmp_path / "db")))
    )
    assert client.get("/api/v1/health").json() == {
        "status": "ok",
        "storage": "supabase",
        "persistence_ready": False,
        "audio_storage_ready": False,
        "auth_configured": False,
    }
    config = client.get("/api/v1/config").json()
    assert set(config) == {
        "supabase_url",
        "supabase_publishable_key",
        "auth_configured",
        "ai_enabled",
        "min_recording_seconds",
        "max_recording_seconds",
        "max_upload_bytes",
        "guided_voice_available",
        "guided_max_seconds",
        "guided_unavailable_reason",
    }
    assert len(client.get("/api/v1/scenarios").json()["scenarios"]) == 6
    assert client.get("/api/v1/profile").status_code == 401
