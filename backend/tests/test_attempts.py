import io
import wave
from uuid import uuid4
from test_flow import client_for


def audio(seconds=30):
    data = io.BytesIO()
    with wave.open(data, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000 * seconds)
    return data.getvalue()


def report():
    return dict(
        overall_score=80,
        category_scores=dict(
            clarity=80,
            structure=80,
            conciseness=80,
            audience_fit=80,
            professional_tone=80,
        ),
        communication_strengths=["Clear opening"],
        transcript_evidence=[{"quote": "Hello", "observation": "Direct greeting"}],
        filler_words=[],
        jargon_flags=[],
        pacing_observations=[],
        weak_phrasing=[],
        missed_questions=[],
        priority_improvement="Give an example",
        suggested_practice_exercise="Practice an example",
        improved_answer="Hello. Here is an example.",
        next_time_recommendation="Lead with your answer",
    )


def setup(tmp_path):
    c = client_for(tmp_path)
    c.app.state.ai.scenario = lambda *args: {
        "context": "A call",
        "example_response": "Hello",
    }
    c.app.state.ai.transcribe = lambda path: "Hello"
    c.app.state.ai.evaluate = lambda *args: report()
    headers = {"Authorization": "Bearer alice"}
    session = c.post(
        "/api/v1/sessions",
        headers=headers,
        json={"scenario_id": "help-desk", "goal": "Clarity"},
    ).json()
    return c, headers, session


def test_recording_to_report_retry_and_idempotency(tmp_path):
    c, h, s = setup(tmp_path)
    url = "/api/v1/sessions/" + s["id"] + "/attempts"
    h = h | {"Idempotency-Key": str(uuid4())}
    payload = {"audio": ("answer.wav", audio(), "audio/wav")}
    first = c.post(url, headers=h, files=payload, data={"duration_seconds": "30"})
    assert first.status_code == 200, first.text
    assert first.json()["report"]["overall_score"] == 80
    assert (
        c.post(url, headers=h, files=payload, data={"duration_seconds": "30"}).json()
        == first.json()
    )
    h["Idempotency-Key"] = str(uuid4())
    second = c.post(url, headers=h, files=payload, data={"duration_seconds": "30"})
    assert second.status_code == 200
    assert second.json()["id"] != first.json()["id"]
    assert len(c.get("/api/v1/sessions/" + s["id"], headers=h).json()["attempts"]) == 2
    assert (
        c.get("/api/v1/sessions", headers=h).json()["sessions"][0]["latest_score"] == 80
    )
    assert c.get("/api/v1/usage", headers=h).json()["daily_used"] == 3
    assert not list((tmp_path / "audio").glob("*"))
