# Guided Voice — Hermes Execution Instructions

## Mission

Execute the planning and then implementation of the complete feature specified in `.hermes/docs/requirements/GUIDED_VOICE_SESSION_SPEC.md`, using `.hermes/docs/execution/GUIDED_VOICE_IMPLEMENTATION_PLAN.md`. Do not stop after architecture prose, UI scaffolding, a mocked transport, or passing a subset of tests. Keep working until acceptance gates are verified or a genuine external blocker prevents the remaining gate.

These instructions describe future execution. Their creation is not authorization to change credentials, deploy to production, erase existing data, or use Andrew's account without consent.

## Reading order and authority

1. `.hermes/docs/requirements/GUIDED_VOICE_SESSION_SPEC.md`: what the feature must do, user experience, acceptance requirements.
2. This file: how Hermes executes safely and records evidence.
3. `.hermes/docs/execution/GUIDED_VOICE_IMPLEMENTATION_PLAN.md`: proposed paths, tasks, verification sequence.
4. `.hermes/docs/README.md`: current navigation and evidence rules.
5. `.hermes/docs/execution/doc.md`: engineering history, prior interruptions and boundaries; not proof of current source/runtime.
6. `.hermes/docs/handoffs/BUILD_CHECKPOINT.md` and current relevant `verification/` files, especially SECURITY_CORRECTIONS.md, APP_INTEGRATION.md and PERSISTENCE_CUTOVER.md.
7. Existing requirements DAY_1_SECURE_FOUNDATION.md, DAY_2_CORE_PRACTICE_FLOW.md, DAY_3_PRODUCT_CONTROLS.md, DAY_4_TESTING_RELEASE.md, IMPLEMENTATION_CONTRACT.md, and SUPABASE_COMPLETION_PROMPT.md under `.hermes/docs/requirements/` as applicable.

Current user directions win over historical documents. Preserve original Recorded Practice contracts unless the user specifically approves changing them. Resolve document/source contradictions against live inspection; write an explicit correction, do not silently treat an old checkbox as acceptance. Stop and ask only when an unresolved decision materially changes scope/security or requires user participation.

## First actions

- Recheck cwd, `git status --short`, branch, and repo-specific instructions. Existing untracked app files and relocated docs are user work, not disposable scaffolding.
- Load relevant skills: writing-plans, test-driven-development; systematic-debugging for failures; agent-browser for browser verification; subagent-driven-development if delegating. Load Supabase implementation/MCP skills before related operations and current provider documentation before selecting transport.
- Read manifests, source definitions and callers before edits. Confirm current FastAPI auth/persistence readiness gate and app lifecycle. Inspect exact frontend auth-generation guards and recording API contracts.
- Run existing frontend/backend baselines. Record results and environment limitations without installing arbitrary production dependencies or printing `.env`.
- Inspect authorized development-project state read-only through Supabase MCP, not CLI, following the standing project preference. Do not infer runtime application access from management OAuth.

## Plan before implementation, then execute without another ceremonial approval

Refine the provided plan into an executor-ready sequence with confirmed exact paths, transport choice, schemas, state transitions, dependencies, and test strategy. Save revisions to the implementation plan and log any material decisions. Do not create a second parallel source of truth.

Make one small vertical slice first: authenticated session creation -> microphone -> real provider -> audible canonical prompt -> one user response -> validated short feedback -> retry/next -> saved turn -> teardown. Then harden controls, visibility, failure behavior and persistence. Keep original practice mode operational.

Use RED -> GREEN -> REFACTOR for application behavior. Tests may mock providers/network only in test code and must be labeled. Runtime may show offline/setup states but never fabricate provider output or user coaching. Apply minimal changes, no unrelated refactors. Do not commit or push unless explicitly asked.

## Transport and authority requirements

