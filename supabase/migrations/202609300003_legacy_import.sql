-- Protected one-owner import. Exporter must map each source owner to an existing auth UUID.
CREATE TABLE speechclear_private.import_receipts(user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,fingerprint text NOT NULL,payload_hash bytea NOT NULL,counts jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(user_id,fingerprint));
ALTER TABLE speechclear_private.import_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON speechclear_private.import_receipts FROM PUBLIC,anon,authenticated;

CREATE FUNCTION speechclear_private.import_legacy(owner uuid, payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SET search_path=pg_catalog,public,speechclear_private AS $$
DECLARE t text; r jsonb; v jsonb; fp text; h bytea; saved speechclear_private.import_receipts%ROWTYPE; counts jsonb:='{}'; n int;
BEGIN
 -- Prevent ordinary service inserts from evaluating nextval during setval.
 LOCK TABLE public.usage_records,public.audit_events IN ACCESS EXCLUSIVE MODE;
 IF jsonb_typeof(payload) IS DISTINCT FROM 'object' OR EXISTS(SELECT 1 FROM jsonb_object_keys(payload) k WHERE k NOT IN ('profiles','sessions','attempts','usage','controls','audit','operations','fingerprint')) OR NOT payload ?& ARRAY['profiles','sessions','attempts','usage','controls','audit','operations'] THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy payload'; END IF;
 h:=sha256(convert_to((payload-'fingerprint')::text,'UTF8'));
 fp:=coalesce(payload->>'fingerprint',encode(h,'hex'));
 IF fp !~ '^[a-f0-9]{64}$' THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy fingerprint'; END IF;
 SELECT * INTO saved FROM speechclear_private.import_receipts WHERE user_id=owner AND fingerprint=fp;
 IF FOUND THEN
  IF saved.payload_hash<>h THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Legacy fingerprint conflict'; END IF;
  RETURN jsonb_build_object('counts',saved.counts,'replayed',true,'fingerprint',fp);
 END IF;
 FOREACH t IN ARRAY ARRAY['profiles','sessions','attempts','usage','controls','audit','operations'] LOOP
  IF jsonb_typeof(payload->t) IS DISTINCT FROM 'array' OR jsonb_array_length(payload->t)>100000 THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy rows'; END IF;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(payload->t) e WHERE jsonb_typeof(e) IS DISTINCT FROM 'object' OR e->>'user_id' IS DISTINCT FROM owner::text) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy owner mapping'; END IF;
 END LOOP;
 FOREACH t IN ARRAY ARRAY['profiles','sessions','attempts','usage','controls','audit','operations'] LOOP
  n:=0;
  FOR r IN SELECT value FROM jsonb_array_elements(payload->t) LOOP
   IF jsonb_typeof(r) IS DISTINCT FROM 'object' OR r->>'user_id' IS DISTINCT FROM owner::text THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy owner mapping'; END IF;
   CASE t
   WHEN 'profiles' THEN
    IF NOT exact(r,ARRAY['user_id','data']) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy profile'; END IF;
    v:=CASE WHEN jsonb_typeof(r->'data')='string' THEN (r->>'data')::jsonb ELSE r->'data' END;
    IF NOT profile_valid(v) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy profile'; END IF;
    -- Never overwrite existing runtime rows during cutover.
    INSERT INTO public.profiles(user_id,data) VALUES(owner,v);
   WHEN 'sessions' THEN
    IF NOT exact(r,ARRAY['id','user_id','data']) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy session'; END IF;
    v:=CASE WHEN jsonb_typeof(r->'data')='string' THEN (r->>'data')::jsonb ELSE r->'data' END;
    IF NOT session_valid(v) OR r->>'id' IS DISTINCT FROM v->>'id' THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy session'; END IF;
    INSERT INTO public.practice_sessions(id,user_id,data,created_at) VALUES((r->>'id')::uuid,owner,v,(v->>'created_at')::timestamptz);
   WHEN 'attempts' THEN
    IF NOT exact(r,ARRAY['id','user_id','session_id','data']) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy attempt'; END IF;
    v:=CASE WHEN jsonb_typeof(r->'data')='string' THEN (r->>'data')::jsonb ELSE r->'data' END;
    IF NOT attempt_valid(v) OR r->>'id' IS DISTINCT FROM v->>'id' OR r->>'session_id' IS DISTINCT FROM v->>'session_id' THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy attempt'; END IF;
    INSERT INTO public.attempts(id,user_id,session_id,data,created_at) VALUES((r->>'id')::uuid,owner,(r->>'session_id')::uuid,v,(v->>'created_at')::timestamptz);
    INSERT INTO public.transcripts(attempt_id,user_id,content) VALUES((r->>'id')::uuid,owner,v->>'transcript');
    INSERT INTO public.coaching_reports(attempt_id,user_id,data) VALUES((r->>'id')::uuid,owner,v->'report');
   WHEN 'usage' THEN
    IF NOT exact(r,ARRAY['id','user_id','created_at']) OR NOT coalesce(speechclear_private.integer(r->'id',1,2147483647),false) OR NOT isfinite((r->>'created_at')::timestamptz) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy usage'; END IF;
    INSERT INTO public.usage_records(id,user_id,created_at) OVERRIDING SYSTEM VALUE VALUES((r->>'id')::bigint,owner,(r->>'created_at')::timestamptz);
   WHEN 'controls' THEN
    IF NOT exact(r,ARRAY['user_id','suspended']) OR r->'suspended' NOT IN ('true'::jsonb,'false'::jsonb,'0'::jsonb,'1'::jsonb) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy control'; END IF;
    INSERT INTO public.controls(user_id,suspended) VALUES(owner,r->'suspended' IN ('true'::jsonb,'1'::jsonb));
   WHEN 'audit' THEN
    IF NOT exact(r,ARRAY['id','user_id','action','created_at']) OR NOT coalesce(speechclear_private.integer(r->'id',1,2147483647),false) OR NOT isfinite((r->>'created_at')::timestamptz) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy audit'; END IF;
    INSERT INTO public.audit_events(id,user_id,action,created_at) OVERRIDING SYSTEM VALUE VALUES((r->>'id')::bigint,owner,r->>'action',(r->>'created_at')::timestamptz);
   WHEN 'operations' THEN
    IF NOT exact(r,ARRAY['user_id','key','session_id','state','attempt_id']) OR r->>'state' NOT IN ('processing','complete','failed') THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy operation'; END IF;
    -- A pre-cutover in-flight operation has no trusted live worker/lease. Preserve it, but fence completion.
    INSERT INTO public.operations(user_id,key,session_id,state,attempt_id,lease_until) VALUES(owner,(r->>'key')::uuid,(r->>'session_id')::uuid,r->>'state',(r->>'attempt_id')::uuid,now());
   END CASE;n:=n+1;
  END LOOP;
  counts:=counts||jsonb_build_object(t,n);
 END LOOP;
 -- Sequence adjustment is monotonic; PostgreSQL sequences themselves are nontransactional.
 PERFORM setval('public.usage_records_id_seq',greatest((SELECT last_value FROM public.usage_records_id_seq),(SELECT coalesce(max(id),1) FROM public.usage_records)),true);
 PERFORM setval('public.audit_events_id_seq',greatest((SELECT last_value FROM public.audit_events_id_seq),(SELECT coalesce(max(id),1) FROM public.audit_events)),true);
 INSERT INTO speechclear_private.import_receipts(user_id,fingerprint,payload_hash,counts) VALUES(owner,fp,h,counts);
 RETURN jsonb_build_object('counts',counts,'replayed',false,'fingerprint',fp);
EXCEPTION WHEN check_violation OR not_null_violation OR invalid_text_representation OR datetime_field_overflow THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid legacy rows';
END $$;
REVOKE ALL ON FUNCTION speechclear_private.import_legacy(uuid,jsonb) FROM PUBLIC,anon,authenticated,service_role;
