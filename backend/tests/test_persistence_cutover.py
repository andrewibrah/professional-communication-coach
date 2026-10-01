from fastapi.testclient import TestClient
from app import Settings, create_app


def test_default_runtime_never_opens_sqlite_when_credentials_missing(tmp_path):
    path = tmp_path / "original.sqlite3"
    client = TestClient(create_app(Settings(_env_file=None, db_path=str(path))))
    assert client.get("/api/v1/health").json()["storage"] == "supabase"
    assert not path.exists()


def test_public_config_cannot_expose_modern_backend_secret(tmp_path):
    secret = "sb_secret_test_only_private"
    client = TestClient(
        create_app(
            Settings(
                _env_file=None,
                db_path=str(tmp_path / "db"),
                supabase_url="https://qpheitaamyzcekzvbcox.supabase.co",
                supabase_publishable_key="sb_publishable_test_only",
                supabase_secret_key=secret,
            )
        )
    )
    assert secret not in client.get("/api/v1/config").text
    assert not (tmp_path / "db").exists()
