"""Synthetic, Unix-socket PostgreSQL proof for Guided Voice persistence."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_postgres_schema import lock_holder, release_holder

from scripts.verify_postgres import disposable_database

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
S = "33333333-3333-4333-8333-333333333333"
T = "44444444-4444-4444-8444-444444444444"
W = "55555555-5555-4555-8555-555555555555"
P = "66666666-6666-4666-8666-666666666666"
C = "77777777-7777-4777-8777-777777777777"


def initial(id=S):
    return dict(
        id=id,
        scenario_id="introduction",
        goal="Speak clearly",
        created_at="2026-10-01T00:00:00+00:00",
        expires_at="2026-10-01T00:05:00+00:00",
        state="created",
        revision=0,
        prompt_visible=True,
        muted=False,
        max_retries=2,
        prompts=[],
        prompt_index=0,
        attempts_on_prompt=0,
        turns=[],
        recap=None,
        status_message="Ready",
    )


@pytest.fixture
def db():
    with disposable_database() as conn:
        conn.sql(f"INSERT INTO auth.users VALUES ('{A}'),('{B}');")
        yield conn


def rpc(
    db, action, owner: str | None = A, payload=None, role="service_role", check=True
):
    body = json.dumps(payload or {}).replace("'", "''")
    uid = "NULL" if owner is None else "'" + owner + "'"
    result = db.sql(
        f"SET ROLE {role}; SELECT public.speechclear_guided_api('{action}',{uid},'{body}'::jsonb);",
        check=check,
    )
    return json.loads(result.stdout) if check else result


def reserve(db, owner=A, data=None, **limits):
    return rpc(
        db,
        "reserve",
        owner,
        dict(
            data=data or initial(),
            daily_seconds=1800,
            monthly_seconds=18000,
            max_seconds=300,
        )
        | limits,
    )


def test_reservation_is_idempotent_db_clock_owned_and_private(db):
    value = reserve(db)
    assert value["state"] == "created" and value["revision"] == 0
    assert value["created_at"] != initial()["created_at"]
    assert (
        db.scalar(
            "SELECT extract(epoch from expires_at-created_at) FROM guided_sessions;"
        )
        == "300.000000"
    )
    assert reserve(db) == value
    assert rpc(db, "get", A, {"id": S}) == value
    assert rpc(db, "list", A) == [value]
    assert rpc(db, "list", B) == []
    assert (
        db.scalar("SELECT count(*) FROM speechclear_private.guided_reservations;")
        == "1"
    )
    with pytest.raises(AssertionError, match="conflict"):
        reserve(db, data=initial() | {"goal": "Different"})
    with pytest.raises(AssertionError, match="active"):
        reserve(db, data=initial(T))
    for role in ("anon", "authenticated"):
        assert rpc(db, "get", A, {"id": S}, role=role, check=False).returncode
        assert db.sql(
            f"SET ROLE {role}; SELECT * FROM speechclear_private.guided_reservations;",
            check=False,
        ).returncode
    assert (
        db.scalar(
            f"SET ROLE authenticated; SET request.jwt.claim.sub='{B}'; SELECT count(*) FROM guided_sessions;"
        )
        == "0"
    )
    assert (
        db.scalar(
            f"SET ROLE authenticated; SET request.jwt.claim.sub='{A}'; SELECT count(*) FROM guided_sessions;"
        )
        == "1"
    )
    assert db.sql(
        f"SET ROLE authenticated; DELETE FROM guided_sessions WHERE id='{S}';",
        check=False,
    ).returncode


def prompt(id=P, position=0):
    return dict(
        id=id,
        text="I communicate clearly.",
        exercise_type="repetition",
        position=position,
    )


def turn():
    return dict(
        id=T,
        prompt_id=P,
        provider_item_id="item_1",
        attempt=1,
        transcript="I communicate clearly.",
        feedback=dict(
            prompt_id=P,
            strength="Clear",
            priority_correction=None,
            corrected_example=None,
            decision="next",
            evidence_basis="transcript",
            evidence_quote="communicate",
            spoken_feedback="Clear. Try the next phrase.",
        ),
        prompt_visible=True,
        created_at="2026-10-01T00:00:00+00:00",
    )


def commit(db, value, revision=None, key=None, owner=A):
    args = dict(
        id=value["id"],
        expected_revision=value["revision"] if revision is None else revision,
        data=value,
    )
    if key is not None:
        args["command_id"] = key
    return rpc(db, "commit", owner, args)


def test_atomic_cas_append_only_children_receipts_and_rollback(db):
    base = reserve(db)
    candidate = base | {"state": "connecting", "prompts": [prompt()]}
    saved = commit(db, candidate, key=C)
    assert saved["revision"] == 1 and saved["prompts"] == [prompt()]
    assert commit(db, candidate, key=C) == saved
    assert rpc(db, "command_result", A, {"id": S, "command_id": C}) == saved
    assert rpc(db, "command_result", A, {"id": S, "command_id": W}) is None
    with pytest.raises(AssertionError, match="conflict"):
        commit(db, candidate | {"status_message": "Changed"}, key=C)
    with pytest.raises(AssertionError, match="revision"):
        commit(db, candidate)
    with pytest.raises(AssertionError, match="immutable"):
        commit(db, saved | {"prompts": [prompt() | {"text": "Changed"}]})
    with pytest.raises(AssertionError, match="immutable"):
        commit(db, saved | {"expires_at": "2026-10-01T00:06:00+00:00"})
    attempt = saved | {"state": "reviewing", "turns": [turn()], "attempts_on_prompt": 1}
    db.sql(
        "CREATE FUNCTION public.guided_inject() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'guided late failure'; END $$; CREATE TRIGGER guided_failure BEFORE INSERT ON guided_turns FOR EACH ROW EXECUTE FUNCTION public.guided_inject();"
    )
    with pytest.raises(AssertionError, match="guided late failure"):
        commit(db, attempt, key=W)
    assert rpc(db, "get", A, {"id": S}) == saved
    assert db.scalar("SELECT count(*) FROM guided_turns;") == "0"
    assert rpc(db, "command_result", A, {"id": S, "command_id": W}) is None
    db.sql("DROP TRIGGER guided_failure ON guided_turns;")
    complete = commit(db, attempt, key=W)
    assert complete["revision"] == 2
    assert db.scalar("SELECT count(*) FROM guided_prompts;") == "1"
    assert db.scalar("SELECT count(*) FROM guided_turns;") == "1"
    assert db.sql(
        f"UPDATE guided_turns SET data=jsonb_set(data,'{{transcript}}','\"Injected\"') WHERE id='{T}';",
        check=False,
    ).returncode
    with pytest.raises(AssertionError):
        commit(db, complete | {"turns": [turn(), turn() | {"id": W, "attempt": 2}]})
    ended = commit(db, complete | {"state": "finished"})
    with pytest.raises(AssertionError, match="ended"):
        commit(db, ended | {"state": "listening"})


def test_command_receipts_require_exact_request_fingerprint_and_legacy_parity(db):
    base = reserve(db)
    candidate = base | {"state": "connecting", "prompts": [prompt()]}
    args = dict(
        id=S,
        expected_revision=0,
        data=candidate,
        command_id=C,
        request_fingerprint="a" * 64,
    )
    saved = rpc(db, "commit", A, args)
    lookup = dict(id=S, command_id=C, request_fingerprint="a" * 64)
    assert rpc(db, "command_result", A, lookup) == saved
    assert rpc(db, "commit", A, args) == saved
    # Reusing a UUID for a different action/raw request must not return the old DTO.
    for changed in (
        lookup | {"request_fingerprint": "b" * 64},
        dict(id=S, command_id=C),
    ):
        with pytest.raises(AssertionError, match="command conflict"):
            rpc(db, "command_result", A, changed)
    with pytest.raises(AssertionError, match="command conflict"):
        rpc(db, "commit", A, args | {"request_fingerprint": "b" * 64})
    with pytest.raises(AssertionError, match="command conflict"):
        rpc(
            db,
            "commit",
            A,
            {k: v for k, v in args.items() if k != "request_fingerprint"},
        )
    legacy = commit(db, saved | {"state": "listening"}, key=W)
    assert rpc(db, "command_result", A, dict(id=S, command_id=W)) == legacy
    with pytest.raises(AssertionError, match="command conflict"):
        rpc(
            db,
            "command_result",
            A,
            dict(id=S, command_id=W, request_fingerprint="a" * 64),
        )
    for invalid in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, None, 123):
        with pytest.raises(AssertionError, match="Invalid guided request"):
            rpc(db, "command_result", A, lookup | {"request_fingerprint": invalid})
    with pytest.raises(AssertionError, match="Invalid guided request"):
        rpc(
            db,
            "commit",
            A,
            dict(id=S, expected_revision=2, data=legacy, request_fingerprint="a" * 64),
        )
    assert rpc(db, "get", A, {"id": S}) == legacy


def claim(db, worker=W, revision=0):
    return rpc(
        db,
        "claim_connection",
        A,
        dict(id=S, expected_revision=revision, worker_id=worker),
    )


def attach(db, worker=W, call="rtc_first"):
    return rpc(db, "attach", A, dict(id=S, worker_id=worker, call_id=call))


def release(db, worker=W, call="rtc_first", confirmed=True):
    return rpc(
        db,
        "release_call",
        A,
        dict(id=S, worker_id=worker, call_id=call, confirmed=confirmed),
    )


def test_durable_lease_fencing_usage_termination_delete_and_auth_cascade(db):
    base = reserve(db)
    lease = claim(db)
    assert lease == dict(owner=A, id=S, worker_id=W, call_id=None)
    assert claim(db) == lease
    with pytest.raises(AssertionError, match="lease"):
        claim(db, C)
    live = attach(db)
    assert live == dict(owner=A, id=S, worker_id=W, call_id="rtc_first")
    assert attach(db) == live
    with pytest.raises(AssertionError, match="lease"):
        attach(db, call="rtc_second")
    assert rpc(db, "heartbeat", A, {"id": S}) == base
    assert rpc(db, "usage", A, dict(id=S, worker_id=W, tokens=3000)) is None
    with pytest.raises(AssertionError, match="usage"):
        rpc(db, "usage", A, dict(id=S, worker_id=W, tokens=2999))
    # Trusted worker submits aggregate voice + transcription cumulative usage.
    rpc(db, "usage", A, dict(id=S, worker_id=W, tokens=6001))
    assert rpc(db, "watchdog", None) == [live]
    assert rpc(db, "get", A, {"id": S})["state"] == "failed"
    with pytest.raises(AssertionError):
        commit(db, base | {"state": "listening"})
    release(db, confirmed=False)
    assert rpc(db, "watchdog", None) == [live]
    with pytest.raises(AssertionError, match="lease"):
        release(db, worker=C)
    release(db)
    assert rpc(db, "watchdog", None) == []
    assert release(db) is None
    rpc(db, "delete", A, {"id": S})
    assert rpc(db, "list", A) == []
    with pytest.raises(AssertionError):
        reserve(db)
    assert (
        db.scalar("SELECT sum(seconds) FROM speechclear_private.guided_reservations;")
        == "300"
    )
    # Deletion of an account with an unknown live call never loses its exact handle.
    reserve(db, data=initial(T))
    rpc(db, "claim_connection", A, dict(id=T, expected_revision=0, worker_id=C))
    rpc(db, "attach", A, dict(id=T, worker_id=C, call_id="rtc_account_delete"))
    db.sql(f"DELETE FROM auth.users WHERE id='{A}';")
    expected = dict(owner=A, id=T, worker_id=C, call_id="rtc_account_delete")
    assert rpc(db, "watchdog", None) == [expected]
    assert (
        rpc(
            db,
            "release_call",
            A,
            dict(id=T, worker_id=C, call_id="rtc_account_delete", confirmed=True),
        )
        is None
    )
    assert rpc(db, "watchdog", None) == []
    assert db.scalar("SELECT count(*) FROM guided_sessions;") == "0"


def test_pending_deleted_live_call_blocks_new_reservation_and_wipes_content(db):
    base = reserve(db)
    saved = commit(db, base | {"state": "connecting", "prompts": [prompt()]}, key=C)
    saved = commit(db, saved | {"turns": [turn()], "attempts_on_prompt": 1}, key=T)
    claim(db, revision=2)
    live = attach(db)
    rpc(db, "delete", A, {"id": S})
    for table in (
        "guided_sessions",
        "guided_prompts",
        "guided_turns",
        "speechclear_private.guided_commands",
    ):
        assert db.scalar(f"SELECT count(*) FROM {table};") == "0"
    assert rpc(db, "command_result", A, {"id": S, "command_id": C}) is None
    with pytest.raises(AssertionError, match="active"):
        reserve(db, data=initial(T))
    assert rpc(db, "watchdog", None) == [live]
    release(db)
    assert reserve(db, data=initial(T))["id"] == T
    assert (
        db.scalar("SELECT sum(seconds) FROM speechclear_private.guided_reservations;")
        == "600"
    )


def test_pause_grace_is_thirty_seconds_with_independent_twenty_second_heartbeat(db):
    base = reserve(db)
    claim(db)
    live = attach(db)
    paused = commit(db, base | {"state": "paused"})
    db.sql(
        "UPDATE speechclear_private.guided_reservations SET paused_at=clock_timestamp()-interval '25 seconds';"
    )
    assert rpc(db, "heartbeat", A, {"id": S}) == paused
    assert claim(db, revision=1) == live
    assert rpc(db, "watchdog", None) == []
    # A repeated pause must not reset the original grace deadline.
    same_pause = db.scalar(
        "SELECT paused_at FROM speechclear_private.guided_reservations;"
    )
    paused = commit(db, paused | {"status_message": "Still paused"})
    assert (
        db.scalar("SELECT paused_at FROM speechclear_private.guided_reservations;")
        == same_pause
    )
    db.sql(
        "UPDATE speechclear_private.guided_reservations SET paused_at=clock_timestamp()-interval '31 seconds';"
    )
    for action, payload in (
        ("heartbeat", {"id": S}),
        ("claim_connection", dict(id=S, expected_revision=2, worker_id=W)),
        (
            "commit",
            dict(id=S, expected_revision=2, data=paused | {"state": "listening"}),
        ),
    ):
        with pytest.raises(AssertionError):
            rpc(db, action, A, payload)
    assert rpc(db, "watchdog", None) == [live]
    assert rpc(db, "get", A, {"id": S})["state"] == "failed"


def test_attach_after_pause_expiry_records_pending_exact_handle(db):
    base = reserve(db)
    claim(db)
    commit(db, base | {"state": "paused"})
    db.sql(
        "UPDATE speechclear_private.guided_reservations SET paused_at=clock_timestamp()-interval '31 seconds';"
    )
    assert attach(db)["call_id"] == "rtc_first"
    assert db.scalar("SELECT pending FROM speechclear_private.guided_leases;") == "t"
    assert rpc(db, "watchdog", None) == [
        dict(owner=A, id=S, worker_id=W, call_id="rtc_first")
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        "feedback_total",
        "multiple_corrections",
        "audio_claim",
        "uncertain_turn",
        "empty_transcript",
        "long_prompt",
    ],
)
def test_content_validation_rejects_unsafe_trusted_snapshots(db, mutation):
    base = reserve(db)
    candidate = base | {
        "state": "connecting",
        "prompts": [prompt()],
        "turns": [turn()],
        "attempts_on_prompt": 1,
    }
    f = candidate["turns"][0]["feedback"]
    if mutation == "feedback_total":
        f["strength"] = "x" * 390
    elif mutation == "multiple_corrections":
        f["priority_correction"] = "Be clear. Be brief."
    elif mutation == "audio_claim":
        f["strength"] = "Your pronunciation is clear."
    elif mutation == "uncertain_turn":
        f.update(
            strength=None,
            evidence_quote=None,
            evidence_basis="uncertain",
            decision="clarify",
        )
    elif mutation == "empty_transcript":
        candidate["turns"][0]["transcript"] = ""
        f.update(strength=None, evidence_quote=None)
    elif mutation == "long_prompt":
        candidate["prompts"][0]["text"] = "x" * 241
    with pytest.raises(AssertionError, match="Invalid guided snapshot"):
        commit(db, candidate)
    assert rpc(db, "get", A, {"id": S}) == base
    assert db.scalar("SELECT count(*) FROM guided_turns;") == "0"


def test_creation_replay_ignores_only_server_owned_times(db):
    base = reserve(db)
    same = initial() | {
        "created_at": "2026-10-02T00:00:00+00:00",
        "expires_at": "2026-10-02T00:05:00+00:00",
    }
    assert reserve(db, data=same) == base
    assert (
        db.scalar("SELECT count(*) FROM speechclear_private.guided_reservations;")
        == "1"
    )


def wait_guided_waiters(db, count=1, action=None):
    """Observe real advisory waiters and their blockers, not concurrent launch."""
    import time

    deadline = time.monotonic() + 5
    predicate = "query LIKE '%speechclear_guided_api%'"
    if action is not None:
        predicate += f" AND query LIKE '%''{action}''%'"
    while time.monotonic() < deadline:
        rows = json.loads(
            db.scalar(
                f"SELECT coalesce(json_agg(json_build_object('pid',pid,'blockers',pg_blocking_pids(pid))),'[]') FROM pg_stat_activity WHERE wait_event='advisory' AND cardinality(pg_blocking_pids(pid))>0 AND {predicate};"
            )
        )
        if len(rows) >= count:
            assert len({r["pid"] for r in rows}) == len(rows)
            return rows
        time.sleep(0.02)
    raise AssertionError(f"Expected {count} observed Guided advisory waiters")


def reservation_query(id, **limits):
    payload = (
        dict(
            data=initial(id), daily_seconds=1800, monthly_seconds=18000, max_seconds=300
        )
        | limits
    )
    return f"SELECT public.speechclear_guided_api('reserve','{A}','{json.dumps(payload)}'::jsonb);"


def test_owner_lock_serializes_max_active_and_cas_with_observed_waiters(db):
    holder = lock_holder(
        db, f"SELECT pg_advisory_xact_lock(hashtextextended('{A}',0));"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                db.sql, "SET ROLE service_role; " + reservation_query(id), check=False
            )
            for id in (S, T)
        ]
        try:
            wait_guided_waiters(db, 2, "reserve")
            assert all(not f.done() for f in futures)
        finally:
            release_holder(holder)
        results = [f.result(timeout=5) for f in futures]
    assert sorted(r.returncode == 0 for r in results) == [False, True]
    assert "already active" in next(r.stderr for r in results if r.returncode)
    assert (
        db.scalar("SELECT count(*) FROM speechclear_private.guided_reservations;")
        == "1"
    )
    saved = rpc(db, "list", A)[0]
    holder = lock_holder(
        db, f"SELECT pg_advisory_xact_lock(hashtextextended('{A}',0));"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                rpc,
                db,
                "commit",
                A,
                dict(
                    id=saved["id"],
                    expected_revision=0,
                    data=saved | {"status_message": msg},
                    command_id=key,
                    request_fingerprint=fp * 64,
                ),
                check=False,
            )
            for msg, key, fp in (("First", C, "a"), ("Second", W, "b"))
        ]
        try:
            wait_guided_waiters(db, 2, "commit")
            assert all(not f.done() for f in futures)
        finally:
            release_holder(holder)
        results = [f.result(timeout=5) for f in futures]
    assert sorted(r.returncode == 0 for r in results) == [False, True]
    assert "revision conflict" in next(r.stderr for r in results if r.returncode)
    assert rpc(db, "get", A, {"id": saved["id"]})["revision"] == 1
    assert db.scalar("SELECT count(*) FROM speechclear_private.guided_commands;") == "1"


def test_daily_hardcap_nonrefund_and_quota_contention_with_observed_waiters(db):
    from uuid import UUID

    for index in range(5):
        id = str(UUID(int=index + 100))
        reserve(db, data=initial(id), daily_seconds=999999, monthly_seconds=999999)
        rpc(db, "delete", A, {"id": id})
    assert (
        db.scalar("SELECT sum(seconds) FROM speechclear_private.guided_reservations;")
        == "1500"
    )
    holder = lock_holder(
        db, f"SELECT pg_advisory_xact_lock(hashtextextended('{A}',0));"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        # Reserve + delete atomically removes max-active as a confounder.
        futures = [
            pool.submit(
                db.sql,
                "BEGIN; SET ROLE service_role; "
                + reservation_query(id, daily_seconds=999999, monthly_seconds=999999)
                + f" SELECT public.speechclear_guided_api('delete','{A}','{{\"id\":\"{id}\"}}'); COMMIT;",
                check=False,
            )
            for id in (S, T)
        ]
        try:
            wait_guided_waiters(db, 2, "reserve")
            assert all(not f.done() for f in futures)
        finally:
            release_holder(holder)
        results = [f.result(timeout=5) for f in futures]
    assert sorted(r.returncode == 0 for r in results) == [False, True]
    assert "quota reached" in next(r.stderr for r in results if r.returncode)
    assert (
        db.scalar("SELECT sum(seconds) FROM speechclear_private.guided_reservations;")
        == "1800"
    )
    assert rpc(db, "list", A) == []
    assert (
        db.scalar("SELECT count(*) FROM speechclear_private.guided_reservations;")
        == "6"
    )
    with pytest.raises(AssertionError, match="quota reached"):
        reserve(db, data=initial(C), daily_seconds=999999, monthly_seconds=999999)


def test_lower_monthly_budget_and_owner_isolation(db):
    for id in (S, T):
        reserve(db, data=initial(id), monthly_seconds=600)
        rpc(db, "delete", A, {"id": id})
    with pytest.raises(AssertionError, match="quota reached"):
        reserve(db, data=initial(C), monthly_seconds=600)
    assert reserve(db, owner=B, data=initial(W), monthly_seconds=600)["id"] == W


def test_guided_quota_clock_is_captured_after_observed_owner_lock_wait(db):
    holder = lock_holder(
        db, f"SELECT pg_advisory_xact_lock(hashtextextended('{A}',0));"
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(reserve, db)
        try:
            wait_guided_waiters(db, 1, "reserve")
            threshold = db.scalar("SELECT clock_timestamp();")
        finally:
            release_holder(holder)
        saved = future.result(timeout=5)
    assert (
        db.scalar(
            f"SELECT created_at>='{threshold}'::timestamptz AND heartbeat_at=created_at AND expires_at=created_at+interval '300 seconds' FROM speechclear_private.guided_reservations;"
        )
        == "t"
    )
    assert saved["created_at"] == rpc(db, "get", A, {"id": S})["created_at"]
    definition = db.scalar(
        "SELECT pg_get_functiondef('public.speechclear_guided_api(text,uuid,jsonb)'::regprocedure);"
    )
    assert "date_trunc('day',at AT TIME ZONE 'UTC')" in definition
    assert "date_trunc('month',at AT TIME ZONE 'UTC')" in definition
    assert "monthly:=least((p_payload->>'monthly_seconds')::int,18000)" in definition


def test_multiworker_watchdog_order_and_after_lock_eligibility_recheck(db):
    reserve(db)
    reserve(db, owner=B, data=initial(T))
    db.sql(
        f"UPDATE speechclear_private.guided_reservations SET heartbeat_at=clock_timestamp()-interval '21 seconds' WHERE owner='{B}';"
    )
    holder = lock_holder(
        db, f"SELECT pg_advisory_xact_lock(hashtextextended('{B}',0));"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(rpc, db, "watchdog", None)
        try:
            wait_guided_waiters(db, 1, "watchdog")
            second = pool.submit(rpc, db, "watchdog", None)
            rows = wait_guided_waiters(db, 2, "watchdog")
            assert any(r["pid"] in other["blockers"] for r in rows for other in rows)
            assert holder.stdin is not None and holder.stdout is not None
            holder.stdin.write(
                f"UPDATE speechclear_private.guided_reservations SET heartbeat_at=clock_timestamp() WHERE owner='{B}'; SELECT 'refreshed';\n"
            )
            holder.stdin.flush()
            assert holder.stdout.readline().strip() == "refreshed"
        finally:
            release_holder(holder)
        assert first.result(timeout=5) == [] and second.result(timeout=5) == []
    assert rpc(db, "get", A, {"id": S})["state"] == "created"
    assert rpc(db, "get", B, {"id": T})["state"] == "created"


@pytest.mark.parametrize("expiry", ["heartbeat", "absolute"])
def test_heartbeat_and_absolute_timeout_remain_independent_of_pause_grace(db, expiry):
    reserve(db)
    claim(db)
    live = attach(db)
    column = "heartbeat_at" if expiry == "heartbeat" else "expires_at"
    amount = "21 seconds" if expiry == "heartbeat" else "1 second"
    db.sql(
        f"UPDATE speechclear_private.guided_reservations SET {column}=clock_timestamp()-interval '{amount}';"
    )
    with pytest.raises(AssertionError, match="expired"):
        rpc(db, "heartbeat", A, {"id": S})
    assert rpc(db, "watchdog", None) == [live]


@pytest.mark.parametrize("reason", ["claim_expired", "history_deleted", "auth_deleted"])
def test_late_callback_tombstone_survives_deletion(db, reason):
    reserve(db)
    claim(db)
    if reason == "claim_expired":
        db.sql(
            "UPDATE speechclear_private.guided_leases SET claim_until=clock_timestamp()-interval '1 second';"
        )
        assert rpc(db, "watchdog", None) == []
    elif reason == "history_deleted":
        rpc(db, "delete", A, {"id": S})
    else:
        db.sql(f"DELETE FROM auth.users WHERE id='{A}';")
    late = attach(db, call="rtc_late_private_handle")
    assert (
        db.scalar(
            "SELECT pending AND NOT ended FROM speechclear_private.guided_leases WHERE call_id='rtc_late_private_handle';"
        )
        == "t"
    )
    assert rpc(db, "watchdog", None) == [late]
    release(db, call="rtc_late_private_handle")
    assert rpc(db, "watchdog", None) == []


def test_auth_delete_does_not_invert_inflight_reservation_lock_order(db):
    # Stop a real reserve after its owner lock, immediately before the auth FK write.
    db.sql(
        f"CREATE FUNCTION public.guided_reserve_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_xact_lock(hashtextextended('{P}',0)); RETURN NEW; END $$; CREATE TRIGGER guided_reserve_barrier BEFORE INSERT ON speechclear_private.guided_reservations FOR EACH ROW EXECUTE FUNCTION public.guided_reserve_barrier();"
    )
    holder = lock_holder(
        db, f"SELECT pg_advisory_xact_lock(hashtextextended('{P}',0));"
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        reservation = pool.submit(reserve, db)
        try:
            wait_guided_waiters(db, 1, "reserve")
            deletion = pool.submit(db.sql, f"DELETE FROM auth.users WHERE id='{A}';")
            import time

            deadline = time.monotonic() + 5
            count = "0"
            while time.monotonic() < deadline:
                count = db.scalar(
                    "SELECT count(*) FROM pg_stat_activity WHERE query LIKE 'DELETE FROM auth.users%' AND cardinality(pg_blocking_pids(pid))>0;"
                )
                if count != "0":
                    break
                time.sleep(0.02)
            assert count == "1" and not deletion.done()
        finally:
            release_holder(holder)
        assert reservation.result(timeout=5)["id"] == S
        assert deletion.result(timeout=5).returncode == 0
    assert db.scalar("SELECT count(*) FROM guided_sessions;") == "0"
    assert (
        db.scalar(
            "SELECT ended AND deleted FROM speechclear_private.guided_reservations;"
        )
        == "t"
    )


def test_operational_lease_fk_binds_owner_to_reservation(db):
    reserve(db)
    with pytest.raises(AssertionError, match="foreign key"):
        db.sql(
            f"INSERT INTO speechclear_private.guided_leases(owner,id,worker_id,claim_until) VALUES('{B}','{S}','{W}',clock_timestamp()+interval '20 seconds');"
        )
    assert db.scalar("SELECT count(*) FROM speechclear_private.guided_leases;") == "0"


def test_guided_generated_children_owner_isolation_and_helper_privileges(db):
    base = reserve(db)
    saved = commit(
        db, base | {"prompts": [prompt()], "turns": [turn()], "attempts_on_prompt": 1}
    )
    for table in ("guided_sessions", "guided_prompts", "guided_turns"):
        assert (
            db.scalar(
                f"SET ROLE authenticated; SET request.jwt.claim.sub='{A}'; SELECT count(*) FROM {table};"
            )
            == "1"
        )
        assert (
            db.scalar(
                f"SET ROLE authenticated; SET request.jwt.claim.sub='{B}'; SELECT count(*) FROM {table};"
            )
            == "0"
        )
        for role in ("anon", "authenticated", "service_role"):
            assert (
                db.scalar(
                    f"SELECT has_table_privilege('{role}','public.{table}','INSERT,UPDATE,DELETE');"
                )
                == "f"
            )
    for table in ("guided_reservations", "guided_commands", "guided_leases"):
        for role in ("anon", "authenticated", "service_role"):
            assert (
                db.scalar(
                    f"SELECT has_table_privilege('{role}','speechclear_private.{table}','SELECT,INSERT,UPDATE,DELETE');"
                )
                == "f"
            )
    for role in ("anon", "authenticated", "service_role"):
        assert (
            db.scalar(
                f"SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='speechclear_private' AND p.proname LIKE 'guided_%' AND has_function_privilege('{role}',p.oid,'EXECUTE');"
            )
            == "0"
        )
    with pytest.raises(AssertionError, match="immutable"):
        db.sql(
            f"UPDATE guided_prompts SET data=data||'{{\"text\":\"Changed\"}}' WHERE id='{P}';"
        )
    with pytest.raises(AssertionError, match="Invalid guided child"):
        db.sql(
            f"INSERT INTO guided_prompts VALUES('{W}','{A}','{S}','{json.dumps(prompt(W))}');"
        )
    with pytest.raises(AssertionError, match="Invalid guided child"):
        db.sql(
            f"INSERT INTO guided_prompts VALUES('{C}','{B}','{S}','{json.dumps(prompt(C))}');"
        )
    assert rpc(db, "get", A, {"id": S}) == saved
    assert all(
        "call_id" not in entry and "worker_id" not in entry
        for entry in rpc(db, "list", A)
    )


def test_reconnect_usage_is_cumulative_and_generation_is_fenced(db):
    reserve(db)
    claim(db)
    attach(db)
    rpc(db, "usage", A, dict(id=S, worker_id=W, tokens=3500))
    release(db)
    assert claim(db, worker=C)["call_id"] is None
    attach(db, worker=C, call="rtc_reconnect")
    rpc(db, "usage", A, dict(id=S, worker_id=C, tokens=2500))
    assert (
        db.scalar("SELECT sum(tokens) FROM speechclear_private.guided_leases;")
        == "6000"
    )
    expected = dict(owner=A, id=S, worker_id=C, call_id="rtc_reconnect")
    assert rpc(db, "watchdog", None) == [expected]
    with pytest.raises(AssertionError, match="lease"):
        claim(db, worker=T)
    with pytest.raises(AssertionError, match="lease"):
        attach(db, worker=W, call="rtc_reconnect")
    with pytest.raises(AssertionError, match="lease"):
        release(db, worker=C, call="rtc_first")
    assert rpc(db, "watchdog", None) == [expected]


def test_connection_claim_budget_and_late_replaced_generation(db):
    reserve(db)
    claim(db)
    db.sql(
        "UPDATE speechclear_private.guided_leases SET claim_until=clock_timestamp()-interval '1 second';"
    )
    claim(db, worker=C)
    current = attach(db, worker=C, call="rtc_current_generation")
    late = attach(db, worker=W, call="rtc_late_generation")
    assert (
        db.scalar(
            f"SELECT pending FROM speechclear_private.guided_leases WHERE worker_id='{W}';"
        )
        == "t"
    )
    handles = rpc(db, "watchdog", None)
    assert sorted(handles, key=lambda lease: lease["worker_id"]) == sorted(
        [late, current], key=lambda lease: lease["worker_id"]
    )
    release(db, worker=W, call="rtc_late_generation")
    release(db, worker=C, call="rtc_current_generation")
    assert rpc(db, "watchdog", None) == []
    rpc(db, "delete", A, {"id": S})
    reserve(db, data=initial(T))
    for worker in (W, C, P):
        rpc(
            db, "claim_connection", A, dict(id=T, expected_revision=0, worker_id=worker)
        )
        call = "rtc_" + worker
        rpc(db, "attach", A, dict(id=T, worker_id=worker, call_id=call))
        rpc(
            db,
            "release_call",
            A,
            dict(id=T, worker_id=worker, call_id=call, confirmed=True),
        )
    with pytest.raises(AssertionError, match="lease unavailable"):
        rpc(db, "claim_connection", A, dict(id=T, expected_revision=0, worker_id=S))
    assert (
        db.scalar(
            f"SELECT claims FROM speechclear_private.guided_reservations WHERE id='{T}';"
        )
        == "3"
    )


def test_guided_privilege_boundary_survives_managed_default_grants():
    from scripts.verify_postgres import ROOT

    with disposable_database(migrate=False) as db:
        paths = sorted((ROOT / "supabase/migrations").glob("*.sql"))
        for migration in paths[:-1]:
            db.sql("BEGIN;" + migration.read_text() + "COMMIT;")
        # Hosted installations can automatically grant new objects to API roles.
        for schema in ("public", "speechclear_private"):
            db.sql(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT ALL ON TABLES TO anon,authenticated,service_role; ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT EXECUTE ON FUNCTIONS TO anon,authenticated,service_role;"
            )
        db.sql("BEGIN;" + paths[-1].read_text() + "COMMIT;")
        for role in ("anon", "authenticated", "service_role"):
            assert (
                db.scalar(
                    f"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','speechclear_private') AND c.relname LIKE 'guided_%' AND c.relkind='r' AND has_table_privilege('{role}',c.oid,'INSERT,UPDATE,DELETE');"
                )
                == "0"
            )
            assert (
                db.scalar(
                    f"SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='speechclear_private' AND p.proname LIKE 'guided_%' AND has_function_privilege('{role}',p.oid,'EXECUTE');"
                )
                == "0"
            )
            assert (
                db.scalar(
                    f"SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='speechclear_private' AND c.relname LIKE 'guided_%' AND c.relkind='r' AND has_table_privilege('{role}',c.oid,'SELECT');"
                )
                == "0"
            )
        db.sql(f"INSERT INTO auth.users VALUES ('{A}');")
        assert reserve(db)["id"] == S
        assert (
            db.scalar(
                f"SET ROLE authenticated; SET request.jwt.claim.sub='{A}'; SELECT count(*) FROM guided_sessions;"
            )
            == "1"
        )
