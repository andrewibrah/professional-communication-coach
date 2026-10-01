import time
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException


def test_asymmetric_auth_rejects_untrusted_claims():
    from auth import Authenticator
    from app import Settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = Settings(
        _env_file=None,
        supabase_url="https://project.supabase.co",
        supabase_publishable_key="sb_publishable_test",
    )
    auth = Authenticator(settings)
    auth.jwks.get_signing_key_from_jwt = lambda token: type(
        "Key", (), {"key": key.public_key()}
    )()
    claims = dict(
        sub="owner",
        exp=int(time.time()) + 60,
        iss=settings.supabase_url + "/auth/v1",
        aud="authenticated",
    )
    token = jwt.encode(claims, key, algorithm="RS256")
    assert auth.verify(token)["sub"] == "owner"
    for override in [dict(exp=0), dict(aud="evil"), dict(iss="evil"), dict(sub="")]:
        with pytest.raises(HTTPException) as error:
            auth.verify(jwt.encode(claims | override, key, algorithm="RS256"))
        assert error.value.status_code == 401
    with pytest.raises(HTTPException):
        auth.verify(jwt.encode(claims, "secret" * 8, algorithm="HS256"))


def test_email_confirmation_comes_from_auth_server_not_metadata():
    from auth import confirmed_user

    assert not confirmed_user(
        {"id": "owner", "user_metadata": {"email_verified": True}}, "owner"
    )
    assert not confirmed_user(
        {"id": "other", "email_confirmed_at": "2026-01-01"}, "owner"
    )
    assert confirmed_user({"id": "owner", "email_confirmed_at": "2026-01-01"}, "owner")
