# SpeechClear implementation contract

Scope: React desktop app, real practice-to-feedback flow, and FastAPI controls. Supabase schema/persistence/private Storage are integrated; live two-user and authenticated browser/provider acceptance remain pending. No fake auth/reports. DAY_* docs are requirements, not execution proof. Do not overwrite .env or print its values.

## Runtime
- Frontend Vite React TypeScript in `frontend/`, localhost:5173.
- Backend FastAPI in `backend/`, localhost:8000, API prefix `/api/v1`.
- Vite proxy /api -> localhost:8000. Bearer Supabase access tokens on protected routes.
- .env loaded server-side from repo root. GET /api/v1/config exposes ONLY {supabase_url, supabase_publishable_key, auth_configured, ai_enabled, min_recording_seconds:30,max_recording_seconds:180,max_upload_bytes:12582912}. No privileged secrets.
- Missing backend credentials/target or protected import receipt: screens/public scenarios remain available; private endpoints fail closed. Supabase is the only default runtime store, with no automatic SQLite fallback or dual-write. SQLite is only a protected read-only migration source and explicit test adapter.

## API contract
All JSON response objects snake_case. Error: {detail:string}.
GET /api/v1/health -> {status:'ok',storage:'supabase',auth_configured:bool,persistence_ready:bool,audio_storage_ready:bool}; readiness is local configuration/receipt evidence, not RLS acceptance.
GET /api/v1/config -> as above
GET /api/v1/scenarios -> {scenarios:[{id,title,description,question}]}; IDs introduction,technical-interview,help-desk,cybersecurity,sales,escalation.
GET /api/v1/profile -> {role,industry,experience_level,goal,tone,weakness,audience,role_description} strings; defaults empty.
PUT /api/v1/profile same fields -> stored profile.
POST /api/v1/sessions {scenario_id,goal,custom_context?} -> {id,scenario_id,goal,context,question,example_response,created_at}; uses real OpenAI for context/example.
GET /api/v1/sessions -> {sessions:[{id,scenario_id,goal,context,question,example_response,created_at,attempt_count,latest_score}]}
GET /api/v1/sessions/{id} -> session fields + {attempts:[{id,session_id,transcript,duration_seconds,created_at,report:Report}]}
POST /api/v1/sessions/{id}/attempt-uploads JSON {content_type,size_bytes,duration_seconds} -> {upload_id,expires_at}; authorization is owner/session-bound and expires after five minutes.
PUT /api/v1/sessions/{id}/attempt-uploads/{upload_id} raw audio bytes -> 204; verified bearer identity, single-use atomic claim, actual-byte validation, then private Storage relay. Server derives path {owner}/{upload_id}/response.ext.
POST /api/v1/sessions/{id}/attempts JSON {upload_id}; mandatory canonical UUID Idempotency-Key -> existing attempt object. Completed replay returns the saved attempt without another upload/provider call/quota charge; failed keys require new recording. Actual media decoding remains authoritative. Raw-object cleanup is durable/retryable, with local-file finally cleanup and scheduled crash recovery. No permanent audio replay or signed URL is exposed. Legacy multipart exists only with explicit injected test SQLite, never active runtime fallback.
DELETE /api/v1/sessions/{id} -> 204
DELETE /api/v1/history -> 204
GET /api/v1/usage -> {daily_used,daily_limit,monthly_used,monthly_limit}; quota units are AI operations, includes scenario generation.

Report fields:
overall_score: integer 0..100
category_scores: {clarity:int,structure:int,conciseness:int,audience_fit:int,professional_tone:int} (0..100)
communication_strengths: string[]
transcript_evidence: [{quote:string,observation:string}]
filler_words: [{word:string,count:int}]
jargon_flags: string[]
pacing_observations: string[]
weak_phrasing: string[]
missed_questions: string[]
priority_improvement: string
suggested_practice_exercise: string
improved_answer: string
next_time_recommendation: string

## Frontend boundaries
Use real Supabase JS auth with public config fetched from server: signup, login, logout, reset email, update password, session refresh handled by SDK. Show verification instructions. All private APIs must attach verified session token. A missing backend or config shows honest setup/error state, never sample scores or fake successful flows. Provide dashboard, practice, history, profile/privacy settings. Delete history/session works; account deletion explicitly pending until integration exists. Progress computed from saved reports, empty state otherwise. Pause unsupported on recorder; cancel/stop supported. Recorder hard-stops 180s, rejects shorter than 30s, MIME feature detection, permission errors, cleanup tracks/object URLs. Retry stays in same session and compares first vs latest.

## Test discipline
Use vertical RED -> GREEN tests before implementation. Record commands/failures in each lane's verification file. Mock external OpenAI/JWKS only in tests; no mock data runtime. Security tests cover unauthorized, invalid/expired tokens, unverified users, cross-user ownership, quotas concurrency, suspension, kill switch, invalid reports, malformed media, duplicate idempotency. Do not claim live Supabase validation until actually exercised.
