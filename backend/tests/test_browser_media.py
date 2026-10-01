"""Actual Chromium MediaRecorder bytes; controlled tone, no private content."""

import json
import io
import subprocess
import wave
from pathlib import Path

import pytest
from fastapi import HTTPException

from media import probe

FIXTURES = Path(__file__).parent / "fixtures"
CLIPS = {
    c["name"]: c
    for c in json.loads((FIXTURES / "browser-audio.json").read_text())["clips"]
}


@pytest.mark.parametrize("name", ["boundary", "valid"])
def test_actual_browser_webm_without_container_duration_is_decoded(name):
    clip = CLIPS[name]
    duration = probe(FIXTURES / clip["filename"], ".webm", clip["seconds"])
    assert 29.85 <= duration <= 180.15
    assert abs(duration - clip["seconds"]) < 0.15


def test_actual_short_browser_audio_cannot_be_accepted_by_claiming_thirty_seconds():
    with pytest.raises(HTTPException) as error:
        probe(FIXTURES / CLIPS["short"]["filename"], ".webm", 30)
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "seconds,declared,accepted",
    [
        (29.84, 30, False),
        (29.86, 30, True),
        (180.14, 180, True),
        (180.16, 180, False),
        (185, 180, False),
        (30, 40, False),
    ],
)
def test_decoded_boundary_precision_is_bounded(tmp_path, seconds, declared, accepted):
    # Supplementary PCM cases; the primary regression uses actual browser bytes.
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * round(seconds * 8000))
    path = tmp_path / "boundary.wav"
    path.write_bytes(buffer.getvalue())
    if accepted:
        assert probe(path, ".wav", declared) == pytest.approx(seconds, abs=0.001)
    else:
        with pytest.raises(HTTPException) as error:
            probe(path, ".wav", declared)
        assert error.value.status_code == 422


def test_decoder_timeout_fails_closed_with_bounded_command(monkeypatch):
    original = subprocess.run

    def run(args, **kwargs):
        if args[0] == "ffmpeg":
            assert args[args.index("-t") + 1] == "181"
            assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
            assert kwargs["timeout"] == 20
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return original(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(HTTPException) as error:
        probe(FIXTURES / CLIPS["valid"]["filename"], ".webm", 31.2)
    assert error.value.status_code == 422


@pytest.mark.parametrize("name", ["boundary", "valid"])
def test_actual_browser_bytes_complete_api_media_path_with_test_provider(
    tmp_path, name
):
    from test_attempts import setup
    from uuid import uuid4

    client, headers, session = setup(tmp_path)
    clip = CLIPS[name]
    response = client.post(
        "/api/v1/sessions/" + session["id"] + "/attempts",
        headers=headers | {"Idempotency-Key": str(uuid4())},
        files={
            "audio": (
                "response.webm",
                (FIXTURES / clip["filename"]).read_bytes(),
                clip["type"],
            )
        },
        data={"duration_seconds": str(clip["seconds"])},
    )
    assert response.status_code == 200
    assert abs(response.json()["duration_seconds"] - clip["seconds"]) < 0.15
    assert not list((tmp_path / "audio").glob("*"))
