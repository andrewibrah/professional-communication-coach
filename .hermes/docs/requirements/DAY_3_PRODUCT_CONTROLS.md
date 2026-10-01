# Day 3 — Personalization, Privacy, Quotas, and Progress

## Objective

Turn the Day 2 vertical slice into a controlled private alpha with user personalization, history, transparent progress, deletion controls, and cost protection.

## Build scope

### Professional onboarding

Collect only:

- Current or target role.
- Industry.
- Experience level.
- Primary communication goal.
- Preferred tone.
- Main communication weakness.
- Target customer or audience.
- Optional role-description text.

Do not request sensitive personal, medical, psychological, financial, or government-identification information.

### Scenario personalization

- Tailor scenario context and feedback to the user's professional profile.
- Keep profile facts separate from instructions.
- Support custom scenarios subject to length and safety limits.
- Adjust rubric weights by scenario type.

### Professional progress experience

- Practice history.
- Performance trend.
- Competency progress.
- Attempt-one versus attempt-two comparison.
- Recurring observable communication patterns.
- Highest-priority skill.
- Recommended next scenario.
- Weekly practice count without streak pressure.
- “Apply in your next call” recommendation.

No mascots, XP, confetti, childish badges, or manipulative streak mechanics.

### Safe reflection mode

Identify only observable patterns supported by the user's transcripts, including overexplaining, rushing, hedging, filler words, self-correction, indirect answers, defensive objection responses, weak openings, and excessive jargon.

The system must not diagnose, imply psychological certainty, provide therapy, or infer trauma, attention-deficit/hyperactivity disorder, anxiety disorders, personality disorders, or any other medical or psychological condition.

### Privacy controls

- Delete an individual recording.
- Delete an individual session and associated results.
- Delete all practice history.
- Delete uploaded documents.
- Delete the entire account.
- Default raw-audio deletion after processing and no later than 24 hours unless replay storage is explicitly enabled.

### Cost and abuse controls

- Rate limiting by authenticated user and IP address.
- Daily and monthly practice quotas by plan.
- Per-user usage ledger.
- Maximum audio duration and upload size.
- Account suspension control.
- Global AI-feature kill switch.
- Audit events for security-relevant actions.
- Safe idempotency for expensive processing requests.

## Required tests

- Quota checks occur before expensive AI calls.
- Concurrent requests cannot bypass usage limits.
- Deleted sessions are inaccessible through APIs and signed URLs.
- The account-deletion workflow removes or schedules all owned data according to policy.
- Reflection output always cites transcript evidence and contains no diagnosis.
- Suspended accounts and the global kill switch block AI processing.

## Day 3 acceptance receipt

The alpha supports personalized scenarios, professional progress views, safe reflection, history, complete user deletion controls, enforced quotas, audit records, and an emergency AI shutdown path.
