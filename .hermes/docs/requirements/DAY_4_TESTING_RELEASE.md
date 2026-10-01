# Day 4 — Private Knowledge Base and Testing Release

## Objective

Ship a deployed, documented, controlled-testing release with a limited private knowledge base, observability, security verification, and clear operational boundaries.

## Knowledge-base scope

- Support PDF, DOCX, TXT, Markdown, and CSV only.
- Reject executables, archives, macro-enabled Office files, unknown MIME types, malformed files, oversized files, and excessive page counts.
- Apply plan limits for document count and total indexed content.
- Keep documents in private storage.
- Extract text server-side.
- Index with per-user isolation using pgvector or OpenAI vector stores.
- Retrieve only relevant chunks for the active scenario.
- Require ownership checks at upload, processing, retrieval, download, and deletion.
- Treat retrieved chunks as quoted reference material, never executable instructions.
- Add malware scanning if a dependable scanner can be integrated within the alpha window; otherwise keep document uploads restricted and mark general uploads as unavailable.

## Observability and privacy

- Configure Sentry for backend and browser errors.
- Configure privacy-conscious PostHog events.
- Never log authorization headers, API keys, raw audio, full transcripts, document contents, or signed URLs.
- Return safe client errors without stack traces.
- Record audit events for login, session creation, upload, deletion, account deletion, suspension, and subscription changes.
- Separate development, staging, and production configuration in documentation and deployment setup.

## Release verification

- Run unit, API integration, database-policy, browser end-to-end, and secret-scanning tests.
- Verify two independent test users cannot access each other's:
  - Profiles.
  - Practice sessions.
  - Attempts.
  - Transcripts.
  - Coaching reports.
  - Audio objects.
  - Documents.
  - Retrieved knowledge-base chunks.
  - Usage records.
  - Subscription records.
- Exercise invalid tokens, expired tokens, unverified accounts, malformed uploads, oversized recordings, quota exhaustion, suspended users, and the AI kill switch.
- Verify temporary audio cleanup.
- Verify prompt-injection strings cannot override evaluation policy or authorization.
- Verify no privileged secrets appear in the web bundle, logs, repository, or source maps.

## Required documentation

- Root README with local setup and verified commands.
- `.env.example` containing names only—never secret values.
- Architecture diagram.
- Database schema and migrations.
- Row Level Security policy inventory.
- API documentation.
- Threat model.
- Privacy and data-retention policy.
- Secure deployment instructions.
- Cross-user isolation checklist with recorded test results.
- Known limitations and post-alpha backlog.

## Day 4 release boundary

This release is a private testing alpha for desktop and laptop browsers. It is not an iOS, Android, tablet, or mobile-browser product. It is not represented as enterprise-certified, independently audited, medically diagnostic, or production-scale.

## Day 4 acceptance receipt

- The web application and API are deployed to controlled test environments.
- Real authentication, recording, transcription, coaching, retry, deletion, quotas, and restricted knowledge retrieval work end to end.
- Canonical automated tests pass from a clean checkout.
- Cross-user isolation checks pass for database rows, storage objects, documents, transcripts, and AI results.
- The release has a written rollback procedure and a working AI-feature kill switch.
- Known limitations are documented honestly before testers are invited.
