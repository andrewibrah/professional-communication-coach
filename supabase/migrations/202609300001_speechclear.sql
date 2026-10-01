-- Additive application schema. Does not alter Supabase's rls_auto_enable trigger.
-- Policies are OR-combined; an existing broad policy could expose these buckets.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='storage' AND tablename='objects') THEN
  RAISE EXCEPTION 'Existing Storage policies require explicit review';
 END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS speechclear_private;
REVOKE ALL ON SCHEMA speechclear_private FROM PUBLIC, anon, authenticated;

CREATE FUNCTION speechclear_private.exact(v jsonb, keys text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
 SELECT jsonb_typeof(v)='object' AND (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(v) k) = (SELECT array_agg(k ORDER BY k) FROM unnest(keys) k)
$$;
CREATE FUNCTION speechclear_private.txt(v jsonb, lo int, hi int) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
 SELECT jsonb_typeof(v)='string' AND length(v#>>'{}') BETWEEN lo AND hi
$$;
CREATE FUNCTION speechclear_private.integer(v jsonb, lo int, hi int) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path = pg_catalog AS $$
 SELECT jsonb_typeof(v)='number' AND (v#>>'{}') ~ '^[0-9]+$' AND (v#>>'{}')::numeric BETWEEN lo AND hi
$$;
CREATE FUNCTION speechclear_private.profile_valid(v jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog, speechclear_private AS $$
DECLARE k text; lim int;
BEGIN
 IF jsonb_typeof(v) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
 FOR k IN SELECT jsonb_object_keys(v) LOOP
  lim := CASE k WHEN 'role' THEN 200 WHEN 'industry' THEN 200 WHEN 'experience_level' THEN 200 WHEN 'goal' THEN 1000 WHEN 'tone' THEN 200 WHEN 'weakness' THEN 1000 WHEN 'audience' THEN 500 WHEN 'role_description' THEN 4000 ELSE NULL END;
  IF lim IS NULL OR NOT coalesce(txt(v->k,0,lim),false) THEN RETURN false; END IF;
 END LOOP; RETURN true;
END $$;

CREATE TABLE public.profiles(user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, data jsonb NOT NULL CHECK(speechclear_private.profile_valid(data)), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.practice_sessions(id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE, data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(id,user_id), CHECK(data->>'id'=id::text));
CREATE TABLE public.attempts(id uuid PRIMARY KEY, user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE, session_id uuid NOT NULL, data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(id,user_id), UNIQUE(id,session_id,user_id), FOREIGN KEY(session_id,user_id) REFERENCES public.practice_sessions(id,user_id) ON DELETE CASCADE, CHECK(data->>'id'=id::text AND data->>'session_id'=session_id::text));
CREATE TABLE public.transcripts(attempt_id uuid PRIMARY KEY, user_id uuid NOT NULL, content text NOT NULL CHECK(length(content) BETWEEN 1 AND 100000), FOREIGN KEY(attempt_id,user_id) REFERENCES public.attempts(id,user_id) ON DELETE CASCADE);
CREATE TABLE public.coaching_reports(attempt_id uuid PRIMARY KEY, user_id uuid NOT NULL, data jsonb NOT NULL, FOREIGN KEY(attempt_id,user_id) REFERENCES public.attempts(id,user_id) ON DELETE CASCADE);
CREATE TABLE public.usage_records(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.subscriptions(user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, plan text NOT NULL DEFAULT 'alpha' CHECK(plan IN ('alpha','free','pro')), status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','inactive')), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.audit_events(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE, action text NOT NULL CHECK(action IN ('session_created','session_deleted','history_deleted','suspended','unsuspended','upload_created','legacy_imported')), created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE public.controls(user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE, suspended boolean NOT NULL DEFAULT false);
CREATE TABLE public.global_controls(id boolean PRIMARY KEY DEFAULT true CHECK(id), ai_enabled boolean NOT NULL DEFAULT true, daily_limit int NOT NULL DEFAULT 20 CHECK(daily_limit BETWEEN 1 AND 20), monthly_limit int NOT NULL DEFAULT 200 CHECK(monthly_limit BETWEEN 1 AND 200));
INSERT INTO public.global_controls(id) VALUES(true);
CREATE TABLE public.documents(id uuid PRIMARY KEY,user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE, name text NOT NULL CHECK(length(name) BETWEEN 1 AND 200), state text NOT NULL DEFAULT 'disabled' CHECK(state IN ('disabled','cleanup_pending','deleted')), created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(id,user_id));
CREATE TABLE public.object_metadata(id uuid PRIMARY KEY,user_id uuid NOT NULL REFERENCES auth.users(id),session_id uuid, bucket text NOT NULL DEFAULT 'temporary-audio' CHECK(bucket IN ('temporary-audio','documents')), path text NOT NULL UNIQUE, content_type text NOT NULL,size_bytes bigint NOT NULL CHECK(size_bytes BETWEEN 1 AND 12582912),duration_seconds numeric CHECK(duration_seconds BETWEEN 30 AND 180),state text NOT NULL DEFAULT 'authorized' CHECK(state IN ('authorized','uploading','uploaded','processing','cleanup_pending','deleted')),created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT now()+interval '5 minutes',delete_after timestamptz NOT NULL DEFAULT now()+interval '24 hours',UNIQUE(id,user_id),FOREIGN KEY(session_id,user_id) REFERENCES public.practice_sessions(id,user_id) ON DELETE SET NULL (session_id),CHECK(path LIKE user_id::text||'/'||id::text||'/%'),CHECK(expires_at<=created_at+interval '5 minutes' AND delete_after<=created_at+interval '24 hours'));
CREATE TABLE public.operations(user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,key uuid NOT NULL,session_id uuid NOT NULL,state text NOT NULL CHECK(state IN ('processing','complete','failed')),attempt_id uuid,upload_id uuid,created_at timestamptz NOT NULL DEFAULT now(),lease_until timestamptz NOT NULL DEFAULT now()+interval '10 minutes',PRIMARY KEY(user_id,key),FOREIGN KEY(session_id,user_id) REFERENCES public.practice_sessions(id,user_id) ON DELETE CASCADE,FOREIGN KEY(attempt_id,session_id,user_id) REFERENCES public.attempts(id,session_id,user_id) ON DELETE CASCADE,FOREIGN KEY(upload_id,user_id) REFERENCES public.object_metadata(id,user_id),UNIQUE(upload_id),CHECK((state='complete')=(attempt_id IS NOT NULL)));
CREATE INDEX practice_sessions_owner_created ON public.practice_sessions(user_id,created_at DESC,id);
CREATE INDEX attempts_owner_session_created ON public.attempts(user_id,session_id,created_at,id);
CREATE INDEX usage_records_owner_created ON public.usage_records(user_id,created_at);
CREATE INDEX audit_events_owner_created ON public.audit_events(user_id,created_at);
CREATE INDEX object_metadata_owner_session ON public.object_metadata(user_id,session_id);
CREATE INDEX object_metadata_cleanup ON public.object_metadata(state,delete_after,updated_at) WHERE state<>'deleted';
CREATE INDEX operations_owner_session ON public.operations(user_id,session_id);
CREATE INDEX documents_owner ON public.documents(user_id);
CREATE INDEX transcripts_owner ON public.transcripts(user_id);
CREATE INDEX coaching_reports_owner ON public.coaching_reports(user_id);

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['profiles','practice_sessions','attempts','transcripts','coaching_reports','usage_records','subscriptions','audit_events','controls','documents','object_metadata','operations','global_controls'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated',t);
  EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
  IF t <> 'global_controls' THEN
   EXECUTE format('GRANT SELECT ON public.%I TO authenticated',t);
   EXECUTE format('CREATE POLICY owner_select ON public.%I FOR SELECT TO authenticated USING (user_id=auth.uid())',t);
  END IF;
 END LOOP;
END $$;
GRANT USAGE ON SCHEMA public TO anon,authenticated,service_role;
GRANT USAGE,SELECT ON SEQUENCE public.usage_records_id_seq,public.audit_events_id_seq TO service_role;
GRANT INSERT,UPDATE,DELETE ON public.profiles TO authenticated;
CREATE POLICY owner_insert ON public.profiles FOR INSERT TO authenticated WITH CHECK(user_id=auth.uid());
CREATE POLICY owner_update ON public.profiles FOR UPDATE TO authenticated USING(user_id=auth.uid()) WITH CHECK(user_id=auth.uid());
CREATE POLICY owner_delete ON public.profiles FOR DELETE TO authenticated USING(user_id=auth.uid());
-- CHECK helpers execute in caller context. Only harmless immutable validation helpers are granted.
GRANT USAGE ON SCHEMA speechclear_private TO authenticated,service_role;
GRANT EXECUTE ON FUNCTION speechclear_private.profile_valid(jsonb),speechclear_private.txt(jsonb,int,int) TO authenticated,service_role;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA speechclear_private FROM PUBLIC,anon;

INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types) VALUES
 ('temporary-audio','temporary-audio',false,12582912,ARRAY['audio/webm','audio/mp4','audio/wav','audio/mpeg','audio/ogg']),
 ('documents','documents',false,12582912,ARRAY['application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/plain','text/markdown','text/csv']) ON CONFLICT(id) DO NOTHING;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM storage.buckets WHERE id IN ('temporary-audio','documents') AND (public IS DISTINCT FROM false OR file_size_limit IS DISTINCT FROM 12582912 OR (id='temporary-audio' AND allowed_mime_types IS DISTINCT FROM ARRAY['audio/webm','audio/mp4','audio/wav','audio/mpeg','audio/ogg']) OR (id='documents' AND allowed_mime_types IS DISTINCT FROM ARRAY['application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document','text/plain','text/markdown','text/csv']))) THEN RAISE EXCEPTION 'Existing bucket configuration mismatch'; END IF;
END $$;
-- No direct client Storage policy. Private backend relay is the upload boundary.
