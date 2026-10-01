import subprocess
from uuid import uuid4
import pytest
from test_attempts import setup, audio, report


@pytest.mark.parametrize(
    "name,mime,data,duration,status",
    [
        ("x.wav", "audio/wav", b"bad", "30", 422),
        ("x.wav", "audio/webm", audio(), "30", 415),
        ("x.webm", "audio/webm", audio(), "30", 422),
        ("x.wav", "audio/wav", audio(1), "30", 422),
        ("x.wav", "audio/wav", audio(), "nan", 422),
        ("x.wav", "audio/wav", audio(), "180", 422),
        ("x.wav", "audio/wav", b"x" * 12582913, "30", 413),
    ],
)
def test_invalid_media_never_calls_ai(tmp_path, name, mime, data, duration, status):
    c, h, s = setup(tmp_path)

    def forbidden(*args):
        pytest.fail("AI called for invalid media")

    c.app.state.ai.transcribe = forbidden
    response = c.post(
        "/api/v1/sessions/" + s["id"] + "/attempts",
        headers=h | {"Idempotency-Key": str(uuid4())},
        files={"audio": (name, data, mime)},
        data={"duration_seconds": duration},
    )
    assert response.status_code == status, response.text
    assert c.get("/api/v1/usage", headers=h).json()["daily_used"] == 1
    assert not list((tmp_path / "audio").glob("*"))


@pytest.mark.parametrize(
    "invalid",
    [
        {"overall_score": 100},
        report() | {"overall_score": "80"},
        report() | {"unexpected": "field"},
        report()
        | {"transcript_evidence": [{"quote": "not spoken", "observation": "claim"}]},
    ],
)
def test_invalid_reports_never_persist(tmp_path, invalid):
    c, h, s = setup(tmp_path)
    c.app.state.ai.evaluate = lambda *args: invalid
    url = "/api/v1/sessions/" + s["id"] + "/attempts"
    key = str(uuid4())
    headers = h | {"Idempotency-Key": key}
    response = c.post(
        url,
        headers=headers,
        files={"audio": ("a.wav", audio(), "audio/wav")},
        data={"duration_seconds": "30"},
    )
    assert response.status_code == 502
    assert c.get("/api/v1/sessions/" + s["id"], headers=h).json()["attempts"] == []
    assert not list((tmp_path / "audio").glob("*"))
    assert (
        c.post(
            url,
            headers=headers,
            files={"audio": ("a.wav", audio(), "audio/wav")},
            data={"duration_seconds": "30"},
        ).status_code
        == 409
    )


def test_browser_webm_without_duration_is_accepted(tmp_path):
    from media import probe

    path = tmp_path / "browser.webm"
    # Non-seekable muxing replicates MediaRecorder's missing container duration.
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "30.1",
            "-c:a",
            "libopus",
            "-f",
            "webm",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    path.write_bytes(result.stdout)
    assert 30 <= probe(path, ".webm", 30.1) <= 31
