"""ASGI route integration; labeled identity/confirmation adapter doubles only."""

import asyncio
import importlib
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException
import pytest
from test_guided_runtime import setup_runtime, OWNER
from test_guided_models import ID

BASE = "/api/v1/guided-sessions"


def routes():
    try:
        return importlib.import_module("guided_routes")
    except ModuleNotFoundError:
        pytest.fail("Guided authenticated routes are not implemented")


def application(runtime):
    app = FastAPI()
    app.state.guided_runtime = runtime
    app.state.confirmed = True

    # Synthetic adapter unit boundary, NOT live authentication or test account.
    def identity(authorization: str = Header(default="")):
        if authorization not in {"synthetic-owner", "synthetic-other"}:
            raise HTTPException(401, "Authentication required")
        return OWNER if authorization == "synthetic-owner" else "synthetic-other-owner"

    def confirmed(user=Depends(identity)):
        if not app.state.confirmed:
            raise HTTPException(403, "Confirmation required")
        return user

    routes().register_guided_routes(
        app, identity, confirmed, runtime.settings, [{"id": "intro"}]
    )
    return app


def test_authenticated_create_read_owner_scope_strict_fields_and_disabled_finish():
    async def run():
        r, store, p, regular = setup_runtime()
        app = application(r)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            try:
                data = dict(
                    command_id=ID,
                    scenario_id="intro",
                    goal="Clear requests",
                    context="",
                    prompt_visible=True,
                )
                assert (await client.post(BASE, json=data)).status_code == 401
                client.headers["Authorization"] = "synthetic-owner"
                app.state.confirmed = False
                assert (await client.post(BASE, json=data)).status_code == 403
                app.state.confirmed = True
                assert (
                    await client.post(
                        BASE, json=data | {"transcript": "forged private text"}
                    )
                ).status_code == 422
                created = await client.post(BASE, json=data)
                assert created.status_code == 200 and created.json()["id"] == ID
                assert (await client.post(BASE, json=data)).json() == created.json()
                assert len((await client.get(BASE)).json()["sessions"]) == 1
                assert (await client.get(BASE + "/" + ID)).json() == created.json()
                assert (await client.get(BASE + "/" + ID.upper())).status_code == 422
                client.headers["Authorization"] = "synthetic-other"
                assert (await client.get(BASE + "/" + ID)).status_code == 404
                assert (await client.get(BASE)).json() == {"sessions": []}
                client.headers["Authorization"] = "synthetic-owner"
                app.state.confirmed = False
                connection = dict(
                    command_id="22345678-1234-4234-8234-123456789abc",
                    expected_revision=created.json()["revision"],
                    sdp="synthetic-audio-offer",
                )
                assert (
                    await client.post(BASE + "/" + ID + "/connection", json=connection)
                ).status_code == 403
                regular.active = False
                r.settings.ai_enabled = False
                assert (await client.post(BASE, json=data)).status_code == 403
                app.state.confirmed = True
                assert (await client.post(BASE, json=data)).status_code == 503
                app.state.confirmed = False
                command = dict(
                    command_id="32345678-1234-4234-8234-123456789abc",
                    expected_revision=created.json()["revision"],
                    prompt_id=None,
                    action="finish",
                )
                ended = await client.post(BASE + "/" + ID + "/commands", json=command)
                assert ended.status_code == 200 and ended.json()["state"] == "finished"
                assert (await client.delete(BASE + "/" + ID)).status_code == 204
                assert (await client.get(BASE)).json() == {"sessions": []}
            finally:
                await r.close()

    asyncio.run(run())


def test_active_commands_require_confirmation_but_finish_does_not():
    async def run():
        r, store, p, _ = setup_runtime()
        app = application(r)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "synthetic-owner"},
        ) as client:
            try:
                created = (
                    await client.post(
                        BASE,
                        json=dict(
                            command_id=ID, scenario_id="intro", goal="Clear requests"
                        ),
                    )
                ).json()
                app.state.confirmed = False
                data = dict(
                    command_id="22345678-1234-4234-8234-123456789abc",
                    expected_revision=created["revision"],
                    prompt_id=None,
                    action="pause",
                )
                assert (
                    await client.post(BASE + "/" + ID + "/commands", json=data)
                ).status_code == 403
                assert (await r.get(OWNER, ID)).state == "created"
                ended = await client.post(
                    BASE + "/" + ID + "/commands", json=data | {"action": "finish"}
                )
                assert ended.status_code == 200 and ended.json()["state"] == "finished"
            finally:
                await r.close()

    asyncio.run(run())


def test_connection_commands_heartbeat_caps_safe_errors_and_missing_runtime():
    async def run():
        r, store, p, regular = setup_runtime()
        app = application(r)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "synthetic-owner"},
        ) as client:
            try:
                created = (
                    await client.post(
                        BASE,
                        json=dict(
                            command_id=ID,
                            scenario_id="intro",
                            goal="Clear requests",
                            context="",
                            prompt_visible=True,
                        ),
                    )
                ).json()
                data = dict(
                    command_id="22345678-1234-4234-8234-123456789abc",
                    expected_revision=created["revision"],
                    sdp="synthetic-audio-offer",
                )
                connected = await client.post(
                    BASE + "/" + ID + "/connection", json=data
                )
                assert (
                    connected.status_code == 200
                    and connected.json()["session"]["state"] == "coach_speaking"
                )
                assert (
                    await client.post(BASE + "/" + ID + "/connection", json=data)
                ).json() == connected.json()
                assert (
                    await client.post(BASE + "/" + ID + "/heartbeat", json={})
                ).status_code == 200
                invalid = await client.post(
                    BASE + "/" + ID + "/heartbeat",
                    json={"transcript": "private-forgery"},
                )
                assert (
                    invalid.status_code == 422 and "private-forgery" not in invalid.text
                )
                huge = await client.post(BASE, content=b"x" * 32769)
                assert huge.status_code == 413
                assert (
                    await client.post(
                        BASE + "/" + ID + "/connection",
                        json=data | {"sdp": "x" * 24001},
                    )
                ).status_code == 422
                app.state.guided_runtime = None
                assert (await client.get(BASE)).status_code == 503
            finally:
                await r.close()

    asyncio.run(run())
