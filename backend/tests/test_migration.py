import hashlib
import importlib
import json
import sqlite3
import stat

import pytest

from store import Store as SQLiteStore

OWNER = "11111111-1111-4111-8111-111111111111"
SID = "22222222-2222-4222-8222-222222222222"
AID = "33333333-3333-4333-8333-333333333333"
TABLES = (
    "profiles",
    "sessions",
    "attempts",
    "operations",
    "usage",
    "controls",
    "audit",
)


def migration():
    return importlib.import_module("migration")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.sqlite3"
    store = SQLiteStore(path)
    with store.connect() as db:
        db.execute(
            "INSERT INTO profiles VALUES (?,?)",
            (OWNER, json.dumps({"role": "Synthetic"})),
        )
        db.execute(
            "INSERT INTO sessions VALUES (?,?,?)",
            (SID, OWNER, json.dumps({"id": SID, "synthetic": "private fixture"})),
        )
        db.execute(
            "INSERT INTO attempts VALUES (?,?,?,?)",
            (AID, OWNER, SID, json.dumps({"id": AID, "session_id": SID})),
        )
        db.execute(
            "INSERT INTO operations VALUES (?,?,?,?,?)",
            (OWNER, AID, SID, "complete", AID),
        )
        db.execute(
            "INSERT INTO usage VALUES (?,?,?)", (1, OWNER, "2026-09-30T00:00:00+00:00")
        )
        db.execute("INSERT INTO controls VALUES (?,?)", (OWNER, 0))
        db.execute(
            "INSERT INTO audit VALUES (?,?,?,?)",
            (1, OWNER, "synthetic", "2026-09-30T00:00:00+00:00"),
        )
    return path


def test_backup_export_preserves_every_row_privately_without_source_write(
    source, tmp_path
):
    before = source.read_bytes()
    result = migration().backup_export(source, tmp_path / "private")
    assert source.read_bytes() == before
    assert result["counts"] == dict.fromkeys(TABLES, 1)
    assert result["owner_count"] == 1
    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o700
    for name in ("backup.sqlite3", "export.json", "manifest.json"):
        assert stat.S_IMODE((tmp_path / "private" / name).stat().st_mode) == 0o600
    exported = json.loads((tmp_path / "private/export.json").read_text())
    assert exported["owner_mapping"] == {OWNER: OWNER}
    with (
        sqlite3.connect(source) as original,
        sqlite3.connect(tmp_path / "private/backup.sqlite3") as backup,
    ):
        for table in TABLES:
            original.row_factory = sqlite3.Row
            assert exported["tables"][table] == [
                dict(row)
                for row in original.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
            ]
            assert backup.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 1
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert (
        result["backup_sha256"]
        == hashlib.sha256(
            (tmp_path / "private/backup.sqlite3").read_bytes()
        ).hexdigest()
    )
    assert "private fixture" not in json.dumps(result)
    assert OWNER not in json.dumps(result)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE attempts SET user_id='44444444-4444-4444-8444-444444444444'",
        "UPDATE operations SET user_id='44444444-4444-4444-8444-444444444444'",
        "UPDATE operations SET attempt_id='44444444-4444-4444-8444-444444444444'",
        "UPDATE operations SET state='invalid'",
        "UPDATE attempts SET session_id='44444444-4444-4444-8444-444444444444'",
        'UPDATE sessions SET data=\'{"id":"wrong"}\'',
        'UPDATE attempts SET data=\'{"id":"wrong"}\'',
        "CREATE TABLE unexpected (private TEXT)",
        "ALTER TABLE usage ADD COLUMN private TEXT",
        "UPDATE controls SET suspended=2",
    ],
)
def test_invalid_relationship_or_schema_blocks_export(source, tmp_path, mutation):
    with sqlite3.connect(source) as db:
        db.execute(mutation)
    before = source.read_bytes()
    with pytest.raises(migration().MigrationError):
        migration().backup_export(source, tmp_path / "private")
    assert source.read_bytes() == before
    assert not (tmp_path / "private/export.json").exists()


@pytest.mark.parametrize(
    "mapping", [{}, {OWNER: "bad"}, {OWNER: OWNER, "extra": OWNER}]
)
def test_incomplete_or_invalid_owner_mapping_blocks_export(source, tmp_path, mapping):
    with pytest.raises(migration().MigrationError):
        migration().backup_export(source, tmp_path / "private", mapping)
    assert not (tmp_path / "private/export.json").exists()


