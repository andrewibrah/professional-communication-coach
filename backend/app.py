from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Header
from auth import Authenticator
from supabase_store import Store, PROJECT_URL
from private_storage import PrivateStorage
from guided_store import GuidedStore
from guided_runtime import GuidedRuntime, invoke
from guided_routes import register_guided_routes
from voice_provider import VoiceProvider
from storage_routes import register_storage_routes, sweep
from contextlib import asynccontextmanager
import asyncio
import json
import logging
import os
import re
import stat
import time
from models import Profile, SessionInput, ScenarioOutput
from ai import AI
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import Response, Request
from models import Report
from media import MAX_BYTES, extension, probe
import tempfile
from uuid import UUID
from starlette.concurrency import run_in_threadpool
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from guards import GuardMiddleware, RateLimiter
import jwt


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env", extra="ignore"
    )
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    supabase_service_role_key: str = ""
    audio_temp_dir: str = str(Path(__file__).parent / "data/audio")
    persistence_cutover_receipt: str = str(
        Path(__file__).parent / "data/supabase-cutover.json"
    )
    supabase_jwt_audience: str = "authenticated"
    openai_api_key: str = ""
    ai_enabled: bool = True
    openai_model: str = "gpt-4.1-mini"
    transcription_model: str = "gpt-4o-mini-transcribe"
    guided_voice_enabled: bool = True
    guided_voice_model: str = "gpt-realtime-mini"
    guided_daily_seconds: int = 1800
    guided_monthly_seconds: int = 18000
    guided_max_retries: int = Field(default=2, ge=0, le=2)
    user_rate_limit: int = 60
    ip_rate_limit: int = 120
    daily_limit: int = 20
    monthly_limit: int = 200
    db_path: str = str(Path(__file__).parent / "data/speechclear.sqlite3")

    @property
    def auth_configured(self):
        return (
            self.supabase_url.startswith("https://")
            and self.public_key_safe
            and "placeholder" not in self.supabase_url.lower()
        )

    @property
    def public_key_safe(self):
        key = self.supabase_publishable_key
        if key.startswith("sb_publishable_") and len(key) > len("sb_publishable_"):
            return True
        try:
            # Classification only, not authentication. Never publish service-role JWTs.
            return (
                jwt.decode(key, options={"verify_signature": False}).get("role")
                == "anon"
            )
        except jwt.PyJWTError:
            return False


SCENARIOS = [
    dict(id=id, title=title, description=title, question=question)
    for id, title, question in [
        (
            "introduction",
            "Tell me about yourself",
            "Tell me about yourself and the value you bring.",
        ),
        (
            "technical-interview",
            "Technical interview",
            "Explain a technical problem you solved and your approach.",
        ),
        (
            "help-desk",
            "Help-desk troubleshooting",
            "How would you help a customer who cannot connect to the network?",
        ),
        (
            "cybersecurity",
            "Cybersecurity explanation",
            "Explain phishing risks to a nontechnical colleague.",
        ),
        (
            "sales",
            "Sales discovery",
            "How would you respond to a customer concerned about price?",
        ),
        (
            "escalation",
            "Customer escalation",
            "Respond to a frustrated customer whose issue remains unresolved.",
        ),
    ]
]


class UnavailableStore:
    def __getattr__(self, name):
        def unavailable(*args, **kwargs):
            raise HTTPException(503, "Private persistence unavailable")

        return unavailable


