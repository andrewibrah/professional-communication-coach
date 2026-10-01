from uuid import uuid4
import pytest
from fastapi import HTTPException
from test_attempts import setup, audio


@pytest.mark.parametrize("operation", ["scenario", "attempt"])
def test_reservation_rechecks_suspension_atomically(tmp_path, operation):
    from store import Store

    store = Store(str(tmp_path / "db"))
    store.save_session("alice", {"id": "session"})
    store.suspend("alice", True)
    with pytest.raises(HTTPException) as error:
        if operation == "scenario":
            store.reserve("alice", 20, 200)
        else:
            store.begin_attempt("alice", "session", "key", 20, 200)
    assert error.value.status_code == 403
    assert store.usage("alice", 20, 200)["daily_used"] == 0


@pytest.mark.parametrize("control,status", [("kill_switch", 503), ("suspension", 403)])
def test_control_changed_during_transcription_blocks_evaluation(
    tmp_path, control, status
):
    c, h, s = setup(tmp_path)

    def transcribe(path):
        if control == "kill_switch":
            c.app.state.settings.ai_enabled = False
        else:
            c.app.state.store.suspend("alice", True)
        return "Hello"

    def forbidden(*args):
        pytest.fail("Evaluation invoked after AI access was disabled")

    c.app.state.ai.transcribe = transcribe
    c.app.state.ai.evaluate = forbidden
    key = str(uuid4())
    result = c.post(
        "/api/v1/sessions/" + s["id"] + "/attempts",
        headers=h | {"Idempotency-Key": key},
        files={"audio": ("a.wav", audio(), "audio/wav")},
        data={"duration_seconds": "30"},
    )
    assert result.status_code == status
    assert c.app.state.store.attempts("alice", s["id"]) == []
    with c.app.state.store.connect() as db:
        assert (
            db.execute("SELECT state FROM operations WHERE key=?", (key,)).fetchone()[0]
            == "failed"
        )
    assert not list((tmp_path / "audio").glob("*"))


def test_kill_switch_changed_during_email_check_blocks_generation(tmp_path):
    c, h, _ = setup(tmp_path)

    def verify_email(*args):
        c.app.state.settings.ai_enabled = False

    def forbidden(*args):
        pytest.fail("Generation invoked after AI access was disabled")

    c.app.state.auth.require_confirmed = verify_email
    c.app.state.ai.scenario = forbidden
    response = c.post(
        "/api/v1/sessions",
        headers=h,
        json={"scenario_id": "help-desk", "goal": "Clear"},
    )
    assert response.status_code == 503
    assert c.app.state.store.usage("alice", 20, 200)["daily_used"] == 1
