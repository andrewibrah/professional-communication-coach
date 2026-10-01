"""Real PostgreSQL authorization/transaction tests, synthetic local rows only."""

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest


def session(id=None):
    return {
        "id": id,
        "scenario_id": "introduction",
        "goal": "Communicate clearly",
        "question": "Tell me about yourself.",
        "created_at": "2026-09-30T12:00:00+00:00",
        "context": "A synthetic local interview.",
        "example_response": "I help teams communicate.",
    }


def report() -> dict[str, Any]:
    return {
        "overall_score": 75,
        "category_scores": {
            "clarity": 75,
            "structure": 75,
            "conciseness": 75,
            "audience_fit": 75,
            "professional_tone": 75,
        },
        "communication_strengths": ["Clear"],
        "transcript_evidence": [{"quote": "I help teams", "observation": "Specific"}],
        "filler_words": [{"word": "um", "count": 0}],
        "jargon_flags": [],
        "pacing_observations": [],
        "weak_phrasing": [],
        "missed_questions": [],
        "priority_improvement": "Be brief",
        "suggested_practice_exercise": "Practice",
        "improved_answer": "I help teams.",
        "next_time_recommendation": "Lead with value",
    }


def attempt(session_id=None) -> dict[str, Any]:
    return {
        "id": I,
        "session_id": session_id or S,
        "transcript": "I help teams communicate clearly.",
        "duration_seconds": 29.94,
        "created_at": "2026-09-30T12:00:01+00:00",
        "report": report(),
    }


spec = importlib.util.spec_from_file_location(
    "verify_postgres",
    Path(__file__).resolve().parents[1] / "scripts/verify_postgres.py",
)
assert spec is not None and spec.loader is not None
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)
A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
S = "33333333-3333-4333-8333-333333333333"
T = "44444444-4444-4444-8444-444444444444"
K = "55555555-5555-4555-8555-555555555555"
I = "66666666-6666-4666-8666-666666666666"  # noqa: E741 — shared fixture identifier


@pytest.fixture
def db():
    with pg.disposable_database() as conn:
        conn.sql(f"INSERT INTO auth.users VALUES ('{A}'),('{B}');")
        yield conn


def test_cleanup_claim_rechecks_generation_and_retains_tombstones(db):
    db.rpc("save_session", A, {"data": session(S)})
    db.rpc(
        "upload_create",
        A,
        {
            "session": S,
            "id": I,
            "content_type": "audio/wav",
            "size_bytes": 10,
            "duration_seconds": 30,
            "suffix": ".wav",
        },
    )
    db.sql(
        f"UPDATE object_metadata SET expires_at=clock_timestamp()-interval '1 second' WHERE id='{I}';"
    )
    candidate = json.loads(db.rpc("cleanup_list", None).stdout)[0]
    db.sql(
        f"UPDATE object_metadata SET state='processing',updated_at=clock_timestamp() WHERE id='{I}';"
    )
    assert (
        json.loads(
            db.rpc(
                "cleanup_claim", A, {"id": I, "updated_at": candidate["updated_at"]}
            ).stdout
        )
        is None
    )
    db.rpc("upload_state", A, {"id": I, "state": "cleanup_pending"})
    candidate = json.loads(db.rpc("cleanup_list", None).stdout)[0]
    claim = json.loads(
        db.rpc(
            "cleanup_claim", A, {"id": I, "updated_at": candidate["updated_at"]}
        ).stdout
    )
    assert claim["state"] == "cleanup_pending"
    db.rpc("cleanup_done", A, {"id": I})
    tombstone = json.loads(db.rpc("cleanup_list", None).stdout)[0]
    assert tombstone["state"] == "deleted" and tombstone["suffix"] == ".wav"
    assert (
        json.loads(
            db.rpc(
                "cleanup_claim", A, {"id": I, "updated_at": tombstone["updated_at"]}
            ).stdout
        )["state"]
        == "deleted"
    )


def test_attempt_parent_is_immutable_even_for_service(db):
    db.rpc("save_session", A, {"data": session(S)})
    db.rpc("begin_attempt", A, {"session": S, "key": K, "daily": 20, "monthly": 200})
    db.rpc("finish_attempt", A, {"key": K, "attempt": attempt()})
    denied = db.sql(
        f"SET ROLE service_role; UPDATE attempts SET data=jsonb_set(data,'{{transcript}}','\"I help teams changed\"') WHERE id='{I}';",
        check=False,
    )
    assert denied.returncode and "Attempts are immutable" in denied.stderr
    db.sql(f"SET ROLE service_role; DELETE FROM attempts WHERE id='{I}';")


