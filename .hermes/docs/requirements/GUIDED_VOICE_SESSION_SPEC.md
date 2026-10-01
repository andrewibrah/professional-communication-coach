# Guided Voice Session — Product Specification

Status: approved planning deliverable, not implemented functionality.
Project: /Users/me/Desktop/professional-communication-coach

## 1. Goal and scope

Evolve SpeechClear from only “user records, stops, submits, reads a report” into an additional guided, call-like practice mode: AI speaks a short prompt, user speaks back, AI provides brief actionable feedback, and AI either requests another attempt or introduces the next prompt. Preserve the existing Recorded Practice mode and its 30–180-second validation/report contract.

This is an in-browser voice session, not a telephone call. Telephony, outbound calling, avatars, pronunciation scoring with false precision, and unrestricted general-purpose chat are out of scope. Do not substitute browser speech synthesis or prerecorded examples for a real live voice provider and claim the target complete.

The minimum release contains repeat-after-me drills. Its data contract distinguishes repetition from later paraphrase and scenario-answer exercises so exact-word matching is not mistakenly used to judge every exercise. Do not implement later exercise types at the expense of completing repetition.

## 2. Entry and session setup

Practice studio exposes two clearly labeled modes: Recorded Practice and Guided Voice. Guided setup reuses scenario, communication goal, and appropriate professional profile context. It adds a visible prompt preference, default Show Prompt, and a clear Start guided session action.

Explain before starting: an AI coach will speak; microphone audio is sent to the voice provider while listening; saved practice data includes prompts, transcripts, and coaching feedback; raw audio is not permanently retained by this application. Do not promise provider zero retention unless its actual configured policy supports that promise.

Starting requires an authenticated, confirmed account, available AI/provider configuration, ready persistence, active account controls, and available guided usage allowance. Request microphone permission only following an explicit user action. A denied microphone, unavailable provider, or setup failure produces an honest recoverable message, not a fake working session.

## 3. Core experience

1. Coach introduces the exercise briefly and speaks one short target sentence.
2. UI indicates Coach speaking, then Your turn.
3. User responds without pressing Record/Send for every turn.
4. Completion detection or the fallback I'm done control ends the turn.
5. Coach acknowledges one concrete strength where supported, identifies at most one priority correction, and demonstrates corrected wording when useful.
6. Coach explicitly says Repeat that sentence or moves to the next exercise.
7. The loop continues until user ends, the planned exercise budget ends, or a server-enforced limit is reached.
8. End screen shows a concise recap: practiced exercises, progress supported by evidence, one remaining focus, and next practice recommendation.

Example interaction, illustrative copy only, never seeded as runtime user evidence:
- Coach: “Repeat: I help customers solve technical problems with clear, practical support.”
- User repeats.
- Coach: “Your wording was clear. Slow down on the last phrase. Try the same sentence again.”
- User repeats.
- Coach: “That was easier to follow. Next sentence…”

Default coaching output should fit roughly one to three short sentences, not a full report. Instructions enforce brevity and structured limits; tests and live review check actual output. Avoid praise unsupported by audio/transcript evidence. Never infer personality, diagnoses, or mental health.

## 4. Exercise identity and retry policy

The application owns a canonical prompt ID and exact target text. Spoken target, displayed target, transcript evaluation, and saved turn all reference that prompt. Replay must speak the same target; retry must retain its identity. A changed target creates a new prompt/version, not a silent mutation of the current exercise.

Default: permit two correction-driven retries after the initial attempt, then offer a shorter variant or move on. Make this configurable server-side, not a client-authoritative limit. A user-requested replay is not an evaluated attempt. No infinite retry loops.

For repetition, evaluate meaningful omissions/changes and audible delivery where reliable. If recognition is uncertain, request repetition or clarification rather than mark failure. Distinguish an incomplete response, no speech, unclear audio, and a completed attempt. For later paraphrase exercises, preserve meaning rather than exact words.

## 5. Show Prompt / Hide Prompt memory practice

A prominent toggle is available before and during the call. Show Prompt displays the exact current target. Hide Prompt replaces it with neutral copy such as “Listen, then repeat from memory.” Toggle state persists throughout the current session, including recoverable reconnect; no sensitive prompt/transcript content goes into browser persistent storage.

Changing visibility never changes prompt identity, starts a new attempt, resets the call, or modifies the evaluation rubric. Record the visibility used for an evaluated turn as context, not as a fabricated separate ability score.

Hide target text from the rendered prompt, accessibility tree, live coach captions, corrected-example text, and in-session transcript/history panels while hidden mode is active. This is a practice UI feature, not a secrecy or authorization boundary: a user can inspect client network traffic. After the session ends, saved history can show prompts under normal owner-scoped access.

Keep status, generic feedback, controls, and timer visible. If a feedback sentence quotes or reconstructs the target, suppress that text in hidden mode while allowing its audio demonstration. Use structured fields rather than brittle keyword replacement. Support keyboard operation, accessible toggle state, and sensible focus behavior. Never use an aria-live region to announce the hidden target.

