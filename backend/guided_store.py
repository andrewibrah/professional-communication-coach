"""Dedicated service-only Guided Voice RPC client; no Recorded Practice coupling."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

import httpx
import jwt
from fastapi import HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

PROJECT_URL = "https://qpheitaamyzcekzvbcox.supabase.co"
ERRORS = {
    403: "Account suspended",
    404: "Session not found",
    409: "Request conflict",
    429: "AI quota reached",
    422: "Invalid storage request",
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Invalid identifier")
    return value


def date(value):
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("Timezone required")
    return value


class Prompt(Strict):
    id: str
    text: str = Field(min_length=1, max_length=400)
    exercise_type: Literal["repetition"]
    position: int = Field(ge=0, le=2)
    _id = field_validator("id")(uuid)


class Feedback(Strict):
    prompt_id: str
    strength: str | None = Field(max_length=400, min_length=1)
    priority_correction: str | None = Field(max_length=400, min_length=1)
    corrected_example: str | None = Field(max_length=400, min_length=1)
    decision: Literal["retry", "next", "simplify", "finish", "clarify"]
    evidence_basis: Literal["transcript", "uncertain"]
    evidence_quote: str | None = Field(max_length=400, min_length=1)
    spoken_feedback: str = Field(min_length=1, max_length=400)
    _id = field_validator("prompt_id")(uuid)


class Turn(Strict):
    id: str
    prompt_id: str
    provider_item_id: str = Field(min_length=1, max_length=200)
    attempt: int = Field(ge=1, le=3)
    transcript: str = Field(max_length=4000)
    feedback: Feedback
    prompt_visible: bool
    created_at: str
    _ids = field_validator("id", "prompt_id")(uuid)
    _date = field_validator("created_at")(date)

    @model_validator(mode="after")
    def coherent(self):
        f = self.feedback
        if f.prompt_id != self.prompt_id or (
            f.evidence_quote is not None and f.evidence_quote not in self.transcript
        ):
            raise ValueError("Invalid evidence")
        if f.evidence_basis == "uncertain" and any(
            x is not None
            for x in (f.evidence_quote, f.priority_correction, f.corrected_example)
        ):
            raise ValueError("Invalid uncertain feedback")
        if f.priority_correction is not None and f.evidence_quote is None:
            raise ValueError("Missing evidence")
        return self


class Recap(Strict):
    practiced_exercises: int = Field(ge=0, le=3)
    completed_attempts: int = Field(ge=0, le=9)
    focus: str = Field(min_length=1, max_length=400)
    next_practice: str = Field(min_length=1, max_length=400)


class DTO(Strict):
    id: str
    scenario_id: str = Field(min_length=1, max_length=50)
    goal: str = Field(min_length=1, max_length=1000)
    created_at: str
    expires_at: str
    state: Literal[
        "created",
        "connecting",
        "coach_speaking",
        "listening",
        "reviewing",
        "paused",
        "reconnecting",
        "finished",
        "failed",
    ]
    revision: int = Field(ge=0, le=2147483647)
    prompt_visible: bool
    muted: bool
    max_retries: int = Field(ge=0, le=2)
    prompts: list[Prompt] = Field(max_length=3)
    prompt_index: int = Field(ge=0, le=2)
    attempts_on_prompt: int = Field(ge=0, le=3)
    turns: list[Turn] = Field(max_length=9)
    recap: Recap | None
    status_message: str = Field(max_length=400)
    _id = field_validator("id")(uuid)
    _date = field_validator("created_at", "expires_at")(date)

    @model_validator(mode="after")
    def coherent(self):
        duration = (
            datetime.fromisoformat(self.expires_at)
            - datetime.fromisoformat(self.created_at)
        ).total_seconds()
        if not 0 < duration <= 600:
            raise ValueError("Invalid duration")
        ids = {p.id for p in self.prompts}
        if len(ids) != len(self.prompts) or [p.position for p in self.prompts] != list(
            range(len(self.prompts))
        ):
            raise ValueError("Invalid prompts")
        counts = {id: 0 for id in ids}
        if len({t.id for t in self.turns}) != len(self.turns) or len(
            {t.provider_item_id for t in self.turns}
        ) != len(self.turns):
            raise ValueError("Duplicate turns")
        for t in self.turns:
            if t.prompt_id not in counts:
                raise ValueError("Invalid prompt reference")
            counts[t.prompt_id] += 1
            if t.attempt != counts[t.prompt_id] or t.attempt > self.max_retries + 1:
                raise ValueError("Invalid attempt")
        if not self.prompts:
            if self.prompt_index or self.attempts_on_prompt:
                raise ValueError("Invalid empty progression")
        elif (
            self.prompt_index >= len(self.prompts)
            or counts[self.prompts[self.prompt_index].id] != self.attempts_on_prompt
        ):
            raise ValueError("Invalid progression")
        if self.recap is not None and (
            self.recap.completed_attempts != len(self.turns)
            or self.recap.practiced_exercises != len({t.prompt_id for t in self.turns})
        ):
            raise ValueError("Invalid recap")
        return self


class Lease(Strict):
    owner: str
    id: str
    worker_id: str
    call_id: str | None = Field(min_length=1, max_length=200)
    _ids = field_validator("owner", "id", "worker_id")(uuid)


def require(condition, status=422):
    if not condition:
        raise HTTPException(
            status,
            "Invalid storage request" if status == 422 else "Invalid storage response",
        )


def identifier(value):
    try:
        return uuid(value)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Invalid storage identifier") from None


def validate(model, value, status=503):
    try:
        return model.model_validate(value).model_dump()
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(
            status,
            "Invalid storage request" if status == 422 else "Invalid storage response",
        ) from None


def integer(value, lo=0, hi=2147483647):
    require(type(value) is int and lo <= value <= hi)
    return value


class GuidedStore:
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

    def _rpc(self, action, owner, payload):
        if owner is not None:
            identifier(owner)
        try:
            response = self._client.post(
                "/rest/v1/rpc/speechclear_guided_api",
                json=dict(p_action=action, p_owner=owner, p_payload=payload),
            )
        except (httpx.HTTPError, ValueError, TypeError, RuntimeError):
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

    def _dto(self, action, owner, payload, id):
        result = validate(DTO, self._rpc(action, identifier(owner), payload))
        require(result["id"] == id, 503)
        return result

    def reserve(
        self,
        owner,
        data,
        daily_seconds=1800,
        monthly_seconds=18000,
        max_seconds=300,
        request_fingerprint=None,
    ):
        data = validate(DTO, data, 422)
        require(
            data["state"] == "created"
            and data["revision"] == 0
            and not data["prompts"]
            and not data["turns"]
            and data["recap"] is None
        )
        payload = dict(
            data=data,
            daily_seconds=integer(daily_seconds, 1),
            monthly_seconds=integer(monthly_seconds, 1),
            max_seconds=integer(max_seconds, 1, 600),
        )
        if request_fingerprint is not None:
            require(
                isinstance(request_fingerprint, str)
                and re.fullmatch(r"[0-9a-f]{64}", request_fingerprint) is not None
            )
            payload["request_fingerprint"] = request_fingerprint
        result = self._dto("reserve", owner, payload, data["id"])
        immutable = ("id", "scenario_id", "goal", "max_retries")
        require(all(result[k] == data[k] for k in immutable), 503)
        if result["revision"] == 0:
            require(
                all(
                    result[k] == data[k]
                    for k in data
                    if k not in ("created_at", "expires_at")
                ),
                503,
            )
        require(
            (
                datetime.fromisoformat(result["expires_at"])
                - datetime.fromisoformat(result["created_at"])
            ).total_seconds()
            == max_seconds,
            503,
        )
        return result

    def get(self, owner, id):
        return self._dto("get", owner, dict(id=identifier(id)), id)

    def list(self, owner):
        result = self._rpc("list", identifier(owner), {})
        require(isinstance(result, list), 503)
        values = [validate(DTO, value) for value in result]
        require(len({v["id"] for v in values}) == len(values), 503)
        return values

    def commit(
        self,
        owner,
        id,
        expected_revision,
        data,
        command_id=None,
        request_fingerprint=None,
    ):
        data = validate(DTO, data, 422)
        payload = dict(
            id=identifier(id),
            expected_revision=integer(expected_revision, 0, 2147483646),
            data=data,
        )
        require(data["id"] == id and data["revision"] == expected_revision)
        if command_id is not None:
            payload["command_id"] = identifier(command_id)
        if request_fingerprint is not None:
            require(command_id is not None)
            require(
                isinstance(request_fingerprint, str)
                and re.fullmatch(r"[0-9a-f]{64}", request_fingerprint) is not None
            )
            payload["request_fingerprint"] = request_fingerprint
        result = self._dto("commit", owner, payload, id)
        require(result == data | {"revision": expected_revision + 1}, 503)
        return result

    def command_result(self, owner, id, command_id, request_fingerprint=None):
        payload = dict(id=identifier(id), command_id=identifier(command_id))
        if request_fingerprint is not None:
            require(
                isinstance(request_fingerprint, str)
                and re.fullmatch(r"[0-9a-f]{64}", request_fingerprint) is not None
            )
            payload["request_fingerprint"] = request_fingerprint
        result = self._rpc("command_result", identifier(owner), payload)
        if result is None:
            return None
        result = validate(DTO, result)
        require(result["id"] == id, 503)
        return result

    def close(self):
        self._client.close()

    def heartbeat(self, owner, id):
        return self._dto("heartbeat", owner, dict(id=identifier(id)), id)

    def _lease(self, action, owner, payload):
        result = validate(Lease, self._rpc(action, identifier(owner), payload))
        require(
            result["owner"] == owner
            and result["id"] == payload["id"]
            and result["worker_id"] == payload["worker_id"],
            503,
        )
        return result

    def claim_connection(self, owner, id, expected_revision, worker_id):
        return self._lease(
            "claim_connection",
            owner,
            dict(
                id=identifier(id),
                expected_revision=integer(expected_revision),
                worker_id=identifier(worker_id),
            ),
        )

    def claim_preparation(self, owner, id, worker_id):
        result = self._rpc(
            "claim_preparation",
            identifier(owner),
            dict(id=identifier(id), worker_id=identifier(worker_id)),
        )
        require(type(result) is bool, 503)
        return result

    def reserve_evaluation(self, owner, id, worker_id):
        self._void(
            "reserve_evaluation",
            owner,
            dict(id=identifier(id), worker_id=identifier(worker_id)),
        )

    def attach(self, owner, id, worker_id, call_id):
        require(isinstance(call_id, str) and 1 <= len(call_id) <= 200)
        result = self._lease(
            "attach",
            owner,
            dict(id=identifier(id), worker_id=identifier(worker_id), call_id=call_id),
        )
        require(result["call_id"] == call_id, 503)
        return result

    def _void(self, action, owner, payload):
        require(self._rpc(action, identifier(owner), payload) is None, 503)

    def release_call(self, owner, id, worker_id, call_id, confirmed):
        require(
            type(confirmed) is bool
            and isinstance(call_id, str)
            and 1 <= len(call_id) <= 200
        )
        self._void(
            "release_call",
            owner,
            dict(
                id=identifier(id),
                worker_id=identifier(worker_id),
                call_id=call_id,
                confirmed=confirmed,
            ),
        )

    def usage(self, owner, id, worker_id, tokens):
        self._void(
            "usage",
            owner,
            dict(
                id=identifier(id),
                worker_id=identifier(worker_id),
                tokens=integer(tokens),
            ),
        )

    def text_usage(self, owner, id, response_id, tokens):
        require(isinstance(response_id, str) and 1 <= len(response_id) <= 200)
        self._void(
            "text_usage",
            owner,
            dict(id=identifier(id), response_id=response_id, tokens=integer(tokens)),
        )

    def watchdog(self):
        result = self._rpc("watchdog", None, {})
        require(isinstance(result, list), 503)
        values = [validate(Lease, value) for value in result]
        require(
            all(v["call_id"] is not None for v in values)
            and len({(v["owner"], v["id"], v["worker_id"]) for v in values})
            == len(values)
            and len({v["call_id"] for v in values}) == len(values),
            503,
        )
        return values

    def delete(self, owner, id):
        self._void("delete", owner, dict(id=identifier(id)))

    def ready(self):
        try:
            value = self._rpc("metadata", None, {})
            return (
                type(value) is dict
                and value == {"schema": "guided_voice", "version": 1}
                and type(value.get("version")) is int
            )
        except HTTPException:
            return False