def test_existing_storage_policy_fails_closed():
    with pg.disposable_database(migrate=False) as conn:
        conn.sql(
            "CREATE POLICY unrelated_public_access ON storage.objects FOR ALL TO public USING (true) WITH CHECK (true);"
        )
        migration = next(
            (pg.ROOT / "supabase/migrations").glob("*speechclear.sql")
        ).read_text()
        with pytest.raises(AssertionError, match="Existing Storage policies"):
            conn.sql("BEGIN;" + migration + "COMMIT;")
        assert (
            conn.scalar("SELECT count(*) FROM pg_policies WHERE schemaname='storage';")
            == "1"
        )


def lock_holder(db, sql):
    import subprocess

    proc = subprocess.Popen(
        ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1"],
        env=db.env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    proc.stdin.write("BEGIN; " + sql + " SELECT 'ready';\n")
    proc.stdin.flush()
    while proc.stdout.readline().strip() != "ready":
        assert proc.poll() is None
    return proc


def wait_blocked(db, event):
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if (
            db.scalar(
                f"SELECT count(*) FROM pg_stat_activity WHERE wait_event='{event}' AND cardinality(pg_blocking_pids(pid))>0 AND query LIKE '%speechclear_api%';"
            )
            != "0"
        ):
            return
        time.sleep(0.02)
    raise AssertionError("No observed lock waiter")


def release_holder(proc):
    proc.stdin.write("COMMIT;\\q\n")
    proc.stdin.flush()
    proc.wait(timeout=5)


def test_quota_timestamp_captured_after_owner_lock(db):
    holder = lock_holder(
        db, f"SELECT pg_advisory_xact_lock(hashtextextended('{A}',0));"
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(db.rpc, "reserve", A, {"daily": 20, "monthly": 200})
        try:
            wait_blocked(db, "advisory")
            before_release = db.scalar("SELECT clock_timestamp();")
        finally:
            release_holder(holder)
        future.result(timeout=5)
    assert (
        db.scalar(
            f"SELECT created_at>='{before_release}'::timestamptz FROM usage_records;"
        )
        == "t"
    )
    definition = db.scalar(
        "SELECT pg_get_functiondef('public.speechclear_api(text,uuid,jsonb)'::regprocedure);"
    )
    assert "date_trunc('day',quota_at AT TIME ZONE 'UTC')" in definition
    assert "date_trunc('month',quota_at AT TIME ZONE 'UTC')" in definition


def test_import_crossowner_runtime_global_lock_and_sequence(db):
    rows = {
        k: []
        for k in (
            "profiles",
            "sessions",
            "attempts",
            "usage",
            "controls",
            "audit",
            "operations",
        )
    }
    rows["usage"] = [
        {"id": 100, "user_id": A, "created_at": "2026-09-30T12:00:00+00:00"}
    ]
    holder = lock_holder(
        db,
        "SELECT pg_advisory_xact_lock(hashtextextended('speechclear-global-import',0));",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        runtime = pool.submit(db.rpc, "reserve", B, {"daily": 20, "monthly": 200})
        importer = pool.submit(db.rpc, "import_legacy", A, rows)
        try:
            wait_blocked(db, "advisory")
            assert not runtime.done() and not importer.done()
        finally:
            release_holder(holder)
        runtime.result(timeout=5)
        importer.result(timeout=5)
    db.rpc("reserve", B, {"daily": 20, "monthly": 200})
    assert (
        int(db.scalar("SELECT max(id) FROM usage_records WHERE user_id='" + B + "';"))
        > 100
    )


def test_import_blocks_direct_insert_before_nextval(db):
    rows = {
        k: []
        for k in (
            "profiles",
            "sessions",
            "attempts",
            "usage",
            "controls",
            "audit",
            "operations",
        )
    }
    # Imported function acquires table lock even for empty payload; retain it in this transaction.
    body = json.dumps(rows).replace("'", "''")
    holder = lock_holder(db, f"SELECT speechclear_api('import_legacy','{A}','{body}');")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            db.sql,
            f"SET ROLE service_role; INSERT INTO usage_records(user_id) VALUES ('{B}');",
        )
        try:
            import time

            deadline = time.monotonic() + 5
            evidence = "0"
            while time.monotonic() < deadline:
                evidence = db.scalar(
                    "SELECT count(*) FROM pg_stat_activity WHERE wait_event='relation' AND cardinality(pg_blocking_pids(pid))>0 AND query LIKE '%INSERT INTO usage_records%';"
                )
                if evidence != "0":
                    break
                time.sleep(0.02)
            assert evidence != "0"
        finally:
            release_holder(holder)
        future.result(timeout=5)


def test_schema_roles_and_profile_ownership(db):
    names = db.scalar(
        "SELECT string_agg(tablename,',' ORDER BY tablename) FROM pg_tables WHERE schemaname='public' AND rowsecurity;"
    )
    for name in (
        "profiles",
        "practice_sessions",
        "attempts",
        "transcripts",
        "coaching_reports",
        "usage_records",
        "subscriptions",
        "audit_events",
        "documents",
        "object_metadata",
        "controls",
        "operations",
        "global_controls",
    ):
        assert name in names.split(",")
    assert db.sql("SET ROLE anon; SELECT * FROM profiles;", check=False).returncode
    db.sql(
        f"SET ROLE authenticated; SET request.jwt.claim.sub='{A}'; INSERT INTO profiles(user_id,data) VALUES ('{A}','{{}}');"
    )
    assert (
        db.scalar(
            f"SET ROLE authenticated; SET request.jwt.claim.sub='{B}'; SELECT count(*) FROM profiles;"
        )
        == "0"
    )
    assert db.sql(
        f"SET ROLE authenticated; SET request.jwt.claim.sub='{B}'; INSERT INTO profiles(user_id,data) VALUES ('{A}','{{}}');",
        check=False,
    ).returncode
    assert (
        db.scalar(
            f"SET ROLE authenticated; SET request.jwt.claim.sub='{B}'; UPDATE profiles SET data='{{}}' WHERE user_id='{A}'; DELETE FROM profiles WHERE user_id='{A}'; SELECT count(*) FROM profiles;"
        )
        == "0"
    )
    assert db.sql(
        f"SET ROLE authenticated; SELECT public.speechclear_api('profile','{A}','{{}}');",
        check=False,
    ).returncode


def test_atomic_attempt_contract(db):
    assert json.loads(db.rpc("profile", A).stdout)["role"] == ""
    db.rpc("save_session", A, {"data": session(S)})
    assert (
        json.loads(
            db.rpc(
                "begin_attempt",
                A,
                {"session": S, "key": K, "daily": 20, "monthly": 200},
            ).stdout
        )
        is None
    )
    db.rpc("finish_attempt", A, {"key": K, "attempt": attempt()})
    cached = json.loads(
        db.rpc(
            "begin_attempt", A, {"session": S, "key": K, "daily": 20, "monthly": 200}
        ).stdout
    )
    assert cached == attempt()
    detail = json.loads(db.rpc("session_detail", A, {"id": S}).stdout)
    assert detail["attempts"] == [attempt()]
    assert (
        json.loads(db.rpc("usage", A, {"daily": 999, "monthly": 999}).stdout)[
            "daily_limit"
        ]
        == 20
    )
    assert db.scalar(f"SELECT count(*) FROM usage_records WHERE user_id='{A}';") == "1"
    with pytest.raises(AssertionError, match="Session not found"):
        db.rpc("session", B, {"id": S})
    db.rpc("delete", A, {"id": S})
    assert db.scalar("SELECT count(*) FROM attempts;") == "0"
    assert db.scalar("SELECT count(*) FROM usage_records;") == "1"


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "float_score",
        "bool_score",
        "evidence",
        "empty_evidence",
        "too_many",
        "text_bound",
        "filler",
        "duration",
    ],
)
def test_strict_reports_and_rollback(db, mutation):
    db.rpc("save_session", A, {"data": session(S)})
    db.rpc("begin_attempt", A, {"session": S, "key": K, "daily": 20, "monthly": 200})
    value = attempt()
    r = value["report"]
    if mutation == "extra":
        r["secret"] = "bad"
    elif mutation == "float_score":
        r["overall_score"] = 75.0
    elif mutation == "bool_score":
        r["overall_score"] = True
    elif mutation == "evidence":
        r["transcript_evidence"][0]["quote"] = "Not present"
    elif mutation == "empty_evidence":
        r["transcript_evidence"] = []
    elif mutation == "too_many":
        r["communication_strengths"] = ["x"] * 31
    elif mutation == "text_bound":
        r["improved_answer"] = "x" * 6001
    elif mutation == "filler":
        r["filler_words"][0]["count"] = 10001
    elif mutation == "duration":
        value["duration_seconds"] = 29.84
    with pytest.raises(AssertionError, match="Invalid coaching report"):
        db.rpc("finish_attempt", A, {"key": K, "attempt": value})
    assert db.scalar("SELECT count(*) FROM attempts;") == "0"
    assert db.scalar("SELECT count(*) FROM transcripts;") == "0"
    assert db.scalar("SELECT count(*) FROM coaching_reports;") == "0"
    assert db.scalar("SELECT state FROM operations;") == "processing"
    assert db.scalar("SELECT count(*) FROM usage_records;") == "1"


