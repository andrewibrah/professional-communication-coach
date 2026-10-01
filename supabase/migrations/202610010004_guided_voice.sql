-- Dedicated Guided Voice persistence. No changes to Recorded Practice.
CREATE FUNCTION speechclear_private.guided_uuid(v jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_typeof(v)='string' AND (v#>>'{}') ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
$$;
CREATE FUNCTION speechclear_private.guided_children_valid(v jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,speechclear_private AS $$
DECLARE p jsonb; t jsonb; f jsonb; k text; n int:=0; seen text[]:=ARRAY[]::text[]; tids text[]:=ARRAY[]::text[]; items text[]:=ARRAY[]::text[];
BEGIN
 IF jsonb_typeof(v->'prompts') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'prompts')>3 OR jsonb_typeof(v->'turns') IS DISTINCT FROM 'array' OR jsonb_array_length(v->'turns')>9 THEN RETURN false; END IF;
 FOR p IN SELECT value FROM jsonb_array_elements(v->'prompts') LOOP
  IF NOT coalesce(exact(p,ARRAY['id','text','exercise_type','position']) AND guided_uuid(p->'id') AND txt(p->'text',1,240) AND p->>'exercise_type'='repetition' AND p->'position'=to_jsonb(n),false) OR p->>'id'=ANY(seen) THEN RETURN false; END IF;
  seen:=array_append(seen,p->>'id');n:=n+1;
 END LOOP;
 IF (n=0 AND (v->'prompt_index'<>'0'::jsonb OR v->'attempts_on_prompt'<>'0'::jsonb)) OR (n>0 AND (v->>'prompt_index')::int>=n) THEN RETURN false; END IF;
 FOR t IN SELECT value FROM jsonb_array_elements(v->'turns') LOOP
  IF NOT coalesce(exact(t,ARRAY['id','prompt_id','provider_item_id','attempt','transcript','feedback','prompt_visible','created_at']) AND guided_uuid(t->'id') AND guided_uuid(t->'prompt_id') AND t->>'prompt_id'=ANY(seen) AND txt(t->'provider_item_id',1,200) AND speechclear_private.integer(t->'attempt',1,(v->>'max_retries')::int+1) AND txt(t->'transcript',1,4000) AND jsonb_typeof(t->'prompt_visible')='boolean' AND txt(t->'created_at',1,64) AND (t->>'created_at') ~ '(Z|[+-][0-9]{2}:[0-9]{2})$' AND isfinite((t->>'created_at')::timestamptz),false) OR t->>'id'=ANY(tids) OR t->>'provider_item_id'=ANY(items) THEN RETURN false; END IF;
  IF (t->>'attempt')::int<>(SELECT count(*)+1 FROM unnest(tids) x JOIN jsonb_array_elements(v->'turns') e ON e->>'id'=x WHERE e->>'prompt_id'=t->>'prompt_id') THEN RETURN false; END IF;
  f:=t->'feedback';
  IF NOT coalesce(exact(f,ARRAY['prompt_id','strength','priority_correction','corrected_example','decision','evidence_basis','evidence_quote','spoken_feedback']) AND f->'prompt_id'=t->'prompt_id' AND f->>'decision' IN ('retry','next','simplify','finish') AND f->>'evidence_basis'='transcript' AND txt(f->'spoken_feedback',1,400),false) THEN RETURN false; END IF;
  FOREACH k IN ARRAY ARRAY['strength','priority_correction','corrected_example','evidence_quote'] LOOP
   IF f->k<>'null'::jsonb AND NOT coalesce(txt(f->k,1,400),false) THEN RETURN false; END IF;
  END LOOP;
  IF coalesce(length(f->>'strength'),0)+coalesce(length(f->>'priority_correction'),0)+coalesce(length(f->>'corrected_example'),0)+length(f->>'spoken_feedback')>400
   OR (SELECT count(*) FROM regexp_matches(f->>'spoken_feedback','[.!?]+(\s|$)','g'))>3
   OR (SELECT count(*) FROM regexp_matches(coalesce(f->>'priority_correction',''),'[.!?]+(\s|$)','g'))>1
   OR concat_ws(' ',f->>'strength',f->>'priority_correction',f->>'corrected_example',f->>'spoken_feedback') ~* '\m(pronunc\w*|prosody|intonation|pitch|volume|pacing|accent|cadence|loud\w*|softly|voice|audio|speaking speed|vocal|sounded|sound clear)\M' THEN RETURN false; END IF;
  IF f->'evidence_quote'<>'null'::jsonb AND strpos(t->>'transcript',f->>'evidence_quote')=0 THEN RETURN false; END IF;
  IF f->>'evidence_basis'='uncertain' AND (f->'evidence_quote'<>'null'::jsonb OR f->'priority_correction'<>'null'::jsonb OR f->'corrected_example'<>'null'::jsonb) THEN RETURN false; END IF;
  IF f->'priority_correction'<>'null'::jsonb AND f->'evidence_quote'='null'::jsonb THEN RETURN false; END IF;
  IF f->'strength'<>'null'::jsonb AND f->'evidence_quote'='null'::jsonb THEN RETURN false; END IF;
  tids:=array_append(tids,t->>'id');items:=array_append(items,t->>'provider_item_id');
 END LOOP;
 IF n>0 AND (v->>'attempts_on_prompt')::int<>(SELECT count(*) FROM jsonb_array_elements(v->'turns') e WHERE e->>'prompt_id'=seen[(v->>'prompt_index')::int+1]) THEN RETURN false; END IF;
 IF v->'recap'<>'null'::jsonb THEN
  f:=v->'recap';
  IF NOT coalesce(exact(f,ARRAY['practiced_exercises','completed_attempts','focus','next_practice']) AND speechclear_private.integer(f->'practiced_exercises',0,3) AND speechclear_private.integer(f->'completed_attempts',0,9) AND txt(f->'focus',1,400) AND txt(f->'next_practice',1,400) AND (f->>'completed_attempts')::int=jsonb_array_length(v->'turns') AND (f->>'practiced_exercises')::int=(SELECT count(DISTINCT e->>'prompt_id') FROM jsonb_array_elements(v->'turns') e),false) THEN RETURN false; END IF;
 END IF;
 RETURN true;
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE FUNCTION speechclear_private.guided_valid(v jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,speechclear_private AS $$
BEGIN
 RETURN coalesce(exact(v,ARRAY['id','scenario_id','goal','created_at','expires_at','state','revision','prompt_visible','muted','max_retries','prompts','prompt_index','attempts_on_prompt','turns','recap','status_message'])
 AND guided_uuid(v->'id') AND txt(v->'scenario_id',1,50) AND txt(v->'goal',1,1000)
 AND txt(v->'created_at',1,64) AND txt(v->'expires_at',1,64)
 AND (v->>'created_at') ~ '(Z|[+-][0-9]{2}:[0-9]{2})$' AND (v->>'expires_at') ~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
 AND isfinite((v->>'created_at')::timestamptz) AND isfinite((v->>'expires_at')::timestamptz)
 AND (v->>'expires_at')::timestamptz>(v->>'created_at')::timestamptz
 AND (v->>'expires_at')::timestamptz<=(v->>'created_at')::timestamptz+interval '600 seconds'
 AND v->>'state' IN ('created','connecting','coach_speaking','listening','reviewing','paused','reconnecting','finished','failed')
 AND speechclear_private.integer(v->'revision',0,2147483647) AND jsonb_typeof(v->'prompt_visible')='boolean' AND jsonb_typeof(v->'muted')='boolean'
 AND speechclear_private.integer(v->'max_retries',0,2) AND speechclear_private.integer(v->'prompt_index',0,2) AND speechclear_private.integer(v->'attempts_on_prompt',0,3)
 AND guided_children_valid(v) AND txt(v->'status_message',0,400),false);
EXCEPTION WHEN OTHERS THEN RETURN false;
END $$;
CREATE TABLE public.guided_sessions(
 id uuid PRIMARY KEY,user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 data jsonb NOT NULL CHECK(speechclear_private.guided_valid(data)),
 created_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
 UNIQUE(id,user_id),CHECK(data->>'id'=id::text AND (data->>'created_at')::timestamptz=created_at AND (data->>'expires_at')::timestamptz=expires_at));
-- No auth/session FK on operational receipts: auth or history deletion must not erase a live call.
CREATE TABLE speechclear_private.guided_reservations(
 id uuid PRIMARY KEY,owner uuid NOT NULL,request_hash bytea NOT NULL,created_at timestamptz NOT NULL,
 seconds int NOT NULL CHECK(seconds BETWEEN 1 AND 600),expires_at timestamptz NOT NULL,
 ended boolean NOT NULL DEFAULT false,deleted boolean NOT NULL DEFAULT false,
 request_fingerprint text CHECK(request_fingerprint ~ '^[0-9a-f]{64}$'),preparation_worker uuid,
 evaluations int NOT NULL DEFAULT 0 CHECK(evaluations BETWEEN 0 AND 12),
 text_tokens bigint NOT NULL DEFAULT 0 CHECK(text_tokens>=0),
 heartbeat_at timestamptz NOT NULL,paused_at timestamptz,claims int NOT NULL DEFAULT 0 CHECK(claims BETWEEN 0 AND 3),UNIQUE(id,owner));
ALTER TABLE public.guided_sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.guided_sessions FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.guided_sessions TO authenticated;
CREATE POLICY owner_select ON public.guided_sessions FOR SELECT TO authenticated USING(user_id=auth.uid());
ALTER TABLE speechclear_private.guided_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON speechclear_private.guided_reservations FROM PUBLIC,anon,authenticated,service_role;
CREATE INDEX guided_owner_created ON public.guided_sessions(user_id,created_at DESC,id);
CREATE INDEX guided_budget ON speechclear_private.guided_reservations(owner,created_at);

-- Trusted usage receipts only: no response bodies or transient user context.
CREATE TABLE speechclear_private.guided_text_usage(
 owner uuid NOT NULL,id uuid NOT NULL,response_id text NOT NULL CHECK(length(response_id) BETWEEN 1 AND 200),
 tokens int NOT NULL CHECK(tokens>=0),PRIMARY KEY(owner,id,response_id),
 FOREIGN KEY(id,owner) REFERENCES speechclear_private.guided_reservations(id,owner));
ALTER TABLE speechclear_private.guided_text_usage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON speechclear_private.guided_text_usage FROM PUBLIC,anon,authenticated,service_role;

CREATE TABLE public.guided_prompts(id uuid PRIMARY KEY,user_id uuid NOT NULL,session_id uuid NOT NULL,data jsonb NOT NULL,UNIQUE(id,session_id,user_id),FOREIGN KEY(session_id,user_id) REFERENCES public.guided_sessions(id,user_id) ON DELETE CASCADE);
CREATE TABLE public.guided_turns(id uuid PRIMARY KEY,user_id uuid NOT NULL,session_id uuid NOT NULL,prompt_id uuid NOT NULL,provider_item_id text NOT NULL,data jsonb NOT NULL,UNIQUE(session_id,provider_item_id),FOREIGN KEY(prompt_id,session_id,user_id) REFERENCES public.guided_prompts(id,session_id,user_id) ON DELETE CASCADE);
CREATE TABLE speechclear_private.guided_commands(owner uuid NOT NULL,id uuid NOT NULL,command_id uuid NOT NULL,request_hash bytea NOT NULL,result jsonb NOT NULL,request_fingerprint text CHECK(request_fingerprint ~ '^[0-9a-f]{64}$'),PRIMARY KEY(owner,id,command_id),FOREIGN KEY(id,owner) REFERENCES public.guided_sessions(id,user_id) ON DELETE CASCADE);
ALTER TABLE speechclear_private.guided_commands ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON speechclear_private.guided_commands FROM PUBLIC,anon,authenticated,service_role;
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['guided_prompts','guided_turns'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role',t);
  EXECUTE format('GRANT SELECT ON public.%I TO authenticated',t);
  EXECUTE format('CREATE POLICY owner_select ON public.%I FOR SELECT TO authenticated USING(user_id=auth.uid())',t);
 END LOOP;
END $$;
CREATE FUNCTION speechclear_private.guided_child_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE parent jsonb; value jsonb;
BEGIN
 IF TG_OP='UPDATE' THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided children immutable'; END IF;
 SELECT data INTO parent FROM public.guided_sessions WHERE id=NEW.session_id AND user_id=NEW.user_id;
 SELECT e INTO value FROM jsonb_array_elements(parent->CASE WHEN TG_TABLE_NAME='guided_prompts' THEN 'prompts' ELSE 'turns' END) e WHERE e->>'id'=NEW.id::text;
 IF value IS NULL OR value IS DISTINCT FROM NEW.data OR (TG_TABLE_NAME='guided_turns' AND (to_jsonb(NEW)->>'prompt_id' IS DISTINCT FROM value->>'prompt_id' OR to_jsonb(NEW)->>'provider_item_id' IS DISTINCT FROM value->>'provider_item_id')) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided child'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guided_prompt_guard BEFORE INSERT OR UPDATE ON public.guided_prompts FOR EACH ROW EXECUTE FUNCTION speechclear_private.guided_child_guard();
CREATE TRIGGER guided_turn_guard BEFORE INSERT OR UPDATE ON public.guided_turns FOR EACH ROW EXECUTE FUNCTION speechclear_private.guided_child_guard();
CREATE FUNCTION speechclear_private.guided_parent_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE k text; arr text;
BEGIN
 IF NEW.id<>OLD.id OR NEW.user_id<>OLD.user_id OR NEW.created_at<>OLD.created_at OR NEW.expires_at<>OLD.expires_at THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided identity immutable'; END IF;
 FOREACH k IN ARRAY ARRAY['id','scenario_id','goal','created_at','expires_at','max_retries'] LOOP
  IF NEW.data->k IS DISTINCT FROM OLD.data->k THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided settings immutable'; END IF;
 END LOOP;
 IF OLD.data->>'state' IN ('finished','failed') THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided session ended'; END IF;
 IF (NEW.data->>'revision')::int<>(OLD.data->>'revision')::int+1 THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided revision conflict'; END IF;
 FOREACH arr IN ARRAY ARRAY['prompts','turns'] LOOP
  IF jsonb_array_length(NEW.data->arr)<jsonb_array_length(OLD.data->arr) OR EXISTS(SELECT 1 FROM jsonb_array_elements(OLD.data->arr) WITH ORDINALITY e(value,i) WHERE value IS DISTINCT FROM NEW.data->arr->(i::int-1)) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided history immutable'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER guided_parent_guard BEFORE UPDATE ON public.guided_sessions FOR EACH ROW EXECUTE FUNCTION speechclear_private.guided_parent_guard();

CREATE TABLE speechclear_private.guided_leases(
 owner uuid NOT NULL,id uuid NOT NULL,worker_id uuid NOT NULL,call_id text UNIQUE,
 claim_until timestamptz NOT NULL,pending boolean NOT NULL DEFAULT false,ended boolean NOT NULL DEFAULT false,
 tokens int NOT NULL DEFAULT 0 CHECK(tokens>=0),ended_at timestamptz,
 PRIMARY KEY(owner,id,worker_id),FOREIGN KEY(id,owner) REFERENCES speechclear_private.guided_reservations(id,owner),
 CHECK(call_id IS NULL OR length(call_id) BETWEEN 1 AND 200));
ALTER TABLE speechclear_private.guided_leases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON speechclear_private.guided_leases FROM PUBLIC,anon,authenticated,service_role;
CREATE INDEX guided_termination ON speechclear_private.guided_leases(pending,ended);
CREATE FUNCTION speechclear_private.guided_lease_json(l speechclear_private.guided_leases) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT jsonb_build_object('owner',l.owner,'id',l.id,'worker_id',l.worker_id,'call_id',l.call_id) $$;
CREATE FUNCTION speechclear_private.guided_terminate(sid uuid,uid uuid) RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,speechclear_private,public AS $$
BEGIN
 UPDATE guided_sessions SET data=data||jsonb_build_object(
  'state','failed','status_message','Call ended','revision',(data->>'revision')::int+1,
  'recap',jsonb_build_object(
   'practiced_exercises',(SELECT count(DISTINCT e->>'prompt_id') FROM jsonb_array_elements(data->'turns') e),
   'completed_attempts',jsonb_array_length(data->'turns'),
   'focus',coalesce((SELECT e->'feedback'->>'priority_correction' FROM jsonb_array_elements(data->'turns') WITH ORDINALITY t(e,n) WHERE e->'feedback'->>'priority_correction' IS NOT NULL ORDER BY n DESC LIMIT 1),'Practice clear wording.'),
   'next_practice','Repeat the target sentences using the same clear wording.'))
 WHERE id=sid AND user_id=uid AND data->>'state' NOT IN ('finished','failed');
 UPDATE guided_reservations SET ended=true WHERE id=sid AND owner=uid;
 UPDATE guided_leases SET pending=true WHERE id=sid AND owner=uid AND NOT ended;
 UPDATE guided_leases SET ended=true,ended_at=clock_timestamp() WHERE id=sid AND owner=uid AND call_id IS NULL AND claim_until<=clock_timestamp();
END $$;
CREATE FUNCTION speechclear_private.guided_delete_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,speechclear_private AS $$
DECLARE uid uuid;
BEGIN
 IF TG_TABLE_SCHEMA='auth' THEN uid:=OLD.id;ELSE uid:=OLD.user_id;END IF;
 PERFORM pg_advisory_xact_lock_shared(hashtextextended('speechclear-global-import',0));
 PERFORM pg_advisory_xact_lock(hashtextextended(uid::text,0));
 UPDATE guided_reservations SET ended=true,deleted=true WHERE owner=uid AND (TG_TABLE_SCHEMA='auth' OR id=OLD.id);
 UPDATE guided_leases SET pending=true WHERE owner=uid AND NOT ended AND (TG_TABLE_SCHEMA='auth' OR id=OLD.id);
 RETURN OLD;
END $$;
CREATE TRIGGER guided_history_delete BEFORE DELETE ON public.guided_sessions FOR EACH ROW EXECUTE FUNCTION speechclear_private.guided_delete_guard();
CREATE TRIGGER guided_auth_delete BEFORE DELETE ON auth.users FOR EACH ROW EXECUTE FUNCTION speechclear_private.guided_delete_guard();

-- Account deletion is rare and cross-cuts every owned table. Serialize it globally
-- BEFORE PostgreSQL locks auth rows: a row trigger alone inverts owner/FK order.
CREATE FUNCTION speechclear_private.guided_auth_delete_boundary() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('speechclear-global-import',0));
 RETURN NULL;
END $$;
CREATE TRIGGER guided_auth_delete_boundary BEFORE DELETE ON auth.users FOR EACH STATEMENT EXECUTE FUNCTION speechclear_private.guided_auth_delete_boundary();

CREATE FUNCTION public.speechclear_guided_api(p_action text,p_owner uuid,p_payload jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,speechclear_private,public AS $$
DECLARE at timestamptz; v jsonb; result jsonb; allowed text[]; required text[]; k text; sid uuid;
 r speechclear_private.guided_reservations%ROWTYPE; daily int; monthly int; duration int; h bytea; old jsonb; e jsonb; receipt speechclear_private.guided_commands%ROWTYPE; l speechclear_private.guided_leases%ROWTYPE; uid uuid;
BEGIN
 IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided request'; END IF;
 CASE p_action
 WHEN 'reserve' THEN allowed:=ARRAY['data','daily_seconds','monthly_seconds','max_seconds','request_fingerprint'];required:=ARRAY['data','daily_seconds','monthly_seconds','max_seconds'];
 WHEN 'claim_preparation' THEN allowed:=ARRAY['id','worker_id'];required:=allowed;
 WHEN 'reserve_evaluation' THEN allowed:=ARRAY['id','worker_id'];required:=allowed;
 WHEN 'get','heartbeat','delete' THEN allowed:=ARRAY['id'];required:=allowed;
 WHEN 'list' THEN allowed:=ARRAY[]::text[];required:=allowed;
 WHEN 'commit' THEN allowed:=ARRAY['id','expected_revision','data','command_id','request_fingerprint'];required:=ARRAY['id','expected_revision','data'];
 WHEN 'command_result' THEN allowed:=ARRAY['id','command_id','request_fingerprint'];required:=ARRAY['id','command_id'];
 WHEN 'claim_connection' THEN allowed:=ARRAY['id','expected_revision','worker_id'];required:=allowed;
 WHEN 'attach' THEN allowed:=ARRAY['id','worker_id','call_id'];required:=allowed;
 WHEN 'release_call' THEN allowed:=ARRAY['id','worker_id','call_id','confirmed'];required:=allowed;
 WHEN 'usage' THEN allowed:=ARRAY['id','worker_id','tokens'];required:=allowed;
 WHEN 'text_usage' THEN allowed:=ARRAY['id','response_id','tokens'];required:=allowed;
 WHEN 'watchdog','metadata' THEN allowed:=ARRAY[]::text[];required:=allowed;
 ELSE RAISE SQLSTATE 'PT422' USING MESSAGE='Unknown guided action'; END CASE;
 IF EXISTS(SELECT 1 FROM jsonb_object_keys(p_payload) x WHERE NOT x=ANY(allowed)) OR NOT p_payload ?& required THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided request'; END IF;
 IF p_action IN ('watchdog','metadata') THEN
  IF p_owner IS NOT NULL THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid watchdog owner'; END IF;
 ELSIF p_owner IS NULL THEN RAISE SQLSTATE 'PT403' USING MESSAGE='Invalid owner'; END IF;
 IF p_payload ? 'id' AND NOT coalesce(guided_uuid(p_payload->'id'),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided identifier'; END IF;
 IF p_payload ? 'command_id' AND NOT coalesce(guided_uuid(p_payload->'command_id'),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided identifier'; END IF;
 IF p_payload ? 'request_fingerprint' AND (NOT coalesce(jsonb_typeof(p_payload->'request_fingerprint')='string' AND p_payload->>'request_fingerprint' ~ '^[0-9a-f]{64}$',false) OR (p_action<>'reserve' AND NOT p_payload ? 'command_id')) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided request'; END IF;
 IF p_payload ? 'worker_id' AND NOT coalesce(guided_uuid(p_payload->'worker_id'),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided identifier'; END IF;
 IF p_payload ? 'call_id' AND NOT coalesce(txt(p_payload->'call_id',1,200),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided call'; END IF;
 PERFORM pg_advisory_xact_lock_shared(hashtextextended('speechclear-global-import',0));
 IF p_owner IS NOT NULL THEN PERFORM pg_advisory_xact_lock(hashtextextended(p_owner::text,0)); END IF;
 IF p_owner IS NOT NULL AND p_action NOT IN ('release_call','usage','text_usage','attach','delete') AND NOT EXISTS(SELECT 1 FROM auth.users WHERE id=p_owner) THEN RAISE SQLSTATE 'PT403' USING MESSAGE='Invalid owner'; END IF;
 at:=clock_timestamp();
 CASE p_action
 WHEN 'metadata' THEN RETURN jsonb_build_object('schema','guided_voice','version',1);
 WHEN 'watchdog' THEN
  result:='[]';
  -- Recheck eligibility inside the same owner boundary as writers, in stable lock order.
  FOR uid IN SELECT DISTINCT owner FROM guided_reservations ORDER BY owner LOOP
   PERFORM pg_advisory_xact_lock(hashtextextended(uid::text,0));at:=clock_timestamp();
   FOR r IN SELECT * FROM guided_reservations WHERE owner=uid LOOP
    IF r.ended OR r.deleted OR r.expires_at<=at OR r.heartbeat_at<=at-interval '20 seconds' OR r.paused_at<=at-interval '30 seconds'
     OR NOT EXISTS(SELECT 1 FROM global_controls WHERE id AND ai_enabled) OR EXISTS(SELECT 1 FROM controls WHERE user_id=uid AND suspended)
     OR r.text_tokens+(SELECT coalesce(sum(tokens),0) FROM guided_leases WHERE id=r.id AND owner=uid)>=6000
     OR EXISTS(SELECT 1 FROM guided_leases WHERE id=r.id AND owner=uid AND NOT ended AND (pending OR (call_id IS NULL AND claim_until<=at))) THEN
     PERFORM guided_terminate(r.id,uid);
    END IF;
   END LOOP;
   FOR l IN SELECT * FROM guided_leases WHERE owner=uid AND pending AND NOT ended AND call_id IS NOT NULL ORDER BY id,worker_id LOOP result:=result||jsonb_build_array(guided_lease_json(l)); END LOOP;
  END LOOP;RETURN result;
 WHEN 'reserve' THEN
  v:=p_payload->'data';
  IF NOT guided_valid(v) OR v->'prompts'<>'[]'::jsonb OR v->'turns'<>'[]'::jsonb OR v->'recap'<>'null'::jsonb OR v->>'state'<>'created' OR v->'revision'<>'0'::jsonb OR v->'prompt_index'<>'0'::jsonb OR v->'attempts_on_prompt'<>'0'::jsonb
   OR NOT coalesce(speechclear_private.integer(p_payload->'daily_seconds',1,2147483647) AND speechclear_private.integer(p_payload->'monthly_seconds',1,2147483647) AND speechclear_private.integer(p_payload->'max_seconds',1,600),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided reservation'; END IF;
  sid:=(v->>'id')::uuid;h:=sha256(convert_to((p_payload||jsonb_build_object('data',v-ARRAY['created_at','expires_at']))::text,'UTF8'));
  SELECT * INTO r FROM guided_reservations WHERE id=sid;
  IF FOUND THEN
   IF r.owner<>p_owner OR r.request_hash<>h OR r.deleted OR r.request_fingerprint IS DISTINCT FROM p_payload->>'request_fingerprint' THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided reservation conflict'; END IF;
   SELECT data INTO result FROM guided_sessions WHERE id=sid AND user_id=p_owner;RETURN result;
  END IF;
  PERFORM 1 FROM global_controls WHERE id AND ai_enabled FOR SHARE;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM controls WHERE user_id=p_owner AND suspended) THEN RAISE SQLSTATE 'PT403' USING MESSAGE='AI unavailable or account suspended'; END IF;
  IF EXISTS(SELECT 1 FROM guided_reservations WHERE owner=p_owner AND NOT ended AND NOT deleted) OR EXISTS(SELECT 1 FROM guided_leases WHERE owner=p_owner AND NOT ended AND (call_id IS NOT NULL OR claim_until>at)) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided session already active'; END IF;
  daily:=least((p_payload->>'daily_seconds')::int,1800);monthly:=least((p_payload->>'monthly_seconds')::int,18000);duration:=(p_payload->>'max_seconds')::int;
  IF (SELECT coalesce(sum(seconds),0) FROM guided_reservations WHERE owner=p_owner AND created_at>=date_trunc('day',at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')+duration>daily
   OR (SELECT coalesce(sum(seconds),0) FROM guided_reservations WHERE owner=p_owner AND created_at>=date_trunc('month',at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')+duration>monthly THEN RAISE SQLSTATE 'PT429' USING MESSAGE='Guided quota reached'; END IF;
  v:=v||jsonb_build_object('created_at',at,'expires_at',at+make_interval(secs=>duration));
  INSERT INTO guided_reservations(id,owner,request_hash,created_at,seconds,expires_at,heartbeat_at,request_fingerprint) VALUES(sid,p_owner,h,at,duration,at+make_interval(secs=>duration),at,p_payload->>'request_fingerprint');
  INSERT INTO guided_sessions VALUES(sid,p_owner,v,at,at+make_interval(secs=>duration));RETURN v;
 WHEN 'text_usage' THEN
  sid:=(p_payload->>'id')::uuid;
  IF NOT coalesce(txt(p_payload->'response_id',1,200) AND speechclear_private.integer(p_payload->'tokens',0,2147483647),false) THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided text usage'; END IF;
  SELECT * INTO r FROM guided_reservations WHERE owner=p_owner AND id=sid;
  IF NOT FOUND THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Guided session not found'; END IF;
  SELECT tokens INTO duration FROM guided_text_usage WHERE owner=p_owner AND id=sid AND response_id=p_payload->>'response_id';
  IF FOUND THEN
   IF duration<>(p_payload->>'tokens')::int THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided text usage conflict'; END IF;
   RETURN 'null';
  END IF;
  INSERT INTO guided_text_usage VALUES(p_owner,sid,p_payload->>'response_id',(p_payload->>'tokens')::int);
  UPDATE guided_reservations SET text_tokens=text_tokens+(p_payload->>'tokens')::int WHERE owner=p_owner AND id=sid RETURNING * INTO r;
  IF r.text_tokens+(SELECT coalesce(sum(tokens),0) FROM guided_leases WHERE owner=p_owner AND id=sid)>=6000 THEN UPDATE guided_leases SET pending=true WHERE owner=p_owner AND id=sid AND NOT ended; END IF;
  RETURN 'null';
 WHEN 'reserve_evaluation' THEN
  sid:=(p_payload->>'id')::uuid;
  SELECT * INTO r FROM guided_reservations WHERE owner=p_owner AND id=sid;
  SELECT data INTO old FROM guided_sessions WHERE user_id=p_owner AND id=sid;
  SELECT * INTO l FROM guided_leases WHERE owner=p_owner AND id=sid AND worker_id=(p_payload->>'worker_id')::uuid;
  IF old IS NULL OR r.deleted THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Guided session not found'; END IF;
  IF r.ended OR r.expires_at<=at OR r.heartbeat_at<=at-interval '20 seconds' OR r.text_tokens+(SELECT coalesce(sum(tokens),0) FROM guided_leases WHERE owner=p_owner AND id=sid)>=6000 OR old->>'state'<>'reviewing' OR old->'muted'='true'::jsonb OR l.id IS NULL OR l.ended OR l.pending OR l.call_id IS NULL THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided evaluation unavailable'; END IF;
  PERFORM 1 FROM global_controls WHERE id AND ai_enabled FOR SHARE;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM controls WHERE user_id=p_owner AND suspended) THEN RAISE SQLSTATE 'PT403' USING MESSAGE='AI unavailable or account suspended'; END IF;
  IF r.evaluations>=12 THEN RAISE SQLSTATE 'PT429' USING MESSAGE='Guided evaluation limit reached'; END IF;
  UPDATE guided_reservations SET evaluations=evaluations+1 WHERE owner=p_owner AND id=sid;
  RETURN 'null';
 WHEN 'claim_preparation' THEN
  sid:=(p_payload->>'id')::uuid;
  SELECT * INTO r FROM guided_reservations WHERE owner=p_owner AND id=sid;
  SELECT data INTO old FROM guided_sessions WHERE user_id=p_owner AND id=sid;
  IF old IS NULL OR r.deleted THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Guided session not found'; END IF;
  IF r.preparation_worker IS NOT NULL OR old->>'state'<>'created' OR old->'prompts'<>'[]'::jsonb THEN RETURN 'false'; END IF;
  IF r.ended OR r.expires_at<=at OR r.heartbeat_at<=at-interval '20 seconds' OR r.text_tokens>=6000 THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided preparation expired'; END IF;
  PERFORM 1 FROM global_controls WHERE id AND ai_enabled FOR SHARE;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM controls WHERE user_id=p_owner AND suspended) THEN RAISE SQLSTATE 'PT403' USING MESSAGE='AI unavailable or account suspended'; END IF;
  UPDATE guided_reservations SET preparation_worker=(p_payload->>'worker_id')::uuid WHERE owner=p_owner AND id=sid;
  RETURN 'true';
 WHEN 'get' THEN
  SELECT data INTO result FROM guided_sessions WHERE id=(p_payload->>'id')::uuid AND user_id=p_owner;
  IF result IS NULL THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Guided session not found'; END IF;RETURN result;
 WHEN 'list' THEN SELECT coalesce(jsonb_agg(data ORDER BY created_at DESC,id),'[]') INTO result FROM guided_sessions WHERE user_id=p_owner;RETURN result;
 WHEN 'delete' THEN
  sid:=(p_payload->>'id')::uuid;
  IF NOT EXISTS(SELECT 1 FROM guided_reservations WHERE owner=p_owner AND id=sid) THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Guided session not found'; END IF;
  UPDATE guided_reservations SET ended=true,deleted=true WHERE owner=p_owner AND id=sid;
  UPDATE guided_leases SET pending=true WHERE owner=p_owner AND id=sid AND NOT ended;
  DELETE FROM guided_sessions WHERE user_id=p_owner AND id=sid;RETURN 'null';
 WHEN 'heartbeat' THEN
  sid:=(p_payload->>'id')::uuid;
  SELECT * INTO r FROM guided_reservations WHERE owner=p_owner AND id=sid;
  IF NOT FOUND OR r.deleted THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Guided session not found'; END IF;
  IF NOT r.ended AND (r.expires_at<=at OR r.heartbeat_at<=at-interval '20 seconds' OR r.paused_at<=at-interval '30 seconds') THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided session expired'; END IF;
  UPDATE guided_reservations SET heartbeat_at=at WHERE owner=p_owner AND id=sid AND NOT ended;
  SELECT data INTO result FROM guided_sessions WHERE id=sid AND user_id=p_owner;RETURN result;
 WHEN 'claim_connection' THEN
  sid:=(p_payload->>'id')::uuid;
  SELECT * INTO r FROM guided_reservations WHERE owner=p_owner AND id=sid;
  SELECT data INTO old FROM guided_sessions WHERE id=sid AND user_id=p_owner;
  IF old IS NULL OR r.deleted THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Guided session not found'; END IF;
  IF r.ended OR r.expires_at<=at OR r.heartbeat_at<=at-interval '20 seconds' OR r.paused_at<=at-interval '30 seconds' OR EXISTS(SELECT 1 FROM guided_leases WHERE owner=p_owner AND id=sid AND pending AND NOT ended) OR r.text_tokens+(SELECT coalesce(sum(tokens),0) FROM guided_leases WHERE owner=p_owner AND id=sid)>=6000 THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided lease unavailable'; END IF;
  PERFORM 1 FROM global_controls WHERE id AND ai_enabled FOR SHARE;
  IF NOT FOUND OR EXISTS(SELECT 1 FROM controls WHERE user_id=p_owner AND suspended) THEN RAISE SQLSTATE 'PT403' USING MESSAGE='AI unavailable or account suspended'; END IF;
  IF NOT coalesce(speechclear_private.integer(p_payload->'expected_revision',0,2147483647),false) OR old->'revision' IS DISTINCT FROM p_payload->'expected_revision' THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided revision conflict'; END IF;
  SELECT * INTO l FROM guided_leases WHERE owner=p_owner AND id=sid AND worker_id=(p_payload->>'worker_id')::uuid;
  IF FOUND THEN
   IF l.ended OR l.pending OR (l.call_id IS NULL AND l.claim_until<=at) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided lease unavailable'; END IF;RETURN guided_lease_json(l);
  END IF;
  UPDATE guided_leases SET ended=true,ended_at=at WHERE owner=p_owner AND id=sid AND call_id IS NULL AND claim_until<=at AND NOT ended;
  IF r.claims>=3 OR EXISTS(SELECT 1 FROM guided_leases WHERE owner=p_owner AND id=sid AND NOT ended) THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided lease unavailable'; END IF;
  INSERT INTO guided_leases(owner,id,worker_id,claim_until) VALUES(p_owner,sid,(p_payload->>'worker_id')::uuid,least(r.expires_at,at+interval '20 seconds')) RETURNING * INTO l;
  UPDATE guided_reservations SET claims=claims+1 WHERE id=sid AND owner=p_owner;RETURN guided_lease_json(l);
 WHEN 'attach','release_call','usage' THEN
  sid:=(p_payload->>'id')::uuid;
  SELECT * INTO l FROM guided_leases WHERE owner=p_owner AND id=sid AND worker_id=(p_payload->>'worker_id')::uuid;
  SELECT * INTO r FROM guided_reservations WHERE owner=p_owner AND id=sid;
  IF l.id IS NULL THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided lease unavailable'; END IF;
  IF p_action='attach' THEN
   IF l.call_id IS NOT NULL THEN
    IF l.call_id IS DISTINCT FROM p_payload->>'call_id' OR l.ended THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided lease conflict'; END IF;RETURN guided_lease_json(l);
   END IF;
   -- A provider may return after cancellation/TTL. Capture its handle for termination, never lose it.
   UPDATE guided_leases SET call_id=p_payload->>'call_id',ended=false,ended_at=NULL,
    pending=pending OR l.ended OR l.claim_until<=at OR r.ended OR r.deleted OR r.expires_at<=at OR r.heartbeat_at<=at-interval '20 seconds' OR coalesce(r.paused_at<=at-interval '30 seconds',false)
      OR NOT EXISTS(SELECT 1 FROM global_controls WHERE id AND ai_enabled) OR EXISTS(SELECT 1 FROM controls WHERE user_id=p_owner AND suspended)
    WHERE owner=p_owner AND id=sid AND worker_id=l.worker_id RETURNING * INTO l;RETURN guided_lease_json(l);
  ELSIF p_action='release_call' THEN
   IF jsonb_typeof(p_payload->'confirmed') IS DISTINCT FROM 'boolean' THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided release'; END IF;
   IF l.call_id IS DISTINCT FROM p_payload->>'call_id' THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided lease conflict'; END IF;
   UPDATE guided_leases SET pending=true,ended=ended OR (p_payload->>'confirmed')::boolean,ended_at=CASE WHEN (p_payload->>'confirmed')::boolean THEN coalesce(ended_at,at) ELSE ended_at END WHERE owner=p_owner AND id=sid AND worker_id=l.worker_id;RETURN 'null';
  ELSE
   IF NOT coalesce(speechclear_private.integer(p_payload->'tokens',0,2147483647),false) OR (p_payload->>'tokens')::int<l.tokens THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided usage'; END IF;
   UPDATE guided_leases SET tokens=(p_payload->>'tokens')::int WHERE owner=p_owner AND id=sid AND worker_id=l.worker_id;
   IF r.text_tokens+(SELECT coalesce(sum(tokens),0) FROM guided_leases WHERE owner=p_owner AND id=sid)>=6000 THEN UPDATE guided_leases SET pending=true WHERE owner=p_owner AND id=sid AND NOT ended; END IF;RETURN 'null';
  END IF;
 WHEN 'command_result' THEN
  SELECT c.* INTO receipt FROM guided_commands c JOIN guided_sessions s ON s.id=c.id AND s.user_id=c.owner WHERE c.owner=p_owner AND c.id=(p_payload->>'id')::uuid AND c.command_id=(p_payload->>'command_id')::uuid;
  IF FOUND THEN
   IF receipt.request_fingerprint IS DISTINCT FROM p_payload->>'request_fingerprint' THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided command conflict'; END IF;RETURN receipt.result;
  END IF;RETURN 'null';
 WHEN 'commit' THEN
  sid:=(p_payload->>'id')::uuid;v:=p_payload->'data';h:=sha256(convert_to(p_payload::text,'UTF8'));
  SELECT * INTO receipt FROM guided_commands WHERE owner=p_owner AND id=sid AND command_id=(p_payload->>'command_id')::uuid;
  IF FOUND THEN
   IF receipt.request_hash<>h OR receipt.request_fingerprint IS DISTINCT FROM p_payload->>'request_fingerprint' THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided command conflict'; END IF;RETURN receipt.result;
  END IF;
  SELECT data INTO old FROM guided_sessions WHERE id=sid AND user_id=p_owner;
  SELECT * INTO r FROM guided_reservations WHERE id=sid AND owner=p_owner;
  IF old IS NULL OR r.deleted THEN RAISE SQLSTATE 'PT404' USING MESSAGE='Guided session not found'; END IF;
  IF r.ended THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided session ended'; END IF;
  FOREACH k IN ARRAY ARRAY['id','scenario_id','goal','created_at','expires_at','max_retries'] LOOP
   IF v->k IS DISTINCT FROM old->k THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided settings immutable'; END IF;
  END LOOP;
  IF NOT coalesce(speechclear_private.integer(p_payload->'expected_revision',0,2147483646),false) OR old->'revision' IS DISTINCT FROM p_payload->'expected_revision' OR v->'revision' IS DISTINCT FROM p_payload->'expected_revision' THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided revision conflict'; END IF;
  IF v->>'state' NOT IN ('finished','failed') THEN
   PERFORM 1 FROM global_controls WHERE id AND ai_enabled FOR SHARE;
   IF NOT FOUND OR EXISTS(SELECT 1 FROM controls WHERE user_id=p_owner AND suspended) THEN RAISE SQLSTATE 'PT403' USING MESSAGE='AI unavailable or account suspended'; END IF;
   IF r.expires_at<=at OR r.heartbeat_at<=at-interval '20 seconds' OR r.paused_at<=at-interval '30 seconds' OR EXISTS(SELECT 1 FROM guided_leases WHERE owner=p_owner AND id=sid AND pending AND NOT ended) OR r.text_tokens+(SELECT coalesce(sum(tokens),0) FROM guided_leases WHERE owner=p_owner AND id=sid)>=6000 THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided session expired'; END IF;
  END IF;
  v:=v||jsonb_build_object('revision',(p_payload->>'expected_revision')::int+1);
  IF NOT guided_valid(v) OR v->>'id'<>sid::text THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided snapshot'; END IF;
  UPDATE guided_sessions SET data=v WHERE id=sid AND user_id=p_owner;
  FOR e IN SELECT value FROM jsonb_array_elements(v->'prompts') LOOP
   IF NOT EXISTS(SELECT 1 FROM guided_prompts WHERE id=(e->>'id')::uuid AND session_id=sid AND user_id=p_owner) THEN INSERT INTO guided_prompts VALUES((e->>'id')::uuid,p_owner,sid,e); END IF;
  END LOOP;
  FOR e IN SELECT value FROM jsonb_array_elements(v->'turns') LOOP
   IF NOT EXISTS(SELECT 1 FROM guided_turns WHERE id=(e->>'id')::uuid AND session_id=sid AND user_id=p_owner) THEN INSERT INTO guided_turns VALUES((e->>'id')::uuid,p_owner,sid,(e->>'prompt_id')::uuid,e->>'provider_item_id',e); END IF;
  END LOOP;
  UPDATE guided_reservations SET ended=v->>'state' IN ('finished','failed'),paused_at=CASE WHEN v->>'state'='paused' THEN coalesce(paused_at,at) ELSE NULL END WHERE id=sid;
  IF v->>'state' IN ('finished','failed') THEN UPDATE guided_leases SET pending=true WHERE owner=p_owner AND id=sid AND NOT ended; END IF;
  IF p_payload ? 'command_id' THEN INSERT INTO guided_commands(owner,id,command_id,request_hash,result,request_fingerprint) VALUES(p_owner,sid,(p_payload->>'command_id')::uuid,h,v,p_payload->>'request_fingerprint'); END IF;RETURN v;
 END CASE;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR datetime_field_overflow OR invalid_datetime_format OR check_violation OR not_null_violation THEN RAISE SQLSTATE 'PT422' USING MESSAGE='Invalid guided request';
 WHEN unique_violation OR foreign_key_violation THEN RAISE SQLSTATE 'PT409' USING MESSAGE='Guided resource conflict';
END $$;
REVOKE ALL ON FUNCTION public.speechclear_guided_api(text,uuid,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.speechclear_guided_api(text,uuid,jsonb) TO service_role;
REVOKE ALL ON FUNCTION speechclear_private.guided_uuid(jsonb),speechclear_private.guided_valid(jsonb) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION speechclear_private.guided_children_valid(jsonb),speechclear_private.guided_child_guard(),speechclear_private.guided_parent_guard() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION speechclear_private.guided_lease_json(speechclear_private.guided_leases),speechclear_private.guided_terminate(uuid,uuid),speechclear_private.guided_delete_guard() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION speechclear_private.guided_auth_delete_boundary() FROM PUBLIC,anon,authenticated,service_role;
