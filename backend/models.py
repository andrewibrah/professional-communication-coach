from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionInput(StrictModel):
    scenario_id: str = Field(max_length=50)
    goal: str = Field(min_length=1, max_length=1000)
    custom_context: str = Field(default="", max_length=4000)


class ScenarioOutput(StrictModel):
    context: str = Field(min_length=1, max_length=5000)
    example_response: str = Field(min_length=1, max_length=5000)


Score = Annotated[int, Field(ge=0, le=100)]
Text = Annotated[str, Field(min_length=1, max_length=6000)]


class CategoryScores(StrictModel):
    clarity: Score
    structure: Score
    conciseness: Score
    audience_fit: Score
    professional_tone: Score


class Evidence(StrictModel):
    quote: Text
    observation: Text


class Filler(StrictModel):
    word: Text
    count: Annotated[int, Field(ge=0, le=10000)]


class Report(StrictModel):
    overall_score: Score
    category_scores: CategoryScores
    communication_strengths: list[Text] = Field(max_length=30)
    transcript_evidence: list[Evidence] = Field(min_length=1, max_length=30)
    filler_words: list[Filler] = Field(max_length=100)
    jargon_flags: list[Text] = Field(max_length=30)
    pacing_observations: list[Text] = Field(max_length=30)
    weak_phrasing: list[Text] = Field(max_length=30)
    missed_questions: list[Text] = Field(max_length=30)
    priority_improvement: Text
    suggested_practice_exercise: Text
    improved_answer: Text
    next_time_recommendation: Text


class Profile(StrictModel):
    role: str = Field(default="", max_length=200)
    industry: str = Field(default="", max_length=200)
    experience_level: str = Field(default="", max_length=200)
    goal: str = Field(default="", max_length=1000)
    tone: str = Field(default="", max_length=200)
    weakness: str = Field(default="", max_length=1000)
    audience: str = Field(default="", max_length=500)
    role_description: str = Field(default="", max_length=4000)