def test_late_child_failure_and_binding_and_lease(db):
    db.rpc("save_session", A, {"data": session(S)})
    db.rpc("save_session", A, {"data": session(T)})
    db.rpc("begin_attempt", A, {"session": S, "key": K, "daily": 20, "monthly": 200})
    with pytest.raises(AssertionError, match="session mismatch"):
        db.rpc("finish_attempt", A, {"key": K, "attempt": attempt(T)})
    before = db.scalar("SELECT jsonb_agg(to_jsonb(o)) FROM operations o;")
    db.sql(
        "CREATE FUNCTION public.inject_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected late report failure'; END $$; CREATE TRIGGER report_failure BEFORE INSERT ON coaching_reports FOR EACH ROW EXECUTE FUNCTION public.inject_failure();"
    )
    with pytest.raises(AssertionError, match="injected late report failure"):
        db.rpc("finish_attempt", A, {"key": K, "attempt": attempt()})
    assert db.scalar("SELECT count(*) FROM attempts;") == "0"
    assert db.scalar("SELECT count(*) FROM transcripts;") == "0"
    assert db.scalar("SELECT jsonb_agg(to_jsonb(o)) FROM operations o;") == before
    db.sql(
        "DROP TRIGGER report_failure ON coaching_reports; UPDATE operations SET lease_until=now()-interval '1 second';"
    )
    with pytest.raises(AssertionError, match="lease expired"):
        db.rpc("finish_attempt", A, {"key": K, "attempt": attempt()})
    with pytest.raises(AssertionError, match="key unavailable"):
        db.rpc(
            "begin_attempt", A, {"session": S, "key": K, "daily": 20, "monthly": 200}
        )
    db.rpc("fail_attempt", A, {"key": K})
    assert db.scalar("SELECT state FROM operations;") == "failed"


