"""Backend-only service RPC adapter; no local fallback or response-content logging."""

from datetime import datetime
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException
from pydantic import (
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from models import Profile, Report, Score, StrictModel

PROJECT_URL = "https://qpheitaamyzcekzvbcox.supabase.co"
ERRORS = {
    403: "Account suspended",
    404: "Session not found",
    409: "Request conflict",
    429: "AI quota reached",
    422: "Invalid storage request",
}


def canonical_uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Invalid storage identifier") from None
    return value


def validate(model, value, status=503):
    try:
        return (
            model.dump_python(model.validate_python(value, strict=True))
            if isinstance(model, TypeAdapter)
            else model.model_validate(value).model_dump()
        )
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(
            status,
            "Invalid storage request" if status == 422 else "Invalid storage response",
        ) from None


class SessionRecord(StrictModel):
    id: str
    scenario_id: str = Field(min_length=1, max_length=50)
    goal: str = Field(min_length=1, max_length=1000)
    context: str = Field(min_length=1, max_length=5000)
    question: str = Field(min_length=1, max_length=5000)
    example_response: str = Field(min_length=1, max_length=5000)
    created_at: str

    @field_validator("id")
    @classmethod
    def valid_id(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("Invalid identifier")
        return value

    @field_validator("created_at")
    @classmethod
    def valid_date(cls, value):
        date = datetime.fromisoformat(value)
        if date.tzinfo is None:
            raise ValueError("Timezone required")
        return value


class AttemptRecord(StrictModel):
    id: str
    session_id: str
    transcript: str = Field(min_length=1, max_length=100000)
    duration_seconds: float = Field(ge=29.85, le=180.15, allow_inf_nan=False)
    created_at: str
    report: Report

    _ids = field_validator("id", "session_id")(SessionRecord.valid_id.__func__)
    _date = field_validator("created_at")(SessionRecord.valid_date.__func__)

    @model_validator(mode="after")
    def evidence(self):
        if any(e.quote not in self.transcript for e in self.report.transcript_evidence):
            raise ValueError("Invalid evidence")
        return self


class SessionSummary(SessionRecord):
    attempt_count: int = Field(ge=0)
    latest_score: Score | None

    @model_validator(mode="after")
    def coherent(self):
        if (self.attempt_count == 0) != (self.latest_score is None):
            raise ValueError("Invalid summary")
        return self


class SessionDetail(SessionRecord):
    attempts: list[AttemptRecord]

    @model_validator(mode="after")
    def coherent(self):
        if any(a.session_id != self.id for a in self.attempts) or len(
            {a.id for a in self.attempts}
        ) != len(self.attempts):
            raise ValueError("Invalid snapshot")
        return self


class Usage(StrictModel):
    daily_used: int = Field(ge=0)
    monthly_used: int = Field(ge=0)
    daily_limit: int = Field(ge=1)
    monthly_limit: int = Field(ge=1)


def coherent(condition):
    if not condition:
        raise HTTPException(503, "Invalid storage response")


def limits(daily, monthly):
    if type(daily) is not int or type(monthly) is not int or daily < 1 or monthly < 1:
        raise HTTPException(422, "Invalid storage request")
    return {"daily": daily, "monthly": monthly}


class Store:
    def __init__(self, settings, transport=None):
        url = getattr(settings, "supabase_url", "")
        key = getattr(settings, "supabase_secret_key", "") or getattr(
            settings, "supabase_service_role_key", ""
        )
        valid = (
            isinstance(key, str)
            and key == key.strip()
            and "placeholder" not in key.lower()
        )
        modern = valid and key.startswith("sb_secret_") and len(key) > len("sb_secret_")
        legacy = False
        if valid and not modern:
            try:
                legacy = (
                    jwt.decode(key, options={"verify_signature": False}).get("role")
                    == "service_role"
                )
            except jwt.PyJWTError:
                pass
        if url != PROJECT_URL or not (modern or legacy):
            raise ValueError("Invalid Supabase storage configuration")
        headers = {"apikey": key}
        if legacy:
            headers["Authorization"] = "Bearer " + key
        self._client = httpx.Client(
            base_url=url,
            headers=headers,
            transport=transport,
            timeout=20,
            follow_redirects=False,
            trust_env=False,
        )

    def rpc(self, action, owner, payload):
        if owner is not None or action not in ("cleanup_list", "cleanup_done"):
            canonical_uuid(owner)
        if not isinstance(action, str) or not action or not isinstance(payload, dict):
            raise HTTPException(422, "Invalid storage request")
        try:
            response = self._client.post(
                "/rest/v1/rpc/speechclear_api",
                json={"p_action": action, "p_owner": owner, "p_payload": payload},
            )
        except (httpx.HTTPError, ValueError, TypeError):
            raise HTTPException(503, "Storage temporarily unavailable") from None
        if response.status_code != 200:
            status = response.status_code if response.status_code in ERRORS else 503
            raise HTTPException(
                status, ERRORS.get(status, "Storage temporarily unavailable")
            ) from None
        try:
            return response.json()
        except (ValueError, TypeError):
            raise HTTPException(503, "Invalid storage response") from None

    def profile(self, owner, data=None):
        payload = {} if data is None else {"data": validate(Profile, data, 422)}
        return validate(Profile, self.rpc("profile", owner, payload))

    def save_session(self, owner, data):
        data = validate(SessionRecord, data, 422)
        result = validate(
            SessionRecord, self.rpc("save_session", owner, {"data": data})
        )
        coherent(result == data)
        return result

    def session(self, owner, id):
        result = validate(
            SessionRecord, self.rpc("session", owner, {"id": canonical_uuid(id)})
        )
        coherent(result["id"] == id)
        return result

    def session_detail(self, owner, id):
        result = validate(
            SessionDetail, self.rpc("session_detail", owner, {"id": canonical_uuid(id)})
        )
        coherent(result["id"] == id)
        return result

    def sessions(self, owner):
        result = validate(
            TypeAdapter(list[SessionSummary]), self.rpc("sessions", owner, {})
        )
        coherent(len({s["id"] for s in result}) == len(result))
        return result

    def attempts(self, owner, id):
        result = validate(
            TypeAdapter(list[AttemptRecord]),
            self.rpc("attempts", owner, {"id": canonical_uuid(id)}),
        )
        coherent(
            all(a["session_id"] == id for a in result)
            and len({a["id"] for a in result}) == len(result)
        )
        return result

    def _void(self, action, owner, payload):
        coherent(self.rpc(action, owner, payload) is None)

    def require_active(self, owner):
        self._void("require_active", owner, {})

    def reserve(self, owner, daily, monthly):
        self._void("reserve", owner, limits(daily, monthly))

    def usage(self, owner, daily, monthly):
        result = validate(Usage, self.rpc("usage", owner, limits(daily, monthly)))
        coherent(
            result["daily_limit"] <= daily
            and result["monthly_limit"] <= monthly
            and result["daily_used"] <= result["monthly_used"]
        )
        return result

    def begin_attempt(self, owner, session, key, daily, monthly, upload_id=None):
        payload = dict(
            session=canonical_uuid(session),
            key=canonical_uuid(key),
            **limits(daily, monthly),
        )
        if upload_id is not None:
            payload["upload_id"] = canonical_uuid(upload_id)
        result = self.rpc("begin_attempt", owner, payload)
        if result is None:
            return None
        result = validate(AttemptRecord, result)
        coherent(result["session_id"] == session)
        return result

    def finish_attempt(self, owner, key, attempt):
        attempt = validate(AttemptRecord, attempt, 422)
        result = validate(
            AttemptRecord,
            self.rpc(
                "finish_attempt",
                owner,
                {"key": canonical_uuid(key), "attempt": attempt},
            ),
        )
        coherent(result == attempt)
        return result

    def fail_attempt(self, owner, key):
        self._void("fail_attempt", owner, {"key": canonical_uuid(key)})

    def delete(self, owner, id=None):
        self._void("delete", owner, {} if id is None else {"id": canonical_uuid(id)})

    def suspend(self, owner, value):
        if type(value) is not bool:
            raise HTTPException(422, "Invalid storage request")
        self._void("suspend", owner, {"value": value})
