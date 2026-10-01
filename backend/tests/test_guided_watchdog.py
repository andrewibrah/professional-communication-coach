"""Real disposable SQL watchdog recap proof; synthetic user/evidence only."""

import pytest
from scripts.verify_postgres import disposable_database
from test_guided_postgres import A, B, S, reserve, prompt, turn, commit, rpc


@pytest.fixture
def db():
    with disposable_database() as database:
        database.sql(f"INSERT INTO auth.users VALUES ('{A}'),('{B}');")
        yield database


def test_watchdog_termination_retains_honest_recap_from_saved_turns(db):
    base = reserve(db)
    saved_turn = turn()
    saved_turn["feedback"]["priority_correction"] = "Keep the complete wording."
    saved = commit(
        db,
        base
        | {
            "state": "reviewing",
            "prompts": [prompt()],
            "turns": [saved_turn],
            "attempts_on_prompt": 1,
        },
    )
    db.sql(
        f"UPDATE speechclear_private.guided_reservations SET heartbeat_at=clock_timestamp()-interval '21 seconds' WHERE id='{S}';"
    )
    rpc(db, "watchdog", None)
    ended = rpc(db, "get", A, {"id": S})
    assert ended["state"] == "failed" and ended["revision"] == saved["revision"] + 1
    assert ended["recap"] == {
        "practiced_exercises": 1,
        "completed_attempts": 1,
        "focus": "Keep the complete wording.",
        "next_practice": "Repeat the target sentences using the same clear wording.",
    }
    rpc(db, "watchdog", None)
    assert rpc(db, "get", A, {"id": S}) == ended
