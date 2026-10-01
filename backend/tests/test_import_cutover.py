"""Synthetic rows in disposable PostgreSQL; never connects to deployed Supabase."""

import json
import sqlite3
from types import SimpleNamespace

import httpx
import pytest

import migration
from store import Store as SQLiteStore
from test_postgres_schema import A, B, S, K, I, attempt, session, pg


class LocalStore:
    _project_url = "https://qpheitaamyzcekzvbcox.supabase.co"

    def __init__(self, db):
        self.db = db
        self.calls = []

    def rpc(self, action, owner, payload):
        self.calls.append((action, owner, payload))
        return json.loads(self.db.rpc(action, owner, payload).stdout)


def prepared(tmp_path):
    source = tmp_path / "synthetic.sqlite3"
    store = SQLiteStore(source)
    with store.connect() as db:
        db.execute("INSERT INTO profiles VALUES (?,?)", ("legacy", "{}"))
        db.execute(
            "INSERT INTO sessions VALUES (?,?,?)", (S, "legacy", json.dumps(session(S)))
        )
        db.execute(
            "INSERT INTO attempts VALUES (?,?,?,?)",
            (I, "legacy", S, json.dumps(attempt())),
        )
        db.execute(
            "INSERT INTO operations VALUES (?,?,?,?,?)", ("legacy", K, S, "complete", I)
        )
        db.execute(
            "INSERT INTO usage VALUES (?,?,?)",
            (1, "legacy", "2026-09-30T12:00:00+00:00"),
        )
        db.execute("INSERT INTO controls VALUES (?,?)", ("legacy", 0))
        db.execute(
            "INSERT INTO audit VALUES (?,?,?,?)",
            (1, "legacy", "session_created", "2026-09-30T12:00:00+00:00"),
        )
    migration.backup_export(source, tmp_path / "protected", {"legacy": A})
    return tmp_path / "protected/export.json"


def privileged_client(db):
    # Only the HTTP boundary is bridged; every REST read accesses real PostgreSQL.
    def handler(request):
        if request.url.path.startswith("/auth/v1/admin/users/"):
            owner = request.url.path.rsplit("/", 1)[1]
            found = (
                db.scalar(f"SELECT count(*) FROM auth.users WHERE id='{owner}'") == "1"
            )
            return httpx.Response(
                200 if found else 404,
                json={"id": owner, "email_confirmed_at": "2026-09-30T12:00:00Z"}
                if found
                else {},
            )
        table = request.url.path.rsplit("/", 1)[1]
        columns = request.url.params["select"]
        owner = request.url.params["user_id"][3:]
        conditions = [f"user_id='{owner}'"]
        for key, value in request.url.params.multi_items():
            if key in ("select", "user_id", "limit", "offset"):
                continue
            assert value.startswith("eq.")
            conditions.append(f"{key}='{value[3:]}'")
        query = f"SELECT coalesce(json_agg(r),'[]'::json) FROM (SELECT {columns} FROM public.{table} WHERE {' AND '.join(conditions)}) r"
        return httpx.Response(200, json=json.loads(db.scalar(query)))

    return httpx.Client(
        base_url=LocalStore._project_url, transport=httpx.MockTransport(handler)
    )


def test_atomic_import_exact_readback_receipt(tmp_path):
    path = prepared(tmp_path)
    with pg.disposable_database() as db:
        db.sql(f"INSERT INTO auth.users VALUES ('{A}')")
        store = LocalStore(db)
        store._client = privileged_client(db)
        verify, readback = migration.secure_callbacks(store)
        receipt = migration.import_export(
            path, store, verify_owner=verify, readback=readback
        )
        assert receipt["target"] == migration.PROJECT_URL
        assert receipt["cutover_ready"] is True
        assert receipt["counts_readback_verified"] is True
        assert receipt["source_counts"] == dict.fromkeys(migration.TABLES, 1)
        assert len(store.calls) == 2 and store.calls[0] == store.calls[1]
        assert db.scalar("SELECT count(*) FROM practice_sessions") == "1"
        assert A not in json.dumps(receipt) and "legacy" not in json.dumps(receipt)
        again = migration.import_export(
            path, store, verify_owner=verify, readback=readback
        )
        assert again["cutover_ready"] is True
        assert db.scalar("SELECT count(*) FROM attempts") == "1"
        migration.write_cutover_receipt(tmp_path / "receipt/verified.json", receipt)
        assert (tmp_path / "receipt/verified.json").stat().st_mode & 0o777 == 0o600
        from app import Settings, cutover_verified

        assert cutover_verified(
            Settings(
                _env_file=None,
                supabase_url=migration.PROJECT_URL,
                persistence_cutover_receipt=str(tmp_path / "receipt/verified.json"),
            )
        )


def test_cli_import_writes_receipt_after_verified_readback(
    tmp_path, monkeypatch, capsys
):
    import app
    import supabase_store

    path = prepared(tmp_path)
    with pg.disposable_database() as db:
        db.sql(f"INSERT INTO auth.users VALUES ('{A}')")
        store = LocalStore(db)
        store._client = privileged_client(db)
        monkeypatch.setattr(app, "Settings", lambda: SimpleNamespace())
        monkeypatch.setattr(supabase_store, "Store", lambda settings: store)
        target = tmp_path / "receipt/verified.json"
        assert (
            migration.main(["import-export", str(path), "--receipt", str(target)]) == 0
        )
        assert json.loads(target.read_text())["target"] == migration.PROJECT_URL
        assert "verified" in capsys.readouterr().out
        assert store._client.is_closed