Use live browser WebRTC with a provider adapter and trusted backend control/observation channel. Verify provider lifecycle, exact event schema, model/account access, SDK versions, transcript timing and termination API before coding against them. Do not mix examples from different provider API generations. If the provider cannot enforce required server termination/observation, change the architecture or mark a genuine blocker rather than claim safe caps.

The browser controls local media and presentation; the server controls ownership, canonical prompt, turn revision, retry budget, trusted feedback persistence and quota state. Provider-generated tool/decision payloads require strict validation and cannot override controls. Browser captions are not trusted saved evidence.

Initial drill should use deliberate controlled turn-taking. Track generated response completion separately from actual playback completion; a response-done event alone does not mean audio has finished playing. Confirm actual output/playback event ordering and gate microphone evaluation accordingly. Reject empty/partial/duplicate/stale turns. Do not mistake local mute or provider speaker echo for a failed answer.

## Parallel work rules

If using subagents, pass full feature scope, repo paths, file ownership, contracts, evidence expectations, and explicit no-secrets/no-remote-writes boundaries. Separate backend/controller, frontend/media/UI, and SQL/test lanes only after agreeing contracts. Never let two lanes edit the same file concurrently. Parent integrates shared files, verifies child claims with real paths/output, and performs spec and security review. Do not claim external side effects from child summaries without exact readback. If an async delegate requires ending the turn for delivery, honor that handoff; do not poll or invent completion.

## External side effects and access gates

Authorized local code/docs/tests may proceed without repeated reconfirmation. Remote development migrations require confirming the exact project, current grants/policies, review, real local SQL tests, and existing authorized scope. Use additive migrations; do not rewrite applied history or wipe data. Verify every remote write with exact-target readback. Production deployment, unrelated projects, destructive operations, and credential changes require explicit scope approval.

Live account testing is currently paused by prior user direction. Before real-account participation, obtain approval and use secure browser/vault mechanisms. Never ask for passwords/verification codes in chat, guess credentials, invent accounts, or bypass confirmation/authentication. A blocked live gate does not prevent local implementation and tests. Finish independent work, then report the precise remaining human action. No smoke test with a service-role key can stand in for two-user RLS proof.

## Verification discipline

- Frontend unit/integration tests and TypeScript/Vite production build.
- Backend controller/route/provider-adapter/security tests.
- Real disposable PostgreSQL tests for owner isolation, constraints, atomic revisions, usage concurrency, and cleanup/termination recovery records.
- Browser checks: user gesture/permission, actual peer connection/media playback, visibility/accessibility, controls, teardown, reconnect and recorded-mode regression.
- Authorized live provider check: real user speech, audible target, short feedback, real retry and next transition, saved exact turn readback, end/limit termination.
- Distinguish test doubles, synthetic audio, actual browser media, live provider, live auth and remote SQL. Synthetic audio is useful transport proof, not proof of real speech coaching.
- Measure observed end-of-user-turn to first audible feedback and report actual results; do not invent latency/cost expectations as measured results.
- Verify no permanent secrets reach public config, frontend source/bundle, logs, URLs, or diagnostic output. Do not print private transcripts or raw auth headers to prove a test.

Write evidence under `.hermes/docs/verification/GUIDED_VOICE_VERIFICATION.md`; append meaningful changes and actual command outcomes to `.hermes/docs/execution/doc.md`. Each requirement is PASS, FAIL, or BLOCKED with an evidence reference and scope of proof. Unrun is not PASS.

## Definition of end-to-end completion

All acceptance rows in the feature spec pass, baseline functionality remains intact, real browser/provider flow works with an authorized account, trusted persisted results read back correctly, and server termination/cost/isolation controls are exercised. If access/approval prevents a gate, deliver working local artifacts and an explicit partial-completion/blocker report—not “end-to-end complete.”

Final handoff: changed files, verified capabilities, exact test/build results, runtime/start instructions, observed live behavior, remaining risks, and one next action if blocked. No future-action promise without actual work.
