import jwt
import httpx
from fastapi import HTTPException


def confirmed_user(data, subject):
    return data.get("id") == subject and bool(data.get("email_confirmed_at"))


class Authenticator:
    def __init__(self, settings):
        self.settings = settings
        self.issuer = settings.supabase_url.rstrip("/") + "/auth/v1"
        self.jwks = (
            jwt.PyJWKClient(self.issuer + "/.well-known/jwks.json", timeout=5)
            if settings.auth_configured
            else None
        )

    def verify(self, token):
        if not self.settings.auth_configured:
            raise HTTPException(503, "Authentication setup pending")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in ("RS256", "ES256"):
                raise ValueError("algorithm")
            claims = jwt.decode(
                token,
                self.jwks.get_signing_key_from_jwt(token).key,
                algorithms=["RS256", "ES256"],
                audience=self.settings.supabase_jwt_audience,
                issuer=self.issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
            if not isinstance(claims["sub"], str) or not claims["sub"].strip():
                raise ValueError("subject")
            return claims
        except Exception:
            raise HTTPException(401, "Invalid or expired access token") from None

    def require_confirmed(self, token, subject):
        try:
            response = httpx.get(
                self.issuer + "/user",
                headers={
                    "Authorization": "Bearer " + token,
                    "apikey": self.settings.supabase_publishable_key,
                },
                timeout=8,
            )
            response.raise_for_status()
            confirmed = confirmed_user(response.json(), subject)
        except Exception:
            raise HTTPException(503, "Unable to verify email status") from None
        if not confirmed:
            raise HTTPException(403, "Verify your email before using AI features")
