"""Pure bounded controller. Provider suggestions cannot increase attempt budgets."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from guided_models import GuidedSession, Prompt, Turn, Recap, validate_feedback

TERMINAL = {"finished", "failed"}


def changed(session, **values):
    return GuidedSession.model_validate(session.model_dump() | values)


def new_session(id, scenario_id, goal, prompt_visible, now=None, max_retries=2):
    now = now or datetime.now(timezone.utc)
    return GuidedSession(
        id=id,
        scenario_id=scenario_id,
        goal=goal,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=300)).isoformat(),
        state="created",
        revision=0,
        prompt_visible=prompt_visible,
        muted=False,
        max_retries=max_retries,
        prompts=[],
        prompt_index=0,
        attempts_on_prompt=0,
        turns=[],
        recap=None,
        status_message="Preparing three short sentences.",
    )


def set_prompts(session, sentences):
    if (
        not isinstance(sentences, list)
        or len(sentences) != 3
        or any(not isinstance(text, str) or not text.strip() for text in sentences)
    ):
        raise ValueError("Exactly three short target sentences required")
    prompts = [
        Prompt(id=str(uuid4()), text=text, position=i)
        for i, text in enumerate(sentences)
    ]
    return changed(
        session,
        prompts=[p.model_dump() for p in prompts],
        status_message="Ready to connect.",
    )


def current_prompt(session):
    if not session.prompts:
        raise ValueError("Targets not ready")
    return session.prompts[session.prompt_index]


def target_speech(session, orientation=False):
    prefix = (
        "Let's practice a short sentence. " if orientation else "Repeat this sentence. "
    )
    return prefix + current_prompt(session).text


def finish(session, failed=False):
    if session.state in TERMINAL:
        return session
    corrections = [
        t.feedback.priority_correction
        for t in session.turns
        if t.feedback.priority_correction
    ]
    recap = Recap(
        practiced_exercises=len({t.prompt_id for t in session.turns}),
        completed_attempts=len(session.turns),
        focus=corrections[-1] if corrections else "Practice clear wording.",
        next_practice="Repeat the target sentences using the same clear wording.",
    )
    return changed(
        session,
        state="failed" if failed else "finished",
        recap=recap.model_dump(),
        status_message="Practice ended."
        if not failed
        else "Connection ended safely. Please reconnect in a new session.",
    )


def control(session, action, prompt_id=None, prompt_visible=None):
    if action == "finish":
        return finish(session)
    if session.state in TERMINAL:
        raise ValueError("Practice already ended")
    if prompt_id is not None and prompt_id != current_prompt(session).id:
        raise ValueError("Stale prompt")
    if (
        action in {"retry", "replay", "done", "visibility"}
        and prompt_id != current_prompt(session).id
    ):
        raise ValueError("Current prompt required")
    if action == "visibility":
        if type(prompt_visible) is not bool:
            raise ValueError("Visibility required")
        return changed(session, prompt_visible=prompt_visible)
    if action in {"replay", "retry"}:
        allowed = (
            {"listening", "coach_speaking"} if action == "replay" else {"listening"}
        )
        if (
            session.state not in allowed
            or session.attempts_on_prompt >= session.max_retries + 1
        ):
            raise ValueError("Replay unavailable")
        return changed(
            session,
            state="coach_speaking",
            status_message="Listen to the same target sentence.",
        )
    if action == "pause":
        return changed(
            session,
            state="paused",
            status_message="Paused. Resume requires a fresh connection.",
        )
    if action in {"resume", "reconnect"}:
        if action == "resume" and session.state != "paused":
            raise ValueError("Practice is not paused")
        return changed(
            session,
            state="reconnecting",
            status_message="Reconnect to hear the current sentence again.",
        )
    if action in {"mute", "unmute"}:
        return changed(session, muted=action == "mute")
    if action == "done" and session.state == "listening":
        return changed(
            session, state="reviewing", status_message="Confirming the sentence."
        )
    raise ValueError("Control unavailable")


def complete_turn(session, feedback, transcript, provider_item_id, now=None):
    if any(t.provider_item_id == provider_item_id for t in session.turns):
        return session
    if session.state not in {"listening", "reviewing"} or session.muted:
        raise ValueError("Not accepting input")
    prompt = current_prompt(session)
    result = validate_feedback(feedback, prompt.id, transcript)
    if result.evidence_basis == "uncertain":
        return changed(
            session, state="coach_speaking", status_message=result.spoken_feedback
        )
    attempt = session.attempts_on_prompt + 1
    turn = Turn(
        id=str(uuid4()),
        prompt_id=prompt.id,
        provider_item_id=provider_item_id,
        attempt=attempt,
        transcript=transcript,
        feedback=result,
        prompt_visible=session.prompt_visible,
        created_at=(now or datetime.now(timezone.utc)).isoformat(),
    )
    updated = changed(
        session,
        turns=[t.model_dump() for t in session.turns] + [turn.model_dump()],
        attempts_on_prompt=attempt,
        state="coach_speaking",
        status_message=result.spoken_feedback,
    )
    if result.decision == "finish":
        return finish(updated)
    if result.decision == "next" or attempt == session.max_retries + 1:
        if session.prompt_index == 2:
            return finish(updated)
        return changed(
            updated, prompt_index=session.prompt_index + 1, attempts_on_prompt=0
        )
    # "simplify" changes explanatory wording only, never the immutable target/rubric.
    return updated