def test_legacy_owner_requires_explicit_canonical_mapping(source, tmp_path):
    with sqlite3.connect(source) as db:
        for table in TABLES:
            db.execute(f'UPDATE "{table}" SET user_id=?', ("legacy-owner",))
    before = source.read_bytes()
    with pytest.raises(migration().MigrationError):
        migration().backup_export(source, tmp_path / "blocked")
    result = migration().backup_export(
        source, tmp_path / "allowed", {"legacy-owner": OWNER}
    )
    assert result["counts"] == dict.fromkeys(TABLES, 1)
    assert source.read_bytes() == before


def test_owner_mapping_cannot_merge_distinct_owners(source, tmp_path):
    other = "44444444-4444-4444-8444-444444444444"
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO profiles VALUES (?,?)", (other, "{}"))
    with pytest.raises(migration().MigrationError):
        migration().backup_export(
            source, tmp_path / "private", {OWNER: OWNER, other: OWNER}
        )


def test_existing_directory_is_never_overwritten(source, tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    marker = directory / "keep"
    marker.write_text("synthetic")
    with pytest.raises(migration().MigrationError):
        migration().backup_export(source, directory)
    assert marker.read_text() == "synthetic"


def test_symlink_source_is_rejected(source, tmp_path):
    link = tmp_path / "link.sqlite3"
    link.symlink_to(source)
    with pytest.raises(migration().MigrationError):
        migration().backup_export(link, tmp_path / "private")


def test_readonly_source_includes_committed_wal_rows(source, tmp_path):
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "INSERT INTO usage VALUES (?,?,?)", (2, OWNER, "2026-09-30T01:00:00+00:00")
        )
        db.commit()
        before = source.read_bytes()
        result = migration().backup_export(source, tmp_path / "private")
        assert result["counts"]["usage"] == 2
        assert source.read_bytes() == before


def test_import_is_blocked_without_remote_support(source, tmp_path):
    migration().backup_export(source, tmp_path / "private")

    class NoRemote:
        def rpc(self, *args):
            pytest.fail("No remote writes authorized")

    with pytest.raises(
        migration().MigrationError,
        match="Remote import is not implemented; cutover blocked",
    ):
        migration().import_export(tmp_path / "private/export.json", NoRemote())


def test_receipt_comparison_requires_exact_hash_counts_project_and_verified_owners(
    source, tmp_path
):
    manifest = migration().backup_export(source, tmp_path / "private")
    receipt = {
        "project_ref": "qpheitaamyzcekzvbcox",
        "export_sha256": manifest["export_sha256"],
        "source_counts": manifest["counts"],
        "owner_mapping_verified": True,
    }
    assert migration().compare_receipt(manifest, receipt) is True
    for altered in (
        receipt | {"project_ref": "other"},
        receipt | {"export_sha256": "bad"},
        receipt | {"source_counts": {}},
        receipt | {"owner_mapping_verified": False},
        receipt | {"owner_mapping_verified": 1},
    ):
        with pytest.raises(migration().MigrationError):
            migration().compare_receipt(manifest, altered)


def test_cli_backup_prints_metadata_only(source, tmp_path, capsys):
    assert (
        migration().main(["backup-export", str(source), str(tmp_path / "private")]) == 0
    )
    output = capsys.readouterr().out
    assert json.loads(output)["cutover_ready"] is False
    assert OWNER not in output and "private fixture" not in output


def test_cli_error_is_safe(tmp_path, capsys):
    assert (
        migration().main(
            ["backup-export", str(tmp_path / "nonexistent"), str(tmp_path / "private")]
        )
        == 1
    )
    output = capsys.readouterr()
    assert str(tmp_path) not in output.err
    assert "Migration validation failed" in output.err


def test_backup_closes_both_sqlite_connections(source, tmp_path, monkeypatch):
    opened = []

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    real_connect = sqlite3.connect

    def tracked_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs, factory=TrackedConnection)
        opened.append(connection)
        return connection

    monkeypatch.setattr(migration().sqlite3, "connect", tracked_connect)
    migration().backup_export(source, tmp_path / "private")
    assert len(opened) == 2 and all(c.closed for c in opened)