def test_upload_authorization_single_use_cleanup(db):
    db.rpc("save_session", A, {"data": session(S)})
    meta = json.loads(
        db.rpc(
            "upload_create",
            A,
            {
                "session": S,
                "id": I,
                "content_type": "audio/webm",
                "size_bytes": 1234,
                "duration_seconds": 30,
                "suffix": ".webm",
            },
        ).stdout
    )
    assert meta["path"] == f"{A}/{I}/response.webm"
    assert meta["state"] == "authorized"
    with pytest.raises(AssertionError, match="Upload not found"):
        db.rpc("upload_claim", B, {"id": I, "session": S})
    assert json.loads(db.rpc("cleanup_list", A).stdout) == []
    db.rpc("upload_claim", A, {"id": I, "session": S})
    with pytest.raises(AssertionError, match="Upload unavailable"):
        db.rpc("upload_claim", A, {"id": I, "session": S})
    db.rpc("upload_state", A, {"id": I, "state": "uploaded"})
    assert (
        json.loads(db.rpc("upload_get", A, {"id": I, "session": S}).stdout)["state"]
        == "uploaded"
    )
    db.rpc(
        "begin_attempt",
        A,
        {"session": S, "key": K, "daily": 20, "monthly": 200, "upload_id": I},
    )
    with pytest.raises(AssertionError, match="Upload unavailable"):
        db.rpc(
            "begin_attempt",
            A,
            {"session": S, "key": T, "daily": 20, "monthly": 200, "upload_id": I},
        )
    db.rpc("delete", A, {"id": S})
    assert db.scalar("SELECT session_id IS NULL FROM object_metadata;") == "t"
    candidates = json.loads(db.rpc("cleanup_list", B).stdout)
    assert candidates[0]["path"] == meta["path"] and candidates[0]["user_id"] == A
    db.rpc("cleanup_done", A, {"id": I})
    assert db.scalar("SELECT state FROM object_metadata;") == "deleted"
    with pytest.raises(AssertionError, match="Upload unavailable"):
        db.rpc("upload_state", A, {"id": I, "state": "uploaded"})


