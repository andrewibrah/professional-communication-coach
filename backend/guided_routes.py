"""Authenticated, bounded Guided Voice HTTP boundary; no client AI decisions."""

import json
import math
import jwt
from fastapi import Depends, HTTPException, Request, Response
from guided_models import (
    CreateInput,
    ConnectionInput,
    CommandInput,
    GuidedSession,
    ConnectionOutput,
    SessionCollection,
    canonical_uuid,
)
from guided_runtime import invoke

CAP = 32768


def canonical(value):
    try:
        return canonical_uuid(value)
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(422, "Invalid request fields") from None


def owner_of(user):
    if isinstance(user, str):
        return user
    if isinstance(user, (tuple, list)) and user and isinstance(user[0], str):
        return user[0]
    if isinstance(user, dict) and isinstance(user.get("sub"), str):
        return user["sub"]
    raise HTTPException(401, "Authentication required")


def verified_expiry(user):
    """Extract expiry only AFTER the supplied identity dependency verified JWT.

    Never store a bearer token. A connection keeps only its authorization deadline.
    Dictionary identities can provide verified claims directly.
    """
    if isinstance(user, dict):
        expires = user.get("exp")
    elif isinstance(user, (tuple, list)) and len(user) > 1:
        try:
            expires = jwt.decode(user[1], options={"verify_signature": False}).get(
                "exp"
            )
        except Exception:
            raise HTTPException(401, "Authentication required") from None
    else:
        return None
    if type(expires) not in {int, float} or not math.isfinite(expires):
        raise HTTPException(401, "Authentication required")
    return float(expires)


async def body(request, model=None):
    try:
        length = int(request.headers.get("content-length", "0"))
        if length < 0 or length > CAP:
            raise HTTPException(413, "Request body too large")
        content = bytearray()
        async for piece in request.stream():
            content.extend(piece)
            if len(content) > CAP:
                raise HTTPException(413, "Request body too large")

        # Reject duplicate JSON keys, not silently allow an overwritten authority field.
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate field")
                result[key] = value
            return result

        data = json.loads(content, object_pairs_hook=unique) if content else {}
        if model is None:
            if data != {}:
                raise ValueError("Empty request required")
            return None
        return model.model_validate(data)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Invalid request fields") from None


async def safe(awaitable):
    try:
        return await awaitable
    except HTTPException as error:
        status = (
            error.status_code
            if error.status_code in {401, 403, 404, 409, 413, 422, 429, 502, 503}
            else 503
        )
        messages = {
            401: "Authentication required",
            403: "Guided practice not permitted",
            404: "Guided practice not found",
            409: "Refresh practice or reconnect",
            413: "Request body too large",
            422: "Invalid request fields",
            429: "Guided practice limit reached",
        }
        raise HTTPException(
            status, messages.get(status, "Guided practice unavailable")
        ) from None
    except Exception:
        raise HTTPException(503, "Guided practice unavailable") from None


def register_guided_routes(app, identity, confirmed_user, settings, scenarios):
    """Parent constructs runtime and calls start/close in its lifespan.

    identity is the existing owner dependency; confirmed_user is a confirmed-account
    dependency (existing ai_user or a dedicated dependency without audio-storage gate).
    confirmed_user must also accept the verified identity as its sole argument.
    Missing runtime fails closed and is never silently constructed here.
    """

    def runtime():
        result = getattr(app.state, "guided_runtime", None)
        if result is None:
            raise HTTPException(503, "Guided practice unavailable")
        return result

    @app.post("/api/v1/guided-sessions", response_model=GuidedSession)
    async def create(request: Request, user=Depends(confirmed_user)):
        data = await body(request, CreateInput)
        scenario = next((s for s in scenarios if s["id"] == data.scenario_id), None)
        if scenario is None:
            raise HTTPException(422, "Unknown scenario")
        return await safe(runtime().create(owner_of(user), data, scenario))

    @app.get("/api/v1/guided-sessions", response_model=SessionCollection)
    async def collection(user=Depends(identity)):
        return {"sessions": await safe(runtime().list(owner_of(user)))}

    @app.get("/api/v1/guided-sessions/{id}", response_model=GuidedSession)
    async def get(id: str, user=Depends(identity)):
        return await safe(runtime().get(owner_of(user), canonical(id)))

    @app.post(
        "/api/v1/guided-sessions/{id}/connection", response_model=ConnectionOutput
    )
    async def connection(id: str, request: Request, user=Depends(confirmed_user)):
        canonical(id)
        data = await body(request, ConnectionInput)
        return await safe(
            runtime().connect(
                owner_of(user), id, data, auth_expires_at=verified_expiry(user)
            )
        )

    @app.post("/api/v1/guided-sessions/{id}/commands", response_model=GuidedSession)
    async def commands(id: str, request: Request, user=Depends(identity)):
        canonical(id)
        data = await body(request, CommandInput)
        if data.action != "finish":
            await safe(invoke(confirmed_user, user))
        return await safe(runtime().command(owner_of(user), id, data))

    @app.post("/api/v1/guided-sessions/{id}/heartbeat", response_model=GuidedSession)
    async def heartbeat(id: str, request: Request, user=Depends(identity)):
        canonical(id)
        await body(request)
        return await safe(runtime().heartbeat(owner_of(user), id))

    @app.delete("/api/v1/guided-sessions/{id}", status_code=204)
    async def delete(id: str, user=Depends(identity)):
        await safe(runtime().delete(owner_of(user), canonical(id)))
        return Response(status_code=204)
