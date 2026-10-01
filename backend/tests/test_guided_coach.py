"""Deterministic controller tests, synthetic generated targets/evidence."""

import importlib
from datetime import datetime, timezone
import pytest
from test_guided_models import ID, feedback


def module():
    try:
        return importlib.import_module("guided_coach")
    except ModuleNotFoundError:
        pytest.fail("Guided deterministic controller is not implemented")


def session():
    c = module()
    return c.new_session(
        ID, "intro", "Clear requests", True, datetime.now(timezone.utc)
    )


def prepared():
    c = module()
    return c.set_prompts(
        session(), ["Please help me.", "Here is the issue.", "Thank you for your help."]
    )


def test_finite_retries_keep_target_then_advance_and_finish():
    c = module()
    s = prepared()
    original = s.prompts[0].id
    for i in range(3):
        s = s.model_copy(update={"state": "listening"})
        f = feedback(prompt_id=original, decision="retry")
        s = c.complete_turn(s, f, "Please help me", f"item-{i}")
        assert len(s.turns) == i + 1
        assert s.turns[-1].attempt == i + 1
        assert s.prompt_index == (0 if i < 2 else 1)
    assert s.prompts[0].id == original
    assert s.prompts[1].id != original
    assert s.attempts_on_prompt == 0
    ended = c.finish(s)
    assert ended.state == "finished"
    assert ended.recap.completed_attempts == 3
    assert ended.recap.practiced_exercises == 1
    assert "score" not in ended.recap.model_dump()


def test_uncertain_replay_visibility_and_duplicate_do_not_create_attempts():
    c = module()
    s = prepared().model_copy(update={"state": "listening"})
    pid = s.prompts[0].id
    s = c.control(s, "visibility", pid, False)
    assert not s.prompt_visible and s.prompts[0].id == pid
    s = c.control(s, "replay", pid)
    assert not s.turns and s.state == "coach_speaking"
    s = s.model_copy(update={"state": "listening"})
    neutral = feedback(
        prompt_id=pid,
        strength=None,
        evidence_quote=None,
        evidence_basis="uncertain",
        decision="clarify",
        spoken_feedback="Please repeat the whole sentence.",
    )
    uncertain = c.complete_turn(s, neutral, "fragment", "item-uncertain")
    assert uncertain.attempts_on_prompt == 0 and not uncertain.turns
    completed = c.complete_turn(s, feedback(prompt_id=pid), "Please help", "item-1")
    assert (
        c.complete_turn(completed, feedback(prompt_id=pid), "Please help", "item-1")
        == completed
    )
    with pytest.raises(ValueError):
        c.control(s, "replay", ID)
    with pytest.raises(ValueError):
        c.set_prompts(session(), ["one", "two"])
    with pytest.raises(ValueError):
        c.set_prompts(session(), ["x" * 241, "two", "three"])


def test_done_disables_listening_while_asr_is_pending():
    c = module()
    s = prepared().model_copy(update={"state": "listening"})
    updated = c.control(s, "done", s.prompts[0].id)
    assert updated.state == "reviewing" and not updated.turns