def cutover_verified(settings):
    """Only a protected, target-bound operator receipt enables persistence."""
    try:
        path = Path(settings.persistence_cutover_receipt)
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            return False
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as source:
            info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid()
                or info.st_size > 16384
            ):
                return False
            data = json.load(source)
        verified_at = datetime.fromisoformat(data["verified_at"])
        return (
            data["target"] == settings.supabase_url == PROJECT_URL
            and data["project_ref"] == "qpheitaamyzcekzvbcox"
            and verified_at.tzinfo is not None
            and verified_at <= datetime.now(timezone.utc)
            and all(
                data.get(key) is True
                for key in (
                    "owner_mapping_verified",
                    "counts_readback_verified",
                    "cutover_ready",
                )
            )
            and all(
                isinstance(data.get(key), str)
                and re.fullmatch(r"[0-9a-f]{64}", data[key])
                for key in ("backup_sha256", "export_sha256")
            )
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def sweep_local_audio(folder):
    """Remove only our stale regular temporary files, never foreign files/symlinks."""
    folder = Path(folder)
    if (
        not folder.exists()
        or folder.is_symlink()
        or any(p.is_symlink() for p in folder.parents)
    ):
        return
    info = folder.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        return
    cutoff = time.time() - 86400
    for path in folder.glob("speechclear-*"):
        try:
            info = path.lstat()
            if (
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and info.st_mtime < cutoff
            ):
                path.unlink()
        except OSError:
            continue


def create_app(
    settings=None, store=None, storage=None, guided_store=None, voice_provider=None
):
    settings = settings or Settings()
    injected = store is not None
    legacy = False
    if injected:
        from store import Store as LegacyStore

        legacy = isinstance(store, LegacyStore)
    if store is None:
        try:
            store = Store(settings)
        except ValueError:
            store = UnavailableStore()
    if storage is None:
        try:
            storage = PrivateStorage(settings)
        except ValueError:
            storage = UnavailableStore()
    if guided_store is None:
        if injected:
            # Explicit local test adapters never accidentally contact runtime Guided SQL.
            guided_store = UnavailableStore()
        else:
            try:
                guided_store = GuidedStore(settings)
            except ValueError:
                guided_store = UnavailableStore()
    voice_provider = voice_provider or VoiceProvider(settings)

    def persistence_ready():
        return not isinstance(app.state.store, UnavailableStore) and (
            injected or cutover_verified(settings)
        )

    async def cleanup_once():
        folder = Path(settings.audio_temp_dir)
        if folder.is_symlink() or any(p.is_symlink() for p in folder.parents):
            logging.getLogger(__name__).warning("Local audio cleanup blocked")
            return
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if folder.stat().st_uid != os.getuid():
            logging.getLogger(__name__).warning("Local audio cleanup blocked")
            return
        folder.chmod(0o700)
        await run_in_threadpool(sweep_local_audio, settings.audio_temp_dir)
        if (
            not legacy
            and persistence_ready()
            and not isinstance(app.state.storage, UnavailableStore)
        ):
            try:
                await run_in_threadpool(sweep, app)
            except Exception:
                logging.getLogger(__name__).warning("Cleanup deferred; retry pending")

    async def cleanup_worker():
        while True:
            await asyncio.sleep(60)
            await cleanup_once()

    @asynccontextmanager
    async def lifespan(app):
        await cleanup_once()
        if (
            not isinstance(app.state.guided_store, UnavailableStore)
            and persistence_ready()
        ):
            app.state.guided_schema_ready = await invoke(app.state.guided_store.ready)
            await app.state.guided_runtime.start()
        worker = asyncio.create_task(cleanup_worker())
        try:
            yield
        finally:
            if app.state.guided_runtime is not None:
                await app.state.guided_runtime.close()
            else:
                await invoke(app.state.voice_provider.close)
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
            for resource in (app.state.store, app.state.storage):
                if isinstance(resource, UnavailableStore):
                    continue
                close = getattr(resource, "close", None)
                if close:
                    await run_in_threadpool(close)
                else:
                    client = getattr(resource, "_client", None) or getattr(
                        resource, "client", None
                    )
                    if client is not None:
                        await run_in_threadpool(client.close)

    app = FastAPI(title="SpeechClear API", lifespan=lifespan)
    app.state.store = store
    app.state.storage = storage
    app.state.settings = settings
    app.state.guided_store = guided_store
    app.state.voice_provider = voice_provider
    app.state.guided_schema_ready = False
    app.state.guided_runtime = (
        GuidedRuntime(settings, guided_store, voice_provider, store)
        if not isinstance(guided_store, UnavailableStore)
        else None
    )
    limiter = RateLimiter()
    app.add_middleware(GuardMiddleware, settings=settings, limiter=limiter)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return JSONResponse(
            {"detail": "Service temporarily unavailable"}, status_code=500
        )

    @app.get("/api/v1/health")
    def health():
        return dict(
            status="ok",
            storage="supabase",
            auth_configured=settings.auth_configured,
            persistence_ready=persistence_ready(),
            audio_storage_ready=(
                persistence_ready()
                and not legacy
                and not isinstance(app.state.storage, UnavailableStore)
            ),
        )

    @app.get("/api/v1/config")
    def config():
        guided_available = bool(
            settings.guided_voice_enabled
            and settings.ai_enabled
            and getattr(
                app.state.voice_provider, "ready", bool(settings.openai_api_key)
            )
            and persistence_ready()
            and app.state.guided_schema_ready
        )
        return dict(
            supabase_url=settings.supabase_url if settings.auth_configured else "",
            supabase_publishable_key=settings.supabase_publishable_key
            if settings.auth_configured
            else "",
            auth_configured=settings.auth_configured,
            ai_enabled=settings.ai_enabled and bool(settings.openai_api_key),
            min_recording_seconds=30,
            max_recording_seconds=180,
            max_upload_bytes=12582912,
            guided_voice_available=guided_available,
            guided_max_seconds=300,
            guided_unavailable_reason=""
            if guided_available
            else "Guided provider or persistence setup is unavailable.",
        )

    @app.get("/api/v1/scenarios")
    def scenarios():
        return {"scenarios": SCENARIOS}

    app.state.auth = Authenticator(settings)

    def identity(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer ") or not authorization[7:]:
            raise HTTPException(401, "Authentication required")
        token = authorization[7:]
        subject = app.state.auth.verify(token)["sub"]
        if not persistence_ready():
            raise HTTPException(503, "Private persistence unavailable")
        limiter.check(("user", subject), settings.user_rate_limit)
        return subject, token

    @app.get("/api/v1/profile")
    def profile(user=Depends(identity)):
        return app.state.store.profile(user[0])

    @app.put("/api/v1/profile")
    def put_profile(profile: Profile, user=Depends(identity)):
        return app.state.store.profile(user[0], profile.model_dump())

    app.state.ai = AI(settings)

    def require_ai_active(user):
        if not settings.ai_enabled or not settings.openai_api_key:
            raise HTTPException(503, "AI features unavailable")
        app.state.store.require_active(user[0])

    def ai_user(user=Depends(identity)):
        if not legacy and isinstance(app.state.storage, UnavailableStore):
            raise HTTPException(503, "Private audio storage unavailable")
        require_ai_active(user)
        app.state.auth.require_confirmed(user[1], user[0])
        require_ai_active(user)
        return user

    def guided_user(user=Depends(identity)):
        if not settings.guided_voice_enabled or not getattr(
            app.state.voice_provider, "ready", bool(settings.openai_api_key)
        ):
            raise HTTPException(503, "Guided Voice unavailable")
        require_ai_active(user)
        app.state.auth.require_confirmed(user[1], user[0])
        require_ai_active(user)
        return user

    register_guided_routes(app, identity, guided_user, settings, SCENARIOS)

    @app.post("/api/v1/sessions")
    def new_session(data: SessionInput, user=Depends(ai_user)):
        scenario = next((s for s in SCENARIOS if s["id"] == data.scenario_id), None)
        if scenario is None:
            raise HTTPException(422, "Unknown scenario")
        app.state.store.reserve(user[0], settings.daily_limit, settings.monthly_limit)
        try:
            generated = ScenarioOutput.model_validate(
                app.state.ai.scenario(
                    scenario, data.model_dump(), app.state.store.profile(user[0])
                )
            ).model_dump()
        except Exception:
            raise HTTPException(
                502, "AI generation failed; please try again later"
            ) from None
        return app.state.store.save_session(
            user[0],
            dict(
                id=str(uuid4()),
                scenario_id=data.scenario_id,
                goal=data.goal,
                question=scenario["question"],
                created_at=datetime.now(timezone.utc).isoformat(),
                **generated,
            ),
        )

    @app.get("/api/v1/sessions")
    def sessions(user=Depends(identity)):
        return {"sessions": app.state.store.sessions(user[0])}

    @app.get("/api/v1/sessions/{id}")
    def session(id: str, user=Depends(identity)):
        if not legacy:
            return app.state.store.session_detail(user[0], id)
        return app.state.store.session(user[0], id) | {
            "attempts": app.state.store.attempts(user[0], id)
        }

    @app.delete("/api/v1/sessions/{id}", status_code=204)
    def delete_session(id: str, user=Depends(identity)):
        app.state.store.delete(user[0], id)
        return Response(status_code=204)

    @app.delete("/api/v1/history", status_code=204)
    def delete_history(user=Depends(identity)):
        app.state.store.delete(user[0])
        return Response(status_code=204)

    @app.get("/api/v1/usage")
    def usage(user=Depends(identity)):
        return app.state.store.usage(
            user[0], settings.daily_limit, settings.monthly_limit
        )

    process_upload = register_storage_routes(app, ai_user, require_ai_active, settings)

    @app.post("/api/v1/sessions/{id}/attempts")
    async def attempt(
        id: str,
        request: Request,
        user=Depends(ai_user),
        idempotency_key: str = Header(default=""),
    ):
        if not legacy:
            if (
                request.headers.get("content-type", "").split(";")[0].strip().lower()
                != "application/json"
            ):
                raise HTTPException(415, "JSON upload reference required")
            return await process_upload(id, request, user, idempotency_key)
        try:
            if str(UUID(idempotency_key)) != idempotency_key:
                raise ValueError()
        except ValueError:
            raise HTTPException(
                422, "Idempotency-Key must be a canonical UUID"
            ) from None
        session = app.state.store.session(user[0], id)
        path = None
        started = False
        try:
            async with request.form(
                max_files=1, max_fields=1, max_part_size=4096
            ) as form:
                upload = form.get("audio")
                if not hasattr(upload, "read"):
                    raise HTTPException(422, "Audio file required")
                suffix = extension(upload.filename, upload.content_type or "")
                try:
                    declared = float(form.get("duration_seconds", ""))
                except (ValueError, TypeError):
                    raise HTTPException(422, "Invalid duration") from None
                folder = Path(settings.audio_temp_dir)
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                folder.chmod(0o700)
                with tempfile.NamedTemporaryFile(
                    dir=folder, prefix="speechclear-", suffix=suffix, delete=False
                ) as file:
                    path = Path(file.name)
                    size = 0
                    while chunk := await upload.read(65536):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise HTTPException(413, "Audio exceeds 12 MiB")
                        file.write(chunk)
                duration = await run_in_threadpool(probe, path, suffix, declared)
                require_ai_active(user)
                cached = app.state.store.begin_attempt(
                    user[0],
                    id,
                    idempotency_key,
                    settings.daily_limit,
                    settings.monthly_limit,
                )
                if cached is not None:
                    return cached
                started = True
                transcript = await run_in_threadpool(app.state.ai.transcribe, path)
                require_ai_active(user)
                report = Report.model_validate(
                    await run_in_threadpool(
                        app.state.ai.evaluate,
                        transcript,
                        session,
                        app.state.store.profile(user[0]),
                        duration,
                    )
                )
                if any(e.quote not in transcript for e in report.transcript_evidence):
                    raise ValueError("Evidence not found")
                result = dict(
                    id=str(uuid4()),
                    session_id=id,
                    transcript=transcript,
                    duration_seconds=duration,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    report=report.model_dump(),
                )
                return app.state.store.finish_attempt(user[0], idempotency_key, result)
        except HTTPException:
            if started:
                app.state.store.fail_attempt(user[0], idempotency_key)
            raise
        except Exception:
            if started:
                app.state.store.fail_attempt(user[0], idempotency_key)
            raise HTTPException(
                502, "Audio processing failed; please try again later"
            ) from None
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    return app


app = create_app()