def test_controls_and_real_concurrent_quota_and_keys(db):
    db.rpc("save_session", A, {"data": session(S)})
    db.rpc("suspend", A, {"value": True})
    with pytest.raises(AssertionError, match="suspended"):
        db.rpc("reserve", A, {"daily": 20, "monthly": 200})
    db.rpc("suspend", A, {"value": False})
    db.sql("UPDATE global_controls SET ai_enabled=false;")
    with pytest.raises(AssertionError, match="unavailable"):
        db.rpc("require_active", A)
    db.sql("UPDATE global_controls SET ai_enabled=true;")

    def claim(key):
        try:
            db.rpc(
                "begin_attempt", A, {"session": S, "key": key, "daily": 1, "monthly": 1}
            )
            return "ok"
        except AssertionError as e:
            return str(e)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [K, K]))
    assert results.count("ok") == 1 and any("key unavailable" in x for x in results)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [T, I]))
    assert all("quota reached" in x for x in results)
    assert db.scalar("SELECT count(*) FROM usage_records;") == "1"
    with ThreadPoolExecutor(max_workers=2) as pool:

        def reserve_once(_):
            try:
                db.rpc("reserve", B, {"daily": 1, "monthly": 1})
                return "ok"
            except AssertionError as exc:
                return str(exc)

        concurrent = list(pool.map(reserve_once, range(2)))
    assert concurrent.count("ok") == 1 and any("quota reached" in x for x in concurrent)


def test_import_legacy_transaction_and_receipt(db):
    rows: dict[str, Any] = {
        "profiles": [{"user_id": A, "data": {"role": "Engineer"}}],
        "sessions": [{"user_id": A, "id": S, "data": session(S)}],
        "attempts": [{"user_id": A, "id": I, "session_id": S, "data": attempt()}],
        "usage": [{"id": 41, "user_id": A, "created_at": "2026-09-30T12:00:00+00:00"}],
        "controls": [{"user_id": A, "suspended": 0}],
        "audit": [
            {
                "id": 42,
                "user_id": A,
                "action": "session_deleted",
                "created_at": "2026-09-30T12:00:00+00:00",
            }
        ],
        "operations": [
            {
                "user_id": A,
                "key": K,
                "session_id": S,
                "state": "complete",
                "attempt_id": I,
            }
        ],
        "fingerprint": "a" * 64,
    }
    result = json.loads(db.rpc("import_legacy", A, rows).stdout)
    assert result["counts"]["attempts"] == 1 and result["replayed"] is False
    assert json.loads(db.rpc("import_legacy", A, rows).stdout)["replayed"] is True
    assert db.scalar("SELECT id FROM usage_records;") == "41"
    assert db.scalar("SELECT id FROM audit_events;") == "42"
    assert json.loads(db.rpc("session_detail", A, {"id": S}).stdout)["attempts"] == [
        attempt()
    ]
    rows["fingerprint"] = "b" * 64
    rows["profiles"][0]["data"] = {"role": "Changed"}
    rows["sessions"][0]["id"] = T
    rows["sessions"][0]["data"] = session(T)
    rows["attempts"][0]["user_id"] = B
    with pytest.raises(AssertionError, match="Invalid legacy"):
        db.rpc("import_legacy", A, rows)
    assert json.loads(db.rpc("profile", A).stdout)["role"] == "Engineer"
    assert db.scalar("SELECT count(*) FROM practice_sessions;") == "1"


