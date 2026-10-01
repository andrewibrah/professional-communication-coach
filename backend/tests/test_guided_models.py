"""Pure schema tests: synthetic text only, no identity/provider calls."""

import importlib
import pytest
from pydantic import ValidationError

ID = "12345678-1234-4234-8234-123456789abc"


def module():
    try:
        return importlib.import_module("guided_models")
    except ModuleNotFoundError:
        pytest.fail("Guided strict models are not implemented")


def feedback(**changes):
    return (
        dict(
            prompt_id=ID,
            strength="Clear request.",
            priority_correction=None,
            corrected_example=None,
            decision="next",
            evidence_basis="transcript",
            evidence_quote="Please help",
            spoken_feedback="Your request is clear.",
        )
        | changes
    )


def test_feedback_requires_exact_fields_and_evidence():
    m = module()
    assert m.Feedback.model_validate(feedback()).decision == "next"
    for bad in [
        feedback(score=90),
        feedback(prompt_id=ID.upper()),
        feedback(evidence_quote=None),
        feedback(decision="pass"),
        feedback(spoken_feedback="Your pronunciation is excellent."),
        feedback(spoken_feedback="Slow down on the final phrase."),
        feedback(spoken_feedback="Speak more slowly."),
        feedback(priority_correction="Use stronger vocal emphasis."),
        feedback(spoken_feedback="One. Two. Three. Four."),
        feedback(spoken_feedback="x" * 401),
        feedback(evidence_basis="uncertain", decision="retry"),
    ]:
        with pytest.raises(ValidationError):
            m.Feedback.model_validate(bad)
    with pytest.raises(ValueError):
        m.validate_feedback(feedback(), ID, "Different wording")
    assert m.validate_feedback(feedback(), ID, "Please help me").strength


def test_command_schema_rejects_forged_results_and_coercion():
    m = module()
    valid = dict(command_id=ID, expected_revision=0, prompt_id=None, action="finish")
    assert m.CommandInput.model_validate(valid).action == "finish"
    for changes in [
        dict(transcript="forged"),
        dict(expected_revision=True),
        dict(expected_revision="0"),
        dict(command_id=ID.upper()),
        dict(action="playback_done"),
        dict(prompt_visible=True),
    ]:
        with pytest.raises(ValidationError):
            m.CommandInput.model_validate(valid | changes)
    with pytest.raises(ValidationError):
        m.ConnectionInput.model_validate(
            dict(command_id=ID, expected_revision=0, sdp="x" * 24001)
        )
    with pytest.raises(ValidationError):
        m.CreateInput.model_validate(
            dict(
                command_id=ID,
                scenario_id="intro",
                goal="a",
                context="",
                prompt_visible="true",
            )
        )
