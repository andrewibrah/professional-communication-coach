# SpeechClear documentation index

Project root: `/Users/me/Desktop/professional-communication-coach`.

All authored project documentation lives here. Source code, SQL migrations, credentials, runtime data and protected migration backups remain outside this documentation tree. Never place credentials, signed URLs, private recordings, transcripts or exported user rows in these docs.

## Start here

For nontechnical users: [SpeechClear user guide](guides/SPEECHCLEAR_USER_GUIDE.md) — account setup, both practice modes, feedback, troubleshooting, and a before-and-after improvement routine.

Current Supabase implementation/cutover: [verified handoff and blocked acceptance gates](handoffs/SUPABASE_IMPLEMENTATION_HANDOFF.md).

1. [Build checkpoint](handoffs/BUILD_CHECKPOINT.md) — continuity handoff, not proof of current state.
2. [Engineering work log](execution/doc.md) — canonical implementation and verification trail.
3. [Completion requirements](requirements/SUPABASE_COMPLETION_PROMPT.md) — required security and evidence gates.
4. [Security corrections](verification/SECURITY_CORRECTIONS.md) — review findings and correction evidence.

## Folder map

- `overview/` — product overview and historical architecture.
- `guides/` — user-facing instructions and practical practice routines.
- `requirements/` — four-day specifications, implementation contract and completion checklist.
- `setup/` — environment and Supabase setup instructions.
- `handoffs/` — resumable checkpoint and historical completion report.
- `execution/` — canonical engineering work log.
- `verification/` — focused implementation, testing and migration/cutover evidence.

## Product and requirements

- [Guided Voice feature specification](requirements/GUIDED_VOICE_SESSION_SPEC.md) — desired experience and acceptance gates.
- [Guided Voice Hermes instructions](execution/GUIDED_VOICE_HERMES_INSTRUCTIONS.md) — execution discipline, permissions, and evidence rules.
- [Guided Voice implementation plan](execution/GUIDED_VOICE_IMPLEMENTATION_PLAN.md) — ordered implementation tasks and verification.
- [Product overview](overview/README.md)
- [Day 1: secure foundation](requirements/DAY_1_SECURE_FOUNDATION.md)
- [Day 2: core practice flow](requirements/DAY_2_CORE_PRACTICE_FLOW.md)
- [Day 3: product controls](requirements/DAY_3_PRODUCT_CONTROLS.md)
- [Day 4: testing and release](requirements/DAY_4_TESTING_RELEASE.md)
- [API and implementation contract](requirements/IMPLEMENTATION_CONTRACT.md)
- [Supabase completion checklist](requirements/SUPABASE_COMPLETION_PROMPT.md)
- [Supabase setup](setup/SUPABASE_SETUP.md)

## Implementation and verification

- [Backend verification](verification/BACKEND_VERIFICATION.md)
- [Frontend verification](verification/FRONTEND_VERIFICATION.md)
- [Frontend Storage handshake](verification/FRONTEND_STORAGE_IMPLEMENTATION.md)
- [Persistence adapter and protected export](verification/PERSISTENCE_IMPLEMENTATION.md)
- [PostgreSQL schema and atomic RPC](verification/SCHEMA_IMPLEMENTATION.md)
- [FastAPI integration](verification/APP_INTEGRATION.md)
- [Import and cutover](verification/PERSISTENCE_CUTOVER.md)
- [Security corrections](verification/SECURITY_CORRECTIONS.md)
- [Guided Voice verification](verification/GUIDED_VOICE_VERIFICATION.md) — implementation/development evidence and explicitly blocked live acceptance.
- [Historical completion report](handoffs/SUPABASE_COMPLETION_REPORT.md)
- [Current Supabase implementation handoff](handoffs/SUPABASE_IMPLEMENTATION_HANDOFF.md)

## Evidence rules

A document title or checkbox does not establish completion. Distinguish static inspection, test doubles, real disposable PostgreSQL, live Supabase operations, and authenticated browser/provider evidence. Historical receipts must be rechecked after code changes. Real two-account tests remain paused until Master Andrew authorizes participation.

Canonical work-log path: `.hermes/docs/execution/doc.md`. New implementation evidence belongs in `verification/`; do not recreate scattered root-level documentation.