def test_actual_role_matrix_and_cross_owner_foreign_keys(db):
    db.rpc("profile", A, {"data": {"role": "Engineer"}})
    db.rpc("save_session", A, {"data": session(S)})
    db.rpc("begin_attempt", A, {"session": S, "key": K, "daily": 20, "monthly": 200})
    db.rpc("finish_attempt", A, {"key": K, "attempt": attempt()})
    db.rpc(
        "upload_create",
        A,
        {
            "session": S,
            "id": I,
            "content_type": "audio/webm",
            "size_bytes": 1234,
            "duration_seconds": 30,
            "suffix": ".webm",
        },
    )
    db.sql(
        f"INSERT INTO documents(id,user_id,name) VALUES ('{T}','{A}','local.txt'); INSERT INTO subscriptions(user_id) VALUES ('{A}'); INSERT INTO controls(user_id) VALUES ('{A}');"
    )
    for table in (
        "profiles",
        "practice_sessions",
        "attempts",
        "transcripts",
        "coaching_reports",
        "usage_records",
        "subscriptions",
        "audit_events",
        "documents",
        "object_metadata",
        "controls",
        "operations",
    ):
        assert (
            int(
                db.scalar(
                    f"SET ROLE authenticated; SET request.jwt.claim.sub='{A}'; SELECT count(*) FROM {table};"
                )
            )
            > 0
        )
        assert (
            db.scalar(
                f"SET ROLE authenticated; SET request.jwt.claim.sub='{B}'; SELECT count(*) FROM {table};"
            )
            == "0"
        )
        assert db.sql(f"SET ROLE anon; SELECT * FROM {table};", check=False).returncode
        if table != "profiles":
            for statement in (
                f"INSERT INTO {table} DEFAULT VALUES",
                f"UPDATE {table} SET user_id=user_id",
                f"DELETE FROM {table}",
            ):
                assert db.sql(
                    f"SET ROLE authenticated; SET request.jwt.claim.sub='{A}'; {statement};",
                    check=False,
                ).returncode
    for role in ("anon", "authenticated"):
        assert db.sql(
            f"SET ROLE {role}; SELECT public.speechclear_api('cleanup_list',NULL,'{{}}');",
            check=False,
        ).returncode
        assert (
            db.scalar(f"SET ROLE {role}; SELECT count(*) FROM storage.objects;") == "0"
        )
        assert db.sql(
            f"SET ROLE {role}; INSERT INTO storage.objects VALUES ('{I}','temporary-audio','{A}/{I}/response.webm');",
            check=False,
        ).returncode
    db.sql(
        f"INSERT INTO storage.objects VALUES ('{I}','temporary-audio','{A}/{I}/response.webm');"
    )
    for role in ("anon", "authenticated"):
        db.sql(
            f"SET ROLE {role}; SET request.jwt.claim.sub='{A}'; UPDATE storage.objects SET name='changed'; DELETE FROM storage.objects;"
        )
        assert (
            db.scalar(
                f"SET ROLE {role}; SET request.jwt.claim.sub='{A}'; SELECT count(*) FROM storage.objects;"
            )
            == "0"
        )
    assert db.scalar("SELECT count(*) FROM storage.objects;") == "1"
    assert db.sql(
        f"INSERT INTO transcripts(attempt_id,user_id,content) VALUES ('{I}','{B}','foreign');",
        check=False,
    ).returncode
    assert db.sql(
        f"INSERT INTO operations(user_id,key,session_id,state) VALUES ('{B}','{T}','{S}','processing');",
        check=False,
    ).returncode
    assert db.sql(
        f"INSERT INTO object_metadata(id,user_id,session_id,path,content_type,size_bytes) VALUES ('{T}','{B}','{S}','{B}/{T}/response.webm','audio/webm',5);",
        check=False,
    ).returncode
    db.sql(
        f"SET ROLE authenticated; SET request.jwt.claim.sub='{A}'; UPDATE profiles SET data='{{\"role\":\"Updated\"}}'; DELETE FROM profiles;"
    )
    assert db.scalar("SELECT count(*) FROM profiles;") == "0"


@pytest.mark.parametrize(
    "payload",
    [
        {"session": S, "key": K.upper(), "daily": 20, "monthly": 200},
        {"session": S, "key": "{" + K + "}", "daily": 20, "monthly": 200},
        {"session": S, "key": None, "daily": 20, "monthly": 200},
        {"session": S, "key": K, "daily": 20, "monthly": 200, "upload_id": None},
    ],
)
def test_reject_noncanonical_or_null_resource_identifiers(db, payload):
    db.rpc("save_session", A, {"data": session(S)})
    if payload["key"] == K and "upload_id" not in payload:
        payload["key"] = K.replace("55555555", "ABCDEFAB", 1)
    with pytest.raises(AssertionError, match="Invalid request fields"):
        db.rpc("begin_attempt", A, payload)
    assert db.scalar("SELECT count(*) FROM operations;") == "0"


