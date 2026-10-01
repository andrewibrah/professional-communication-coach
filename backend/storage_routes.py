"""Five-minute identity-bound authorization; audio relayed to private Storage."""

from pathlib import Path
from uuid import UUID, uuid4
from datetime import datetime, timezone
import tempfile
import asyncio
from private_storage import private_temp_folder

from fastapi import Depends, HTTPException, Request, Response
from pydantic import Field
from models import StrictModel, Report
from media import MAX_BYTES, probe
from starlette.concurrency import run_in_threadpool

RELAY_DRAIN_SECONDS = 120


class UploadInput(StrictModel):
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(gt=0, le=MAX_BYTES)
    duration_seconds: float = Field(ge=30, le=180, allow_inf_nan=False)


class ProcessInput(StrictModel):
    upload_id: str = Field(min_length=36, max_length=36)


def canonical(value):
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "Canonical UUID required") from None
    return value


def cleanup(app, owner, metadata):
    # Compensation is for this writer/processor only, never stale janitor candidates.
    # SQL outage must not prevent deleting physical bytes already written.
    intent_error = None
    try:
        app.state.store.rpc(
            "upload_state", owner, {"id": metadata["id"], "state": "cleanup_pending"}
        )
    except Exception as error:
        intent_error = error
    app.state.storage.delete(owner, metadata)
    app.state.store.rpc("cleanup_done", owner, {"id": metadata["id"]})
    if intent_error:
        raise intent_error


def sweep(app):
    rows = app.state.store.rpc("cleanup_list", None, {})
    completed = 0
    for metadata in rows:
        try:
            claimed = app.state.store.rpc(
                "cleanup_claim",
                metadata["user_id"],
                {"id": metadata["id"], "updated_at": metadata["updated_at"]},
            )
            if claimed is None:
                continue
            app.state.storage.delete(claimed["user_id"], claimed)
            app.state.store.rpc(
                "cleanup_done", claimed["user_id"], {"id": claimed["id"]}
            )
            completed += 1
        except Exception:
            continue  # Retry durable intent; never log provider details or paths.
    return completed


def register_storage_routes(app, ai_user, require_ai_active, settings):
    @app.post("/api/v1/sessions/{id}/attempt-uploads")
    def authorize(id: str, data: UploadInput, user=Depends(ai_user)):
        canonical(id)
        mime = data.content_type.split(";")[0].lower()
        suffix = {
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/mp4": ".mp4",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mpeg": ".mp3",
        }.get(mime)
        if suffix is None:
            raise HTTPException(415, "Unsupported audio type")
        metadata = app.state.store.rpc(
            "upload_create",
            user[0],
            {
                "id": str(uuid4()),
                "session": id,
                "content_type": mime,
                "suffix": suffix,
                "size_bytes": data.size_bytes,
                "duration_seconds": data.duration_seconds,
            },
        )
        return {"upload_id": metadata["id"], "expires_at": metadata["expires_at"]}

    @app.put("/api/v1/sessions/{id}/attempt-uploads/{upload_id}", status_code=204)
    async def relay(id: str, upload_id: str, request: Request, user=Depends(ai_user)):
        canonical(id)
        canonical(upload_id)
        metadata = await run_in_threadpool(
            app.state.store.rpc,
            "upload_claim",
            user[0],
            {"id": upload_id, "session": id},
        )
        folder = private_temp_folder(settings.audio_temp_dir)
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=folder,
                prefix="speechclear-",
                suffix=metadata["suffix"],
                delete=False,
            ) as output:
                path = Path(output.name)
                size = 0
                try:
                    async with asyncio.timeout(RELAY_DRAIN_SECONDS):
                        async for chunk in request.stream():
                            size += len(chunk)
                            if size > MAX_BYTES or size > metadata["size_bytes"]:
                                raise HTTPException(
                                    413, "Audio exceeds authorized size"
                                )
                            output.write(chunk)
                except TimeoutError:
                    raise HTTPException(408, "Audio upload timed out") from None
            if size != metadata["size_bytes"]:
                raise HTTPException(422, "Audio size does not match authorization")
            await run_in_threadpool(
                probe, path, metadata["suffix"], metadata["duration_seconds"]
            )
            require_ai_active(user)
            # A long drain/probe may outlive the claim or a concurrent deletion.
            metadata = await run_in_threadpool(
                app.state.store.rpc,
                "upload_write_check",
                user[0],
                {"id": upload_id, "session": id},
            )
            await run_in_threadpool(app.state.storage.upload, user[0], metadata, path)
            await run_in_threadpool(
                app.state.store.rpc,
                "upload_state",
                user[0],
                {"id": upload_id, "state": "uploaded"},
            )
            return Response(status_code=204)
        except BaseException:
            try:
                await run_in_threadpool(cleanup, app, user[0], metadata)
            except Exception:
                pass
            raise
        finally:
            if path:
                path.unlink(missing_ok=True)

    async def process(id, request, user, idempotency_key):
        canonical(id)
        canonical(idempotency_key)
        try:
            payload = ProcessInput.model_validate(await request.json())
        except Exception:
            raise HTTPException(422, "Invalid processing request") from None
        canonical(payload.upload_id)
        store = app.state.store
        cached = await run_in_threadpool(
            store.rpc,
            "begin_attempt",
            user[0],
            {
                "session": id,
                "key": idempotency_key,
                "daily": settings.daily_limit,
                "monthly": settings.monthly_limit,
                "upload_id": payload.upload_id,
            },
        )
        if cached is not None:
            return cached
        metadata = None
        path = None
        try:
            metadata = await run_in_threadpool(
                store.rpc,
                "upload_get",
                user[0],
                {"id": payload.upload_id, "session": id},
            )
            path = await run_in_threadpool(
                app.state.storage.download, user[0], metadata, settings.audio_temp_dir
            )
            duration = await run_in_threadpool(
                probe, path, metadata["suffix"], metadata["duration_seconds"]
            )
            require_ai_active(user)
            session = await run_in_threadpool(store.session, user[0], id)
            transcript = await run_in_threadpool(app.state.ai.transcribe, path)
            require_ai_active(user)
            profile = await run_in_threadpool(store.profile, user[0])
            report = Report.model_validate(
                await run_in_threadpool(
                    app.state.ai.evaluate, transcript, session, profile, duration
                )
            )
            if any(e.quote not in transcript for e in report.transcript_evidence):
                raise ValueError("Evidence not found")
            require_ai_active(user)
            result = {
                "id": str(uuid4()),
                "session_id": id,
                "transcript": transcript,
                "duration_seconds": duration,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "report": report.model_dump(),
            }
            return await run_in_threadpool(
                store.finish_attempt, user[0], idempotency_key, result
            )
        except HTTPException:
            await run_in_threadpool(store.fail_attempt, user[0], idempotency_key)
            raise
        except Exception:
            await run_in_threadpool(store.fail_attempt, user[0], idempotency_key)
            raise HTTPException(
                502, "Audio processing failed; start a new recording"
            ) from None
        finally:
            if path:
                path.unlink(missing_ok=True)
            if metadata:
                try:
                    await run_in_threadpool(cleanup, app, user[0], metadata)
                except Exception:
                    pass

    return process
