"""Guided Voice wire contracts. No provider/lease/auth handles belong here."""

from datetime import datetime
import re
from typing import Annotated, Literal
from uuid import UUID
from pydantic import AfterValidator, Field, model_validator
from models import StrictModel


def canonical_uuid(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("Canonical lowercase UUID required")
    return value


CanonicalID = Annotated[str, AfterValidator(canonical_uuid)]
State = Literal[
    "created",
    "connecting",
    "coach_speaking",
    "listening",
    "reviewing",
    "paused",
    "reconnecting",
    "finished",
    "failed",
]
Decision = Literal["retry", "next", "simplify", "finish", "clarify"]
Action = Literal[
    "replay",
    "retry",
    "done",
    "pause",
    "resume",
    "mute",
    "unmute",
    "finish",
    "visibility",
    "reconnect",
]
ShortText = Annotated[str, Field(min_length=1, max_length=400)]
# MVP evaluates transcript wording, not acoustic qualities.
AUDIO_CLAIMS = re.compile(
    r"\b(pronunc\w*|enunciat\w*|prosody|intonation|pitch|volume|pacing|pace|accent|cadence|rhythm|loud\w*|softly|voice|audio|speaking speed|vocal|sounded|sound clear|slow down|slowly|slower|speak faster|vocal emphasis)\b",
    re.I,
)


class CreateInput(StrictModel):
    command_id: CanonicalID
    scenario_id: str = Field(min_length=1, max_length=50)
    goal: str = Field(min_length=1, max_length=1000)
    context: str = Field(default="", max_length=4000)
    prompt_visible: bool = True


class ConnectionInput(StrictModel):
    command_id: CanonicalID
    expected_revision: int = Field(ge=0)
    sdp: str = Field(min_length=1, max_length=24000)


class CommandInput(StrictModel):
    command_id: CanonicalID
    expected_revision: int = Field(ge=0)
    prompt_id: CanonicalID | None
    action: Action
    prompt_visible: bool | None = None

    @model_validator(mode="after")
    def visibility(self):
        if (self.action == "visibility") != (self.prompt_visible is not None):
            raise ValueError("Visibility value only belongs to visibility command")
        return self


class Feedback(StrictModel):
    prompt_id: CanonicalID
    strength: ShortText | None
    priority_correction: ShortText | None
    corrected_example: ShortText | None
    decision: Decision
    evidence_basis: Literal["transcript", "uncertain"]
    evidence_quote: ShortText | None
    spoken_feedback: ShortText

    @model_validator(mode="after")
    def evidence_only(self):
        fields = [
            self.strength,
            self.priority_correction,
            self.corrected_example,
            self.spoken_feedback,
        ]
        if sum(len(s) for s in fields if s) > 400:
            raise ValueError("Feedback too long")
        if any(AUDIO_CLAIMS.search(s) for s in fields if s):
            raise ValueError("Transcript wording only")
        if len(re.findall(r"[.!?]+(?:\s|$)", self.spoken_feedback)) > 3:
            raise ValueError("At most three short sentences")
        if (
            self.priority_correction
            and len(re.findall(r"[.!?]+(?:\s|$)", self.priority_correction)) > 1
        ):
            raise ValueError("One correction only")
        if self.strength and not self.evidence_quote:
            raise ValueError("Strength requires evidence")
        if self.evidence_basis == "uncertain" and (
            self.decision != "clarify"
            or any(
                (
                    self.strength,
                    self.priority_correction,
                    self.corrected_example,
                    self.evidence_quote,
                )
            )
        ):
            raise ValueError("Uncertain evidence requires neutral clarification")
        if self.decision == "clarify" and self.evidence_basis != "uncertain":
            raise ValueError("Clarification is not a confident attempt")
        return self


def validate_feedback(data, prompt_id: str, transcript: str) -> Feedback:
    result = Feedback.model_validate(data)
    if result.prompt_id != prompt_id or (
        result.evidence_quote and result.evidence_quote not in transcript
    ):
        raise ValueError("Evidence does not match current transcript")
    return result


class Prompt(StrictModel):
    id: CanonicalID
    text: str = Field(min_length=1, max_length=240)
    exercise_type: Literal["repetition"] = "repetition"
    position: int = Field(ge=0, le=2)


class Turn(StrictModel):
    id: CanonicalID
    prompt_id: CanonicalID
    provider_item_id: str = Field(min_length=1, max_length=200)
    attempt: int = Field(ge=1, le=3)
    transcript: str = Field(min_length=1, max_length=4000)
    feedback: Feedback
    prompt_visible: bool
    created_at: str

    @model_validator(mode="after")
    def evidence(self):
        validate_feedback(self.feedback.model_dump(), self.prompt_id, self.transcript)
        if self.feedback.evidence_basis != "transcript":
            raise ValueError("Only confident completed turns are saved")
        return self


class Recap(StrictModel):
    practiced_exercises: int = Field(ge=0, le=3)
    completed_attempts: int = Field(ge=0, le=9)
    focus: ShortText
    next_practice: ShortText


class GuidedSession(StrictModel):
    id: CanonicalID
    scenario_id: str = Field(min_length=1, max_length=50)
    goal: str = Field(min_length=1, max_length=1000)
    created_at: str
    expires_at: str
    state: State
    revision: int = Field(ge=0)
    prompt_visible: bool
    muted: bool
    max_retries: int = Field(default=2, ge=0, le=2)
    prompts: list[Prompt] = Field(max_length=3)
    prompt_index: int = Field(ge=0, le=2)
    attempts_on_prompt: int = Field(ge=0, le=3)
    turns: list[Turn] = Field(max_length=9)
    recap: Recap | None
    status_message: str = Field(max_length=400)

    @model_validator(mode="after")
    def coherent(self):
        start, end = (
            datetime.fromisoformat(self.created_at),
            datetime.fromisoformat(self.expires_at),
        )
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or end <= start
            or (end - start).total_seconds() > 300
        ):
            raise ValueError("Bounded aware session lifetime required")
        if self.prompts and (
            len(self.prompts) != 3 or self.prompt_index >= len(self.prompts)
        ):
            raise ValueError("Exactly three target sentences required")
        ids = [p.id for p in self.prompts]
        if len(set(ids)) != len(ids) or [p.position for p in self.prompts] != list(
            range(len(ids))
        ):
            raise ValueError("Unique ordered prompts required")
        seen = set()
        for turn in self.turns:
            if turn.prompt_id not in ids or turn.provider_item_id in seen:
                raise ValueError("Invalid or duplicate turn")
            seen.add(turn.provider_item_id)
        return self


# Explicit aliases for adapters/consumers; all have the same strict projection.
SessionDTO = GuidedSession
GuidedSessionDTO = GuidedSession


class ConnectionOutput(StrictModel):
    sdp: str = Field(min_length=1, max_length=24000)
    session: GuidedSession


class SessionCollection(StrictModel):
    sessions: list[GuidedSession]