def test_expired_upload_and_deleted_object_fence_completion(db):
    db.rpc("save_session", A, {"data": session(S)})
    args = {
        "session": S,
        "id": I,
        "content_type": "audio/webm",
        "size_bytes": 1234,
        "duration_seconds": 30,
        "suffix": ".webm",
    }
    db.rpc("upload_create", A, args)
    db.sql("UPDATE object_metadata SET expires_at=now()-interval '1 second';")
    with pytest.raises(AssertionError, match="Upload unavailable"):
        db.rpc("upload_claim", A, {"id": I, "session": S})
    assert len(json.loads(db.rpc("cleanup_list", B).stdout)) == 1
    db.sql("UPDATE object_metadata SET expires_at=created_at+interval '5 minutes';")
    db.rpc("upload_claim", A, {"id": I, "session": S})
    db.rpc("upload_state", A, {"id": I, "state": "uploaded"})
    db.rpc(
        "begin_attempt",
        A,
        {"session": S, "key": K, "daily": 20, "monthly": 200, "upload_id": I},
    )
    db.rpc("upload_state", A, {"id": I, "state": "cleanup_pending"})
    db.rpc("cleanup_done", B, {"id": I})
    with pytest.raises(AssertionError, match="Upload unavailable"):
        db.rpc("finish_attempt", A, {"key": K, "attempt": attempt()})
    assert db.scalar("SELECT count(*) FROM attempts;") == "0"


