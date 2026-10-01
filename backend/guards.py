import time
from threading import Lock
from fastapi import HTTPException
from starlette.responses import JSONResponse
from media import MAX_BYTES


class RateLimiter:
    def __init__(self):
        self.entries = {}
        self.lock = Lock()

    def check(self, key, limit):
        now = int(time.monotonic() // 60)
        with self.lock:
            if len(self.entries) > 10000:
                self.entries = {k: v for k, v in self.entries.items() if v[0] == now}
                if len(self.entries) > 10000:
                    raise HTTPException(429, "Rate limit reached")
            window, count = self.entries.get(key, (now, 0))
            count = count + 1 if window == now else 1
            self.entries[key] = (now, count)
            if count > limit:
                raise HTTPException(429, "Rate limit reached")


class GuardMiddleware:
    def __init__(self, app, settings, limiter):
        self.app = app
        self.settings = settings
        self.limiter = limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        path = scope["path"]
        parts = path.strip("/").split("/")
        raw_upload = scope["method"] == "PUT" and (
            len(parts) == 4
            and parts[:3] == ["api", "v1", "attempt-uploads"]
            or len(parts) == 6
            and parts[:3] == ["api", "v1", "sessions"]
            and parts[4] == "attempt-uploads"
        )
        legacy_multipart = path.endswith("/attempts") and headers.get(
            b"content-type", b""
        ).lower().startswith(b"multipart/form-data")
        cap = (
            MAX_BYTES
            if raw_upload
            else MAX_BYTES + 65536
            if legacy_multipart
            else 32768
        )
        try:
            self.limiter.check(
                ("ip", (scope.get("client") or ("unknown",))[0]),
                self.settings.ip_rate_limit,
            )
            length = int(headers.get(b"content-length", b"0"))
            if length < 0 or length > cap:
                raise HTTPException(413, "Request body too large")
        except ValueError:
            return await JSONResponse(
                {"detail": "Invalid content length"}, status_code=400
            )(scope, receive, send)
        except HTTPException as e:
            return await JSONResponse({"detail": e.detail}, status_code=e.status_code)(
                scope, receive, send
            )
        size = 0

        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > cap:
                raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, bounded_receive, send)
