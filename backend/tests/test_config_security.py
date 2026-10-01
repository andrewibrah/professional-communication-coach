import jwt
import pytest
from fastapi.testclient import TestClient
from app import Settings, create_app


@pytest.mark.parametrize(
    "key",
    [
        "sb_secret_not-for-the-browser",
        jwt.encode(
            {"role": "service_role"}, "test-only-signing-secret" * 2, algorithm="HS256"
        ),
        "not-a-recognized-public-key",
    ],
)
def test_privileged_or_unknown_key_is_not_published(tmp_path, key):
    client = TestClient(
        create_app(
            Settings(
                _env_file=None,
                db_path=str(tmp_path / "db"),
                supabase_url="https://project.supabase.co",
                supabase_publishable_key=key,
            )
        )
    )
    response = client.get("/api/v1/config")
    assert key not in response.text
    assert response.json()["supabase_publishable_key"] == ""
    assert response.json()["auth_configured"] is False
    assert (
        client.get(
            "/api/v1/profile", headers={"Authorization": "Bearer test"}
        ).status_code
        == 503
    )


@pytest.mark.parametrize(
    "key",
    [
        "sb_publishable_test",
        jwt.encode({"role": "anon"}, "test-only-signing-secret" * 2, algorithm="HS256"),
    ],
)
def test_recognized_public_key_is_published(tmp_path, key):
    client = TestClient(
        create_app(
            Settings(
                _env_file=None,
                db_path=str(tmp_path / "db"),
                supabase_url="https://project.supabase.co",
                supabase_publishable_key=key,
            )
        )
    )
    assert client.get("/api/v1/config").json()["supabase_publishable_key"] == key
    assert client.get("/api/v1/config").json()["auth_configured"] is True