## 6. Controls and interruption semantics

- Replay prompt: cancel obsolete playback and replay the canonical target without scoring an attempt.
- Try again: begin another allowed attempt on the same prompt.
- I'm done: fallback end-of-turn action when automatic detection waits too long.
- Pause: stop audio playback and microphone transmission, freeze progression, discard partial input unless explicitly marked recoverable. Server confirms paused state; an idle/grace limit still bounds cost.
- Resume: re-establish required audio resources with a gesture where needed and repeat orientation without duplicating a completed attempt.
- Mute: stop outbound microphone audio; output can continue. Muted silence is not a failed attempt.
- End: immediately stop local microphone/playback, request server termination, and save/return recap if available. Failure saving recap must not keep the microphone active.
- Navigation, logout, account change, unmount, provider error, and terminal limit: teardown audio tracks, peer connection, data channel, timers/listeners, and pending requests. Backend watchdog terminates orphan sessions.

First release uses controlled turn-taking. During ordinary target playback, gate evaluation/listening so speaker echo is not scored. Replay/end/pause can interrupt immediately. Optional natural barge-in is enabled only if cancellation, partial playback, context synchronization, and echo tests pass; it is not required to call the controlled drill complete.

## 7. States and recovery

Canonical progression states: created, connecting, coach_speaking, listening, reviewing, paused, reconnecting, finished, failed. Backend persists business progression; browser adds transport-specific connecting/playback states without granting itself trusted scoring authority.

No overlapping evaluated turns. Every command includes session ID, prompt ID, command ID, and expected revision as appropriate. Ignore or reject stale/duplicate events. Late transcript fragments cannot overwrite a completed turn or resurrect a deleted/ended session.

For brief thinking silence, wait patiently. After configured no-speech timeout, ask “Would you like to hear it again?” without saving a scored failure. Silence timeout and I'm done behavior must be validated against actual provider events. Disconnect: stop outbound audio, display recovery state, reconnect only within a bounded server lease, fetch authoritative prompt/revision, and never automatically resubmit ambiguous completed work.

## 8. Feedback contract and evidence

Store validated bounded fields: strength (optional), priority_correction (optional), corrected_example (optional), decision (retry/next/simplify/finish/clarify), evidence_basis (transcript/audio/uncertain), prompt_id, and short spoken feedback. The controller validates decisions against allowed state and retry budget. Provider suggestions are data, not authorization.

Exact transcript citations must actually occur in the recognized transcript. Transcript supports wording and structure, not pronunciation, emphasis, pitch, or emotional certainty. Audio-grounded delivery feedback must come from actual audio-capable evaluation, acknowledge uncertain input, and avoid invented numeric precision. No score is required for MVP; do not mix guided qualitative progress into existing Recorded Practice /100 averages.

## 9. Security, privacy, and persistence

Permanent provider credentials and Supabase privileged credentials remain backend-only. Reuse verified identity, confirmed-email policy, suspension, kill switch, owner checks, and safe errors. Session creation/configuration and trusted results are backend-authorized. Client-reported feedback/usage is not trusted evidence.

Persist guided sessions/prompts/turns and usage independently of recorded attempt/report tables. Short guided turns must not require relaxing Recorded Practice media/upload/SQL constraints. Owner isolation applies to reads, commands, reconnect, history, summaries, and deletes. Raw audio streaming need not pass through permanent application Storage. If temporary recording is required for evidence, bound it, obtain appropriate consent, and guarantee cleanup; never expose object paths or signed URLs.

Use atomic usage reservations, maximum active sessions per user, maximum session duration, idle/grace timeouts, and token/audio/minute budgets supported by provider usage. A browser timer alone cannot enforce spending. Server must actually terminate provider session/media access at limits; prove the chosen provider lifecycle supports this. Retain trusted usage/termination evidence without recording secrets or private content in logs.

## 10. Acceptance matrix

Every item needs an evidence reference, not an unchecked claim:
- Entry, confirmed auth, and honest unavailable state.
- Real microphone -> real voice provider -> audible coach playback.
- Automatic prompt/response/brief-feedback/retry/next loop.
- Canonical prompt synchronization and finite retry policy.
- Hidden target absent from rendered/caption/accessibility/history surfaces.
- Replay/toggle do not count attempts or lose state.
- Silence, unclear audio, partial response, mute, and I'm done handled correctly.
- Pause/end/navigation/logout release resources; orphan server sessions terminate.
- Duplicate/out-of-order/disconnect events do not corrupt progression.
- Owner isolation, privileged writes, concurrency quotas, and spending enforcement.
- Dedicated persistence/history/deletion and honest qualitative recap.
- Original Recorded Practice tests and behavior preserved.
- Automated frontend/backend/real-SQL checks plus authorized real browser/provider proof.

Existing direction pauses live-account participation until Master Andrew authorizes it. A request to prepare these documents does not revoke that boundary. Future executor must distinguish implemented local functionality from blocked live acceptance gates and obtain secure participation when needed.
