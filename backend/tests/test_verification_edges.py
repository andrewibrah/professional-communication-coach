import time
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException
from test_attempts import setup, audio


@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
def test_auth_rejects_bad_signature_and_missing_expiry(algorithm):
    from auth import Authenticator
    from app import Settings

    def key():
        return (
            rsa.generate_private_key(public_exponent=65537, key_size=2048)
            if algorithm == "RS256"
            else ec.generate_private_key(ec.SECP256R1())
        )

    trusted, attacker = key(), key()
    settings = Settings(
        _env_file=None,
        supabase_url="https://test.supabase.co",
        supabase_publishable_key="sb_publishable_test",
    )
    auth = Authenticator(settings)
    auth.jwks.get_signing_key_from_jwt = lambda token: SimpleNamespace(
        key=trusted.public_key()
    )
    claims = {
        "sub": "alice",
        "aud": "authenticated",
        "iss": settings.supabase_url + "/auth/v1",
        "exp": int(time.time()) + 60,
    }
    assert (
        auth.verify(jwt.encode(claims, trusted, algorithm=algorithm))["sub"] == "alice"
    )
    missing_exp = {k: v for k, v in claims.items() if k != "exp"}
    for token in [
        jwt.encode(claims, attacker, algorithm=algorithm),
        jwt.encode(missing_exp, trusted, algorithm=algorithm),
        "malformed",
    ]:
        with pytest.raises(HTTPException) as error:
            auth.verify(token)
        assert error.value.status_code == 401
        assert error.value.detail == "Invalid or expired access token"


def test_monthly_quota_blocks_ai_and_completed_replay_is_free(tmp_path):
    c, h, s = setup(tmp_path)
    c.app.state.settings.monthly_limit = 2
    url = "/api/v1/sessions/" + s["id"] + "/attempts"
    key = str(uuid4())
    payload = {"audio": ("a.wav", audio(), "audio/wav")}
    first = c.post(
        url,
        headers=h | {"Idempotency-Key": key},
        files=payload,
        data={"duration_seconds": "30"},
    )
    assert first.status_code == 200

    def forbidden(*args):
        pytest.fail("AI invoked after monthly quota exhausted")

    c.app.state.ai.transcribe = forbidden
    c.app.state.ai.scenario = forbidden
    assert (
        c.post(
            url,
            headers=h | {"Idempotency-Key": key},
            files=payload,
            data={"duration_seconds": "30"},
        ).json()
        == first.json()
    )
    assert (
        c.post(
            url,
            headers=h | {"Idempotency-Key": str(uuid4())},
            files=payload,
            data={"duration_seconds": "30"},
        ).status_code
        == 429
    )
    assert (
        c.post(
            "/api/v1/sessions",
            headers=h,
            json={"scenario_id": "help-desk", "goal": "Clear"},
        ).status_code
        == 429
    )
    assert c.get("/api/v1/usage", headers=h).json()["monthly_used"] == 2
    assert not list((tmp_path / "audio").glob("*"))


def test_provider_failure_is_safe_and_audio_is_deleted(tmp_path):
    c, h, s = setup(tmp_path)

    def fail(path):
        raise RuntimeError("provider secret and sensitive content")

    c.app.state.ai.transcribe = fail
    result = c.post(
        "/api/v1/sessions/" + s["id"] + "/attempts",
        headers=h | {"Idempotency-Key": str(uuid4())},
        files={"audio": ("a.wav", audio(), "audio/wav")},
        data={"duration_seconds": "30"},
    )
    assert result.status_code == 502
    assert result.json() == {
        "detail": "Audio processing failed; please try again later"
    }
    assert c.app.state.store.attempts("alice", s["id"]) == []
    assert not list((tmp_path / "audio").glob("*"))
