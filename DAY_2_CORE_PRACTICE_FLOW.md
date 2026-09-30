# Day 2 — Working Practice and Coaching Flow

## Objective

Deliver the complete vertical slice: choose a professional scenario, record a spoken answer in the browser, transcribe it, evaluate it, and retry with a side-by-side comparison.

## Build scope

- Add desktop scenario selection and communication-goal selection.
- Start with a tightly controlled scenario set:
  - Tell me about yourself.
  - Technical job interview.
  - Help-desk troubleshooting call.
  - Cybersecurity explanation for a nontechnical audience.
  - Sales discovery or objection handling.
  - Customer escalation.
- Generate scenario context and one strong, short example response through the backend.
- Record audio through the browser using `MediaRecorder`.
- Enforce a 30–180 second recording boundary.
- Request a short-lived signed upload URL from FastAPI.
- Upload audio directly to a private storage path owned by the authenticated user.
- Validate extension, MIME type, file size, declared duration, actual duration where available, and resource ownership.
- Transcribe audio server-side with OpenAI.
- Evaluate the transcript using a scenario-adjustable professional rubric.
- Request strict structured JSON and validate it with Pydantic before persistence.
- Save only validated reports.
- Show specific strengths, transcript evidence, priority improvement, improved answer, and next-time recommendation.
- Add “try again” and side-by-side attempt comparison.
- Queue temporary audio for deletion according to the retention policy.

## Required coaching schema

- `overall_score`
- `category_scores`
- `communication_strengths`
- `transcript_evidence`
- `filler_words`
- `jargon_flags`
- `pacing_observations`
- `weak_phrasing`
- `missed_questions`
- `priority_improvement`
- `suggested_practice_exercise`
- `improved_answer`
- `next_time_recommendation`

## Prompt-safety boundary

System instructions, evaluation policy, retrieved reference content, scenario context, and transcript text remain distinct. Transcripts and uploaded content are untrusted data and cannot alter authorization, request secrets, reveal hidden prompts, or override system rules.

## Required tests

- Invalid model JSON is rejected and never saved.
- Audio beyond the permitted size or duration is rejected.
- Unsupported and mismatched MIME types are rejected.
- Users cannot process another user's audio or session.
- A prompt-injection statement inside a transcript remains quoted evidence, not an instruction.
- A second attempt is correctly linked to the first session.

## Day 2 acceptance receipt

A verified user can complete the entire browser flow from scenario selection through recording, transcription, validated feedback, improved answer, and a second-attempt comparison using real backend endpoints.
