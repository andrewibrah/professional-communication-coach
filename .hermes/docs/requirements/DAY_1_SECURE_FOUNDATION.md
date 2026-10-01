# Day 1 — Secure Web Foundation

## Product boundary

This is a desktop/laptop web application only. It does not support phones, tablets, React Native, Expo, iOS, or Android.

## Objective

Deliver a runnable web client, FastAPI service, Supabase authentication, database migrations, private storage, and verified tenant isolation.

## Build scope

- Create a responsive desktop-first React web application using TypeScript.
- Create a FastAPI backend with versioned `/api/v1` routes.
- Configure Supabase Auth for email/password and magic-link authentication.
- Require verified email before AI-powered endpoints can run.
- Implement login, logout, password reset, session refresh, and account-deletion entry points.
- Verify Supabase JWTs in FastAPI using published signing keys.
- Derive `user_id` exclusively from the verified token—not request bodies, query strings, or headers supplied by the client.
- Create initial Postgres migrations for profiles, practice sessions, attempts, transcripts, coaching reports, usage records, subscriptions, audit events, documents, and stored-object metadata.
- Add `user_id` to every user-owned record.
- Enable Row Level Security on every table containing user data.
- Create private storage buckets for temporary audio and knowledge-base documents.
- Scope object paths as `{user_id}/{resource_id}/{filename}`.
- Keep all privileged secrets in backend environment variables only.
- Add safe error responses and redact authorization data and sensitive content from logs.

## Six-agent lanes

1. React web shell and authentication screens.
2. FastAPI structure, configuration, and health endpoints.
3. Supabase schema, migrations, and Row Level Security.
4. JWT verification and authorization dependencies.
5. Private storage and signed-URL design.
6. Security tests and independent review.

## Required tests

- Anonymous requests to protected APIs return `401`.
- Invalid and expired JWTs return `401`.
- Unverified users cannot invoke paid AI functionality.
- User A cannot read, update, or delete User B's records.
- User A cannot request a signed URL for User B's storage object.
- The browser bundle contains no privileged key.
- All user-data tables have Row Level Security enabled.

## Day 1 acceptance receipt

- Web client and API both start locally.
- A user can register, verify, sign in, refresh a session, and sign out.
- Database migrations apply cleanly.
- Automated tenant-isolation tests pass.
- A secret scan finds no privileged credentials in client code or committed files.
