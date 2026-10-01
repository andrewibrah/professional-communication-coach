"""Backend-only private Storage transport. Never return provider URLs/errors."""

from pathlib import Path
from urllib.parse import quote
from uuid import UUID
import tempfile
from time import monotonic

import httpx
from fastapi import HTTPException
from media import MAX_BYTES, FORMATS

TRANSFER_SECONDS = 120


def private_temp_folder(folder):
    folder = Path(folder).absolute()
    if any(part.is_symlink() for part in (folder, *folder.parents)):
        raise HTTPException(503, "Unsafe audio temporary directory")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not folder.is_dir() or folder.is_symlink():
        raise HTTPException(503, "Unsafe audio temporary directory")
    folder.chmod(0o700)
    return folder


TARGET = "https://qpheitaamyzcekzvbcox.supabase.co"


class PrivateStorage:
    def __init__(self, settings, transport=None):
        if settings.supabase_url.rstrip("/") != TARGET:
            raise ValueError("Private Storage target mismatch")
        import jwt

        key = getattr(settings, "supabase_secret_key", "") or getattr(
            settings, "supabase_service_role_key", ""
        )
        valid = (
            isinstance(key, str)
            and key == key.strip()
            and not any(
                marker in key.lower() for marker in ("placeholder", "replace_with")
            )
        )
        modern = valid and key.startswith("sb_secret_") and len(key) > len("sb_secret_")
        legacy = False
        if valid and not modern:
            try:
                # Classification only: Supabase verifies the actual credential.
                legacy = (
                    jwt.decode(key, options={"verify_signature": False}).get("role")
                    == "service_role"
                )
            except jwt.PyJWTError:
                pass
        if not (modern or legacy):
            raise ValueError("Backend Storage credential required")
        headers = {"apikey": key}
        if legacy:
            headers["Authorization"] = "Bearer " + key
        self.client = httpx.Client(
            base_url=TARGET + "/storage/v1",
            headers=headers,
            transport=transport,
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        )

    def _target(self, owner, metadata):
        try:
            assert str(UUID(owner)) == owner
            object_id = metadata["id"]
            assert str(UUID(object_id)) == object_id
            assert metadata["user_id"] == owner
            assert metadata["bucket"] == "temporary-audio"
            suffix = metadata["suffix"]
            assert suffix in FORMATS
            expected = owner + "/" + object_id + "/response" + suffix
            assert metadata["path"] == expected
            assert metadata["content_type"].split(";")[0] in FORMATS[suffix][0]
            return "/object/temporary-audio/" + quote(expected, safe="/")
        except (AssertionError, KeyError, TypeError, ValueError):
            raise HTTPException(404, "Audio upload not found") from None

    def upload(self, owner, metadata, path):
        target = self._target(owner, metadata)
        if not 0 < path.stat().st_size <= MAX_BYTES:
            raise HTTPException(413, "Audio exceeds upload limit")
        try:
            deadline = monotonic() + TRANSFER_SECONDS
            with path.open("rb") as source:

                def bounded_chunks():
                    while chunk := source.read(65536):
                        if monotonic() >= deadline:
                            raise ValueError("Transfer deadline")
                        yield chunk

                # Do not drain an untrusted provider response body after upload.
                with self.client.stream(
                    "POST",
                    target,
                    content=bounded_chunks(),
                    headers={
                        "Content-Type": metadata["content_type"],
                        "Content-Length": str(path.stat().st_size),
                        "x-upsert": "false",
                    },
                ) as response:
                    if response.status_code not in (200, 201):
                        raise ValueError()
        except (httpx.HTTPError, ValueError, OSError):
            raise HTTPException(503, "Private audio upload unavailable") from None

    def download(self, owner, metadata, folder):
        target = self._target(owner, metadata)
        folder = private_temp_folder(folder)
        path = None
        try:
            deadline = monotonic() + TRANSFER_SECONDS
            with self.client.stream("GET", target) as response:
                if response.status_code != 200:
                    raise HTTPException(
                        404 if response.status_code == 404 else 503,
                        "Private audio unavailable",
                    )
                with tempfile.NamedTemporaryFile(
                    dir=folder,
                    prefix="speechclear-",
                    suffix=metadata["suffix"],
                    delete=False,
                ) as destination:
                    path = Path(destination.name)
                    size = 0
                    for chunk in response.iter_bytes():
                        if monotonic() >= deadline:
                            raise ValueError("Transfer deadline")
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise HTTPException(413, "Audio exceeds upload limit")
                        destination.write(chunk)
                if size == 0:
                    raise HTTPException(422, "Empty audio object")
            return path
        except Exception as error:
            if path:
                path.unlink(missing_ok=True)
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(503, "Private audio download unavailable") from None

    def delete(self, owner, metadata):
        target = self._target(owner, metadata)
        try:
            response = self.client.request(
                "DELETE",
                "/object/temporary-audio",
                json={"prefixes": [metadata["path"]]},
            )
            if response.status_code not in (200, 404):
                raise ValueError()
            # A successful delete request alone is not proof of object disappearance.
            with self.client.stream("GET", target) as check:
                absent = check.status_code == 404
                if check.status_code == 400:
                    check.read()
                    body = check.json()
                    absent = (
                        body.get("error") in ("not_found", "NoSuchKey")
                        or body.get("message") == "Object not found"
                    )
                if not absent:
                    raise ValueError()
            return True
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "Audio cleanup pending") from None