def test_cli_existing_receipt_blocks_import_before_writes(
    tmp_path, monkeypatch, capsys
):
    import supabase_store

    marker = tmp_path / "existing.json"
    marker.write_text("keep")
    calls = []
    monkeypatch.setattr(
        supabase_store, "Store", lambda settings: calls.append(settings)
    )
    assert (
        migration.main(
            ["import-export", "unused/export.json", "--receipt", str(marker)]
        )
        == 1
    )
    assert not calls and marker.read_text() == "keep"
    assert "cutover blocked" in capsys.readouterr().err


class RecordingStore:
    _project_url = migration.PROJECT_URL

    def __init__(self):
        self.calls = []

    def rpc(self, action, owner, payload):
        self.calls.append((action, owner, payload))
        return {
            "counts": {t: len(payload[t]) for t in migration.TABLES},
            "fingerprint": payload["fingerprint"],
            "replayed": len(self.calls) % 2 == 0,
        }


def test_invalid_private_data_blocks_all_import_writes(tmp_path):
    prepared(tmp_path)
    source = tmp_path / "synthetic.sqlite3"
    with sqlite3.connect(source) as db:
        data = session(S) | {"goal": 42}
        db.execute("UPDATE sessions SET data=?", (json.dumps(data),))
    migration.backup_export(source, tmp_path / "invalid", {"legacy": A})
    store = RecordingStore()
    with pytest.raises(migration.MigrationError, match="cutover blocked"):
        migration.import_export(
            tmp_path / "invalid/export.json",
            store,
            lambda owner: True,
            lambda owner, rows: True,
        )
    assert not store.calls


@pytest.mark.parametrize("mutation", ["bytes", "permissions", "schema", "backup"])
def test_protected_export_tampering_blocks_writes(tmp_path, mutation):
    path = prepared(tmp_path)
    if mutation == "bytes":
        path.write_text(path.read_text() + " ")
    elif mutation == "permissions":
        path.chmod(0o644)
    elif mutation == "schema":
        manifest = path.parent / "manifest.json"
        value = json.loads(manifest.read_text()) | {"schema_sha256": "f" * 64}
        manifest.write_text(json.dumps(value))
    else:
        with (path.parent / "backup.sqlite3").open("ab") as output:
            output.write(b"tamper")
    store = RecordingStore()
    with pytest.raises(migration.MigrationError):
        migration.import_export(
            path, store, lambda owner: True, lambda owner, rows: True
        )
    assert not store.calls


def test_all_auth_owners_verified_before_first_write(tmp_path):
    prepared(tmp_path)
    source = tmp_path / "synthetic.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO profiles VALUES (?,?)", ("second", "{}"))
    migration.backup_export(source, tmp_path / "two", {"legacy": A, "second": B})
    store = RecordingStore()
    verified = []

    def verify(owner):
        verified.append(owner)
        return owner != B

    with pytest.raises(migration.MigrationError):
        migration.import_export(
            tmp_path / "two/export.json", store, verify, lambda *args: True
        )
    assert verified == [A, B] and not store.calls


def test_partial_multiowner_import_never_produces_cutover_receipt(tmp_path):
    prepared(tmp_path)
    source = tmp_path / "synthetic.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO profiles VALUES (?,?)", ("second", "{}"))
    migration.backup_export(source, tmp_path / "two", {"legacy": A, "second": B})
    store = RecordingStore()
    with pytest.raises(migration.MigrationError):
        migration.import_export(
            tmp_path / "two/export.json",
            store,
            lambda owner: True,
            lambda owner, rows: owner != B,
        )
    assert len(store.calls) == 4


@pytest.mark.parametrize("table", ["transcripts", "coaching_reports"])
def test_exact_readback_rejects_private_child_corruption_with_same_counts(
    tmp_path, table
):
    path = prepared(tmp_path)
    with pg.disposable_database() as db:
        db.sql(f"INSERT INTO auth.users VALUES ('{A}')")
        store = LocalStore(db)
        store._client = privileged_client(db)
        verify, readback = migration.secure_callbacks(store)

        def corrupt_then_verify(owner, payload):
            if table == "transcripts":
                db.sql(
                    f"UPDATE transcripts SET content='Different synthetic text' WHERE attempt_id='{I}'"
                )
            else:
                db.sql(
                    f"UPDATE coaching_reports SET data=jsonb_set(data,'{{priority_improvement}}','\"Different\"') WHERE attempt_id='{I}'"
                )
            return readback(owner, payload)

        with pytest.raises(migration.MigrationError, match="cutover blocked"):
            migration.import_export(path, store, verify, corrupt_then_verify)
        assert db.scalar("SELECT count(*) FROM attempts") == "1"
        assert not (tmp_path / "receipt/verified.json").exists()
        store._client.close()


def test_cli_insecure_receipt_directory_blocks_before_client(tmp_path, monkeypatch):
    import app
    import supabase_store

    monkeypatch.setattr(app, "Settings", lambda: SimpleNamespace())
    path = prepared(tmp_path)
    folder = tmp_path / "public"
    folder.mkdir(mode=0o755)
    calls = []
    monkeypatch.setattr(
        supabase_store, "Store", lambda settings: calls.append(settings)
    )
    assert (
        migration.main(
            ["import-export", str(path), "--receipt", str(folder / "verified.json")]
        )
        == 1
    )
    assert not calls


def test_receipt_writer_rejects_incomplete_proof(tmp_path):
    invalid = {
        "cutover_ready": True,
        "counts_readback_verified": True,
        "owner_mapping_verified": True,
        "project_ref": migration.PROJECT_REF,
    }
    with pytest.raises(migration.MigrationError):
        migration.write_cutover_receipt(tmp_path / "receipt/verified.json", invalid)
    assert not (tmp_path / "receipt/verified.json").exists()
