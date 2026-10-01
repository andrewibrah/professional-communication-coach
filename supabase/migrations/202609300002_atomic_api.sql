ALTER TABLE public.object_metadata ADD COLUMN suffix text GENERATED ALWAYS AS (substring(path from '\.[a-z0-9]+$')) STORED;
CREATE FUNCTION speechclear_private.report_valid(v jsonb, transcript text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog,speechclear_private AS $$
DECLARE k text; e jsonb;
BEGIN
 IF NOT coalesce(exact(v,ARRAY['overall_score','category_scores','communication_strengths','transcript_evidence','filler_words','jargon_flags','pacing_observations','weak_phrasing','missed_questions','priority_improvement','suggested_practice_exercise','improved_answer','next_time_recommendation']),false) THEN RETURN false; END IF;
 IF NOT coalesce(speechclear_private.integer(v->'overall_score',0,100),false) OR NOT coalesce(exact(v->'category_scores',ARRAY['clarity','structure','conciseness','audience_fit','professional_tone']),false) THEN RETURN false; END IF;
 FOR k IN SELECT jsonb_object_keys(v->'category_scores') LOOP
  IF NOT coalesce(speechclear_private.integer(v->'category_scores'->k,0,100),false) THEN RETURN false; END IF;
 END LOOP;
 FOREACH k IN ARRAY ARRAY['priority_improvement','suggested_practice_exercise','improved_answer','next_time_recommendation'] LOOP
  IF NOT coalesce(txt(v->k,1,6000),false) THEN RETURN false; END IF;
 END LOOP;
 FOREACH k IN ARRAY ARRAY['communication_strengths','jargon_flags','pacing_observations','weak_phrasing','missed_questions'] LOOP
  IF jsonb_typeof(v->k) IS DISTINCT FROM 'array' OR jsonb_array_length(v->k)>30 THEN RETURN false; END IF;
  FOR e IN SELECT value FROM jsonb_array_elements(v->k) LOOP
   IF NOT coalesce(txt(e,1,6000),false) THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 IF jsonb_typeof(v->'transcript_evidence') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'transcript_evidence') NOT BETWEEN 1 AND 30 THEN RETURN false; END IF;
 FOR e IN SELECT value FROM jsonb_array_elements(v->'transcript_evidence') LOOP
  IF NOT coalesce(exact(e,ARRAY['quote','observation']) AND txt(e->'quote',1,6000) AND txt(e->'observation',1,6000) AND strpos(transcript,e->>'quote')>0,false) THEN RETURN false; END IF;
 END LOOP;
 IF jsonb_typeof(v->'filler_words') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'filler_words')>100 THEN RETURN false; END IF;
 FOR e IN SELECT value FROM jsonb_array_elements(v->'filler_words') LOOP
  IF NOT coalesce(exact(e,ARRAY['word','count']) AND txt(e->'word',1,6000) AND speechclear_private.integer(e->'count',0,10000),false) THEN RETURN false; END IF;
 END LOOP; RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION speechclear_private.session_valid(v jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog,speechclear_private AS $$
BEGIN
 RETURN coalesce(exact(v,ARRAY['id','scenario_id','goal','question','created_at','context','example_response'])
  AND txt(v->'id',36,36) AND (v->>'id')::uuid::text=v->>'id'
  AND txt(v->'scenario_id',1,50) AND v->>'scenario_id' IN ('introduction','technical-interview','help-desk','cybersecurity','sales','escalation')
  AND txt(v->'goal',1,1000) AND txt(v->'question',1,5000) AND txt(v->'context',1,5000) AND txt(v->'example_response',1,5000)
  AND txt(v->'created_at',1,64) AND isfinite((v->>'created_at')::timestamptz),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION speechclear_private.attempt_valid(v jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog,speechclear_private AS $$
BEGIN
 RETURN coalesce(exact(v,ARRAY['id','session_id','transcript','duration_seconds','created_at','report'])
  AND txt(v->'id',36,36) AND (v->>'id')::uuid::text=v->>'id'
  AND txt(v->'session_id',36,36) AND (v->>'session_id')::uuid::text=v->>'session_id'
  AND txt(v->'transcript',1,100000) AND jsonb_typeof(v->'duration_seconds')='number'
  AND (v->>'duration_seconds')::numeric BETWEEN 29.85 AND 180.15
  AND txt(v->'created_at',1,64) AND isfinite((v->>'created_at')::timestamptz)
  AND report_valid(v->'report',v->>'transcript'),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
ALTER TABLE public.practice_sessions ADD CONSTRAINT session_valid CHECK(speechclear_private.session_valid(data));
ALTER TABLE public.attempts ADD CONSTRAINT attempt_valid CHECK(speechclear_private.attempt_valid(data));
ALTER TABLE public.coaching_reports ADD CONSTRAINT report_shape CHECK(jsonb_typeof(data)='object');
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA speechclear_private FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION speechclear_private.profile_valid(jsonb),speechclear_private.txt(jsonb,int,int) TO authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA speechclear_private TO service_role;

CREATE FUNCTION speechclear_private.child_matches_attempt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE parent jsonb;
BEGIN
 SELECT data INTO parent FROM public.attempts WHERE id=NEW.attempt_id AND user_id=NEW.user_id;
 IF parent IS NULL OR (TG_TABLE_NAME='coaching_reports' AND to_jsonb(NEW)->'data' IS DISTINCT FROM parent->'report') OR (TG_TABLE_NAME='transcripts' AND to_jsonb(NEW)->>'content' IS DISTINCT FROM parent->>'transcript') THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid attempt child'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION speechclear_private.child_matches_attempt() FROM PUBLIC,anon,authenticated;
CREATE TRIGGER report_matches_attempt BEFORE INSERT OR UPDATE ON public.coaching_reports FOR EACH ROW EXECUTE FUNCTION speechclear_private.child_matches_attempt();
CREATE TRIGGER transcript_matches_attempt BEFORE INSERT OR UPDATE ON public.transcripts FOR EACH ROW EXECUTE FUNCTION speechclear_private.child_matches_attempt();

CREATE FUNCTION speechclear_private.attempt_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE SQLSTATE 'PT409' USING MESSAGE='Attempts are immutable'; END $$;
REVOKE ALL ON FUNCTION speechclear_private.attempt_immutable() FROM PUBLIC,anon,authenticated;
CREATE TRIGGER attempt_immutable BEFORE UPDATE ON public.attempts FOR EACH ROW EXECUTE FUNCTION speechclear_private.attempt_immutable();

CREATE FUNCTION public.speechclear_api(p_action text,p_owner uuid,p_payload jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog,speechclear_private,public AS $$
DECLARE quota_at timestamptz; v jsonb; result jsonb; op public.operations%ROWTYPE; obj public.object_metadata%ROWTYPE; lock_owner uuid; sid uuid; aid uuid; u jsonb; daily int; monthly int; active boolean; allowed text[]; required text[]; k text; g public.global_controls%ROWTYPE;
BEGIN
 IF p_action NOT IN ('cleanup_list','cleanup_done') AND (p_owner IS NULL OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id=p_owner)) THEN RAISE SQLSTATE 'PT403' USING MESSAGE='Invalid owner'; END IF;
 IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid request fields'; END IF;
 CASE p_action
 WHEN 'require_active','sessions' THEN allowed:=ARRAY[]::text[];required:=allowed;
 WHEN 'usage','reserve' THEN allowed:=ARRAY['daily','monthly'];required:=allowed;
 WHEN 'profile' THEN allowed:=ARRAY['data'];required:=ARRAY[]::text[];
 WHEN 'save_session' THEN allowed:=ARRAY['data'];required:=allowed;
 WHEN 'session','session_detail','attempts' THEN allowed:=ARRAY['id'];required:=allowed;
 WHEN 'begin_attempt' THEN allowed:=ARRAY['session','key','daily','monthly','upload_id'];required:=ARRAY['session','key','daily','monthly'];
 WHEN 'finish_attempt' THEN allowed:=ARRAY['key','attempt'];required:=allowed;
 WHEN 'fail_attempt' THEN allowed:=ARRAY['key'];required:=allowed;
 WHEN 'delete' THEN allowed:=ARRAY['id'];required:=ARRAY[]::text[];
 WHEN 'suspend' THEN allowed:=ARRAY['value'];required:=allowed;
 WHEN 'upload_create' THEN allowed:=ARRAY['session','id','content_type','size_bytes','duration_seconds','suffix'];required:=allowed;
 WHEN 'upload_get' THEN allowed:=ARRAY['id','session'];required:=ARRAY['id'];
 WHEN 'upload_write_check' THEN allowed:=ARRAY['id','session'];required:=allowed;
 WHEN 'upload_claim' THEN allowed:=ARRAY['id','session'];required:=allowed;
 WHEN 'upload_state' THEN allowed:=ARRAY['id','state'];required:=allowed;
 WHEN 'cleanup_claim' THEN allowed:=ARRAY['id','updated_at'];required:=allowed;
 WHEN 'cleanup_list' THEN allowed:=ARRAY[]::text[];required:=allowed;
 WHEN 'cleanup_done' THEN allowed:=ARRAY['id'];required:=allowed;
 WHEN 'import_legacy' THEN allowed:=ARRAY['profiles','sessions','attempts','usage','controls','audit','operations','fingerprint'];required:=ARRAY['profiles','sessions','attempts','usage','controls','audit','operations'];
 ELSE RAISE SQLSTATE 'PT422' USING MESSAGE='Unknown action'; END CASE;
 IF EXISTS(SELECT 1 FROM jsonb_object_keys(p_payload) x WHERE NOT x=ANY(allowed)) OR NOT p_payload ?& required THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid request fields'; END IF;
 FOREACH k IN ARRAY ARRAY['id','session','key','upload_id'] LOOP
  IF p_payload ? k AND NOT (p_action='delete' AND k='id' AND p_payload->k='null'::jsonb) THEN
   IF jsonb_typeof(p_payload->k) IS DISTINCT FROM 'string' OR (p_payload->>k) !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid request fields'; END IF;
  END IF;
 END LOOP;
 -- Global import boundary first, then owner lock: never invert this order.
 IF p_action='import_legacy' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('speechclear-global-import',0));
 ELSE
  PERFORM pg_advisory_xact_lock_shared(hashtextextended('speechclear-global-import',0));
 END IF;
 -- One serialization boundary for every owner mutation; reads can also wait on it.
 lock_owner:=p_owner;
 IF p_action='cleanup_done' THEN SELECT user_id INTO lock_owner FROM public.object_metadata WHERE id=(p_payload->>'id')::uuid; END IF;
 IF lock_owner IS NOT NULL THEN PERFORM pg_advisory_xact_lock(hashtextextended(lock_owner::text,0)); END IF;
 quota_at:=clock_timestamp();
 SELECT * INTO g FROM public.global_controls WHERE id FOR SHARE;
 IF p_action IN ('require_active','reserve','begin_attempt','save_session','finish_attempt','upload_create','upload_claim','upload_write_check') THEN
  IF g.ai_enabled IS DISTINCT FROM true OR EXISTS(SELECT 1 FROM public.controls WHERE user_id=p_owner AND suspended) THEN RAISE SQLSTATE 'PT403' USING MESSAGE='AI features unavailable or account suspended'; END IF;
 END IF;
 IF p_action IN ('usage','reserve','begin_attempt') THEN
  IF NOT coalesce(speechclear_private.integer(p_payload->'daily',1,2147483647) AND speechclear_private.integer(p_payload->'monthly',1,2147483647),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid quota limits'; END IF;
  daily:=least(g.daily_limit,(p_payload->>'daily')::int);monthly:=least(g.monthly_limit,(p_payload->>'monthly')::int);
  SELECT jsonb_build_object('daily_used',count(*) FILTER(WHERE created_at>=date_trunc('day',quota_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'),'monthly_used',count(*),'daily_limit',daily,'monthly_limit',monthly) INTO u FROM public.usage_records WHERE user_id=p_owner AND created_at>=date_trunc('month',quota_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
 END IF;
 CASE p_action
 WHEN 'import_legacy' THEN RETURN speechclear_private.import_legacy(p_owner,p_payload);
 WHEN 'require_active' THEN RETURN 'null';
 WHEN 'usage' THEN RETURN u;
 WHEN 'reserve' THEN
  IF (u->>'daily_used')::int>=daily OR (u->>'monthly_used')::int>=monthly THEN RAISE SQLSTATE 'PT429' USING MESSAGE='AI quota reached'; END IF;
  INSERT INTO public.usage_records(user_id,created_at) VALUES(p_owner,quota_at);RETURN 'null';
 WHEN 'profile' THEN
  IF p_payload ? 'data' THEN
   IF NOT coalesce(profile_valid(p_payload->'data'),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid profile'; END IF;
   INSERT INTO public.profiles(user_id,data) VALUES(p_owner,p_payload->'data') ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=clock_timestamp();
  END IF;
  SELECT data INTO result FROM public.profiles WHERE user_id=p_owner;
  RETURN jsonb_build_object('role','','industry','','experience_level','','goal','','tone','','weakness','','audience','','role_description','') || coalesce(result,'{}');
 WHEN 'save_session' THEN
  v:=p_payload->'data';
  IF NOT session_valid(v) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid session'; END IF;
  INSERT INTO public.practice_sessions(id,user_id,data,created_at) VALUES((v->>'id')::uuid,p_owner,v,(v->>'created_at')::timestamptz);
  INSERT INTO public.audit_events(user_id,action) VALUES(p_owner,'session_created');RETURN v;
 WHEN 'session','session_detail','attempts' THEN
  sid:=(p_payload->>'id')::uuid;
  SELECT CASE WHEN p_action='session_detail' THEN s.data||jsonb_build_object('attempts',coalesce((SELECT jsonb_agg(a.data ORDER BY a.created_at,a.id) FROM public.attempts a WHERE a.user_id=p_owner AND a.session_id=s.id),'[]')) ELSE s.data END INTO result FROM public.practice_sessions s WHERE s.user_id=p_owner AND s.id=sid;
  IF result IS NULL THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Session not found'; END IF;
  IF p_action='attempts' THEN SELECT coalesce(jsonb_agg(data ORDER BY created_at,id),'[]') INTO result FROM public.attempts WHERE user_id=p_owner AND session_id=sid; END IF;RETURN result;
 WHEN 'sessions' THEN
  SELECT coalesce(jsonb_agg(x.data ORDER BY x.created_at DESC,x.id),'[]') INTO result FROM (SELECT s.id,s.created_at,s.data||jsonb_build_object('attempt_count',(SELECT count(*) FROM public.attempts a WHERE a.user_id=p_owner AND a.session_id=s.id),'latest_score',(SELECT a.data->'report'->'overall_score' FROM public.attempts a WHERE a.user_id=p_owner AND a.session_id=s.id ORDER BY a.created_at DESC,a.id DESC LIMIT 1)) data FROM public.practice_sessions s WHERE s.user_id=p_owner) x;RETURN result;
 WHEN 'begin_attempt' THEN
  sid:=(p_payload->>'session')::uuid;
  IF NOT EXISTS(SELECT 1 FROM public.practice_sessions WHERE user_id=p_owner AND id=sid) THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Session not found'; END IF;
  SELECT * INTO op FROM public.operations WHERE user_id=p_owner AND key=(p_payload->>'key')::uuid;
  IF FOUND THEN
   IF op.session_id<>sid OR op.state<>'complete' OR (p_payload ? 'upload_id' AND op.upload_id IS DISTINCT FROM (p_payload->>'upload_id')::uuid) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Request already processing or key unavailable'; END IF;
   SELECT data INTO result FROM public.attempts WHERE user_id=p_owner AND id=op.attempt_id;RETURN result;
  END IF;
  IF (u->>'daily_used')::int>=daily OR (u->>'monthly_used')::int>=monthly THEN RAISE SQLSTATE 'PT429' USING MESSAGE='AI quota reached'; END IF;
  IF p_payload ? 'upload_id' THEN
   SELECT * INTO obj FROM public.object_metadata WHERE id=(p_payload->>'upload_id')::uuid AND user_id=p_owner AND session_id=sid;
   IF NOT FOUND OR obj.state<>'uploaded' OR obj.delete_after<=clock_timestamp() OR EXISTS(SELECT 1 FROM public.operations WHERE upload_id=obj.id) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Upload unavailable'; END IF;
   UPDATE public.object_metadata SET state='processing',updated_at=clock_timestamp() WHERE id=obj.id;
  END IF;
  INSERT INTO public.operations(user_id,key,session_id,state,upload_id) VALUES(p_owner,(p_payload->>'key')::uuid,sid,'processing',obj.id);
  INSERT INTO public.usage_records(user_id,created_at) VALUES(p_owner,quota_at);RETURN 'null';
 WHEN 'finish_attempt' THEN
  SELECT * INTO op FROM public.operations WHERE user_id=p_owner AND key=(p_payload->>'key')::uuid;
  IF NOT FOUND OR op.state<>'processing' OR op.lease_until<=clock_timestamp() THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Request unavailable or lease expired'; END IF;
  IF op.upload_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.object_metadata WHERE id=op.upload_id AND user_id=p_owner AND session_id=op.session_id AND state='processing' AND delete_after>clock_timestamp()) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Upload unavailable'; END IF;
  v:=p_payload->'attempt';
  IF NOT attempt_valid(v) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid coaching report or attempt'; END IF;
  IF (v->>'session_id')::uuid<>op.session_id THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Attempt session mismatch'; END IF;
  aid:=(v->>'id')::uuid;
  INSERT INTO public.attempts(id,user_id,session_id,data,created_at) VALUES(aid,p_owner,op.session_id,v,(v->>'created_at')::timestamptz);
  INSERT INTO public.transcripts(attempt_id,user_id,content) VALUES(aid,p_owner,v->>'transcript');
  INSERT INTO public.coaching_reports(attempt_id,user_id,data) VALUES(aid,p_owner,v->'report');
  UPDATE public.operations SET state='complete',attempt_id=aid WHERE user_id=p_owner AND key=op.key;
  UPDATE public.object_metadata SET state='cleanup_pending',updated_at=clock_timestamp() WHERE id=op.upload_id AND user_id=p_owner AND state<>'deleted';RETURN v;
 WHEN 'fail_attempt' THEN
  UPDATE public.object_metadata SET state='cleanup_pending',updated_at=clock_timestamp() WHERE user_id=p_owner AND id IN (SELECT upload_id FROM public.operations WHERE user_id=p_owner AND key=(p_payload->>'key')::uuid AND state='processing') AND state<>'deleted';
  UPDATE public.operations SET state='failed' WHERE user_id=p_owner AND key=(p_payload->>'key')::uuid AND state='processing';RETURN 'null';
 WHEN 'upload_create' THEN
  sid:=(p_payload->>'session')::uuid;aid:=(p_payload->>'id')::uuid;
  IF NOT EXISTS(SELECT 1 FROM public.practice_sessions WHERE id=sid AND user_id=p_owner) THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Session not found'; END IF;
  IF NOT coalesce(speechclear_private.integer(p_payload->'size_bytes',1,12582912),false) OR jsonb_typeof(p_payload->'duration_seconds') IS DISTINCT FROM 'number' OR (p_payload->>'duration_seconds')::numeric NOT BETWEEN 30 AND 180 OR NOT coalesce((p_payload->>'suffix',p_payload->>'content_type') IN (('.webm','audio/webm'),('.mp4','audio/mp4'),('.m4a','audio/mp4'),('.wav','audio/wav'),('.mp3','audio/mpeg'),('.ogg','audio/ogg')),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid upload metadata'; END IF;
  INSERT INTO public.object_metadata(id,user_id,session_id,path,content_type,size_bytes,duration_seconds) VALUES(aid,p_owner,sid,p_owner::text||'/'||aid::text||'/response'||(p_payload->>'suffix'),p_payload->>'content_type',(p_payload->>'size_bytes')::bigint,(p_payload->>'duration_seconds')::numeric) RETURNING to_jsonb(object_metadata) INTO result;
  INSERT INTO public.audit_events(user_id,action) VALUES(p_owner,'upload_created');RETURN result;
 WHEN 'upload_get','upload_claim','upload_state','upload_write_check' THEN
  SELECT * INTO obj FROM public.object_metadata WHERE id=(p_payload->>'id')::uuid AND user_id=p_owner AND (NOT p_payload ? 'session' OR session_id=(p_payload->>'session')::uuid);
  IF NOT FOUND THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Upload not found'; END IF;
  IF p_action='upload_write_check' THEN
   IF obj.state<>'uploading' OR obj.expires_at<=clock_timestamp() OR obj.delete_after<=clock_timestamp() OR obj.updated_at<=clock_timestamp()-interval '3 minutes' THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Upload unavailable'; END IF;
   RETURN to_jsonb(obj);
  ELSIF p_action='upload_claim' THEN
   IF obj.state<>'authorized' OR obj.expires_at<=clock_timestamp() OR obj.delete_after<=clock_timestamp() THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Upload unavailable'; END IF;
   UPDATE public.object_metadata SET state='uploading',updated_at=clock_timestamp() WHERE id=obj.id RETURNING to_jsonb(object_metadata) INTO result;RETURN result;
  ELSIF p_action='upload_get' THEN
   IF obj.delete_after<=clock_timestamp() OR (obj.state NOT IN ('uploaded','processing') AND NOT EXISTS(SELECT 1 FROM public.operations WHERE upload_id=obj.id AND user_id=p_owner AND state='complete')) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Upload unavailable'; END IF;
   RETURN to_jsonb(obj);
  ELSE
   k:=p_payload->>'state';
   IF k IS NULL OR obj.state='deleted' OR k NOT IN ('uploaded','processing','cleanup_pending','deleted') OR (obj.delete_after<=clock_timestamp() AND k NOT IN ('cleanup_pending','deleted')) OR NOT (k=obj.state OR k='cleanup_pending' OR (obj.state='uploading' AND k='uploaded' AND obj.updated_at>clock_timestamp()-interval '10 minutes') OR (obj.state='uploaded' AND k='processing') OR (obj.state='cleanup_pending' AND k='deleted')) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Upload unavailable'; END IF;
   UPDATE public.object_metadata SET state=k,updated_at=clock_timestamp() WHERE id=obj.id RETURNING to_jsonb(object_metadata) INTO result;RETURN result;
  END IF;
 WHEN 'cleanup_claim' THEN
  SELECT * INTO obj FROM public.object_metadata WHERE id=(p_payload->>'id')::uuid AND user_id=p_owner FOR UPDATE;
  IF NOT FOUND OR obj.updated_at IS DISTINCT FROM (p_payload->>'updated_at')::timestamptz OR NOT (obj.state IN ('cleanup_pending','deleted') OR obj.delete_after<=clock_timestamp() OR (obj.state='authorized' AND obj.expires_at<=clock_timestamp()) OR (obj.state IN ('uploading','processing') AND obj.updated_at<=clock_timestamp()-interval '10 minutes')) THEN RETURN 'null'; END IF;
  IF obj.state<>'deleted' THEN
   UPDATE public.object_metadata SET state='cleanup_pending',updated_at=clock_timestamp() WHERE id=obj.id RETURNING * INTO obj;
  END IF;
  RETURN to_jsonb(obj);
 WHEN 'cleanup_list' THEN
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'user_id',user_id,'bucket',bucket,'path',path,'suffix',suffix,'content_type',content_type,'state',state,'session_id',session_id,'delete_after',delete_after,'updated_at',updated_at) ORDER BY delete_after,id),'[]') INTO result FROM public.object_metadata WHERE (state IN ('cleanup_pending','deleted') OR delete_after<=clock_timestamp() OR (state='authorized' AND expires_at<=clock_timestamp()) OR (state IN ('uploading','processing') AND updated_at<=clock_timestamp()-interval '10 minutes'));RETURN result;
 WHEN 'cleanup_done' THEN
  SELECT * INTO obj FROM public.object_metadata WHERE id=(p_payload->>'id')::uuid;
  IF NOT FOUND THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Upload not found'; END IF;
  IF obj.state<>'deleted' AND NOT (obj.state='cleanup_pending' OR obj.delete_after<=clock_timestamp() OR (obj.state='authorized' AND obj.expires_at<=clock_timestamp()) OR (obj.state IN ('uploading','processing') AND obj.updated_at<=clock_timestamp()-interval '10 minutes')) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Upload unavailable'; END IF;
  UPDATE public.object_metadata SET state='deleted',updated_at=clock_timestamp() WHERE id=obj.id;RETURN 'null';
 WHEN 'delete' THEN
  sid:=(p_payload->>'id')::uuid;
  IF sid IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.practice_sessions WHERE user_id=p_owner AND id=sid) THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Session not found'; END IF;
  UPDATE public.object_metadata SET state='cleanup_pending',session_id=NULL,updated_at=clock_timestamp() WHERE user_id=p_owner AND (sid IS NULL OR session_id=sid) AND state<>'deleted';
  DELETE FROM public.practice_sessions WHERE user_id=p_owner AND (sid IS NULL OR id=sid);
  INSERT INTO public.audit_events(user_id,action) VALUES(p_owner,CASE WHEN sid IS NULL THEN 'history_deleted' ELSE 'session_deleted' END);RETURN 'null';
 WHEN 'suspend' THEN
  IF jsonb_typeof(p_payload->'value') IS DISTINCT FROM 'boolean' THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid suspension'; END IF;
  active:=(p_payload->>'value')::boolean;
  INSERT INTO public.controls(user_id,suspended) VALUES(p_owner,active) ON CONFLICT(user_id) DO UPDATE SET suspended=excluded.suspended;
  INSERT INTO public.audit_events(user_id,action) VALUES(p_owner,CASE WHEN active THEN 'suspended' ELSE 'unsuspended' END);RETURN 'null';
 END CASE;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR datetime_field_overflow OR invalid_datetime_format OR check_violation OR not_null_violation THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid request fields';
 WHEN unique_violation THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Resource or key already exists';
 WHEN foreign_key_violation THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Resource unavailable';
END $$;
REVOKE ALL ON FUNCTION public.speechclear_api(text,uuid,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.speechclear_api(text,uuid,jsonb) TO service_role;