def test_advisory_lock_waiter_evidence(db):
    import subprocess
    import time

    holder = subprocess.Popen(
        ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1"],
        env=db.env | {"PGAPPNAME": "sc-holder"},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdin is not None and holder.stdout is not None
    try:
        holder.stdin.write(
            f"BEGIN; SELECT pg_advisory_xact_lock(hashtextextended('{A}',0)); SELECT 'ready';\n"
        )
        holder.stdin.flush()
        while holder.stdout.readline().strip() != "ready":
            assert holder.poll() is None
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(db.rpc, "reserve", A, {"daily": 1, "monthly": 1})
            deadline = time.monotonic() + 5
            evidence = "0"
            while time.monotonic() < deadline:
                evidence = db.scalar(
                    "SELECT count(*) FROM pg_stat_activity WHERE wait_event='advisory' AND cardinality(pg_blocking_pids(pid))>0 AND query LIKE '%speechclear_api%';"
                )
                if evidence == "1":
                    break
                time.sleep(0.02)
            if evidence != "1":
                holder.kill()
                holder.wait()
            assert evidence == "1"
            assert not future.done()
            holder.stdin.write("COMMIT;\\q\n")
            holder.stdin.flush()
            holder.wait(timeout=5)
            future.result(timeout=5)
        assert db.scalar("SELECT count(*) FROM usage_records;") == "1"
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()


def test_bucket_configuration_conflict_is_not_overwritten():
    with pg.disposable_database(migrate=False) as conn:
        conn.sql(
            "INSERT INTO storage.buckets VALUES ('temporary-audio','temporary-audio',false,12582912,ARRAY['text/plain']);"
        )
        before = conn.scalar(
            "SELECT to_jsonb(b) FROM storage.buckets b WHERE id='temporary-audio';"
        )
        migration = next(
            (pg.ROOT / "supabase/migrations").glob("*speechclear.sql")
        ).read_text()
        with pytest.raises(
            AssertionError, match="Existing bucket configuration mismatch"
        ):
            conn.sql(migration)
        assert (
            conn.scalar(
                "SELECT to_jsonb(b) FROM storage.buckets b WHERE id='temporary-audio';"
            )
            == before
        )


def test_import_late_failure_rolls_back_all_rows(db):
    rows = {
        "profiles": [{"user_id": A, "data": {"role": "Engineer"}}],
        "sessions": [{"user_id": A, "id": S, "data": session(S)}],
        "attempts": [{"user_id": A, "id": I, "session_id": S, "data": attempt()}],
        "usage": [{"id": 41, "user_id": A, "created_at": "2026-09-30T12:00:00+00:00"}],
        "controls": [{"user_id": A, "suspended": 0}],
        "audit": [
            {
                "id": 42,
                "user_id": A,
                "action": "session_deleted",
                "created_at": "2026-09-30T12:00:00+00:00",
            }
        ],
        "operations": [
            {
                "user_id": A,
                "key": K,
                "session_id": T,
                "state": "complete",
                "attempt_id": I,
            }
        ],
    }
    with pytest.raises(AssertionError, match="Resource unavailable"):
        db.rpc("import_legacy", A, rows)
    for table in (
        "profiles",
        "practice_sessions",
        "attempts",
        "transcripts",
        "coaching_reports",
        "usage_records",
        "controls",
        "audit_events",
        "operations",
        "speechclear_private.import_receipts",
    ):
        assert db.scalar(f"SELECT count(*) FROM {table};") == "0"


def test_database_child_validation_direct_trusted_writes(db):
    db.rpc("save_session", A, {"data": session(S)})
    db.rpc("begin_attempt", A, {"session": S, "key": K, "daily": 20, "monthly": 200})
    db.rpc("finish_attempt", A, {"key": K, "attempt": attempt()})
    assert db.sql(
        f"UPDATE coaching_reports SET data='{{}}' WHERE attempt_id='{I}';", check=False
    ).returncode
    assert db.sql(
        f"UPDATE transcripts SET content='Unrelated' WHERE attempt_id='{I}';",
        check=False,
    ).returncode


def test_upload_completed_cache_and_hard_retention(db):
    db.rpc("save_session", A, {"data": session(S)})
    db.rpc(
        "upload_create",
        A,
        {
            "session": S,
            "id": I,
            "content_type": "audio/webm",
            "size_bytes": 1234,
            "duration_seconds": 30,
            "suffix": ".webm",
        },
    )
    db.rpc("upload_claim", A, {"id": I, "session": S})
    db.rpc("upload_state", A, {"id": I, "state": "uploaded"})
    db.rpc(
        "begin_attempt",
        A,
        {"session": S, "key": K, "daily": 20, "monthly": 200, "upload_id": I},
    )
    db.rpc("finish_attempt", A, {"key": K, "attempt": attempt()})
    assert (
        json.loads(db.rpc("upload_get", A, {"id": I, "session": S}).stdout)["state"]
        == "cleanup_pending"
    )
    db.rpc("cleanup_done", None, {"id": I})
    assert (
        json.loads(
            db.rpc(
                "begin_attempt",
                A,
                {"session": S, "key": K, "daily": 20, "monthly": 200, "upload_id": I},
            ).stdout
        )
        == attempt()
    )
    assert db.sql(
        "UPDATE object_metadata SET delete_after=created_at+interval '25 hours';",
        check=False,
    ).returncode
    assert db.sql(
        "UPDATE object_metadata SET expires_at=created_at+interval '6 minutes';",
        check=False,
    ).returncode


def test_cluster_failure_cleanup_and_inherited_credentials_scrubbed(monkeypatch):
    import os

    monkeypatch.setenv("PGHOST", "remote.invalid")
    monkeypatch.setenv("PGSERVICE", "must-not-read-user-service")
    monkeypatch.setenv("PGPASSWORD", "synthetic-not-a-secret")
    base = None
    pid = None
    with (
        pytest.raises(RuntimeError, match="deliberate verifier failure"),
        pg.disposable_database(migrate=False) as conn,
    ):
        base = Path(conn.env["PGHOST"]).parent
        pid = int((base / "data/postmaster.pid").read_text().splitlines()[0])
        assert "PGPASSWORD" not in conn.env and "PGSERVICE" not in conn.env
        assert conn.scalar("SHOW listen_addresses;") == ""
        raise RuntimeError("deliberate verifier failure")
    assert base is not None and pid is not None
    assert not base.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_read_contracts_unknown_fields_and_monthly_quota(db):
    db.rpc("save_session", A, {"data": session(S)})
    assert json.loads(db.rpc("session", A, {"id": S}).stdout) == session(S)
    assert json.loads(db.rpc("attempts", A, {"id": S}).stdout) == []
    assert json.loads(db.rpc("sessions", A).stdout) == [
        session(S) | {"attempt_count": 0, "latest_score": None}
    ]
    with pytest.raises(AssertionError, match="Invalid request fields"):
        db.rpc("require_active", A, {"owner": B})
    with pytest.raises(AssertionError, match="Unknown action"):
        db.rpc("not_supported", A)
    db.rpc("reserve", A, {"daily": 20, "monthly": 1})
    with pytest.raises(AssertionError, match="quota reached"):
        db.rpc("reserve", A, {"daily": 20, "monthly": 1})
    db.rpc("delete", A)
    assert json.loads(db.rpc("sessions", A).stdout) == []
    assert db.scalar("SELECT count(*) FROM usage_records;") == "1"
