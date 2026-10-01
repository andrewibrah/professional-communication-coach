"""Protected backup/export and explicit, verified service-only import tooling."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

COLUMNS = {
    "profiles": ("user_id", "data"),
    "sessions": ("id", "user_id", "data"),
    "attempts": ("id", "user_id", "session_id", "data"),
    "operations": ("user_id", "key", "session_id", "state", "attempt_id"),
    "usage": ("id", "user_id", "created_at"),
    "controls": ("user_id", "suspended"),
    "audit": ("id", "user_id", "action", "created_at"),
}
TABLES = tuple(COLUMNS)


class MigrationError(RuntimeError):
    """Safe error without database rows, owners, credentials, or filesystem paths."""


def _hash(path):
    with Path(path).open("rb") as file:
        digest = hashlib.file_digest(file, "sha256")
    return digest.hexdigest()


def _private_file(path, content=b""):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def _json_bytes(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _require(condition):
    if not condition:
        raise MigrationError("Migration validation failed")


def _uuid(value):
    _require(isinstance(value, str) and str(UUID(value)) == value)


def _validate_snapshot(db, tables, owner_mapping):
    actual = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    _require(actual == set(TABLES))
    for table, columns in COLUMNS.items():
        _require(
            tuple(r[1] for r in db.execute(f'PRAGMA table_info("{table}")')) == columns
        )
    _require(not db.execute("PRAGMA foreign_key_check").fetchall())
    owners = {r["user_id"] for rows in tables.values() for r in rows}
    _require(all(isinstance(o, str) and bool(o) for o in owners))
    mapping = {o: o for o in owners} if owner_mapping is None else owner_mapping
    _require(isinstance(mapping, dict) and set(mapping) == owners)
    for target in mapping.values():
        _uuid(target)
    _require(len(set(mapping.values())) == len(mapping))
    sessions = {r["id"]: r for r in tables["sessions"]}
    attempts = {r["id"]: r for r in tables["attempts"]}
    for table in ("profiles", "sessions", "attempts"):
        for row in tables[table]:
            data = json.loads(row["data"])
            _require(isinstance(data, dict))
            for field in ("user_id", "owner"):
                _require(field not in data or data[field] == row["user_id"])
            if table != "profiles":
                _uuid(row["id"])
                _require(data.get("id") == row["id"])
            if table == "attempts":
                parent = sessions.get(row["session_id"])
                _require(parent is not None and parent["user_id"] == row["user_id"])
                _require(data.get("session_id") == row["session_id"])
    for row in tables["operations"]:
        _uuid(row["key"])
        parent = sessions.get(row["session_id"])
        _require(parent is not None and parent["user_id"] == row["user_id"])
        _require(row["state"] in ("processing", "complete", "failed"))
        if row["state"] == "complete":
            child = attempts.get(row["attempt_id"])
            _require(
                child is not None
                and child["session_id"] == row["session_id"]
                and child["user_id"] == row["user_id"]
            )
        else:
            _require(row["attempt_id"] is None)
    _require(
        all(
            type(r["suspended"]) is int and r["suspended"] in (0, 1)
            for r in tables["controls"]
        )
    )
    return owners, mapping


def backup_export(source, directory, owner_mapping=None):
    source = Path(source)
    directory = Path(directory)
    try:
        _require(source.is_file() and not source.is_symlink())
        _require(not any(parent.is_symlink() for parent in directory.parents))
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)
        backup_path = directory / "backup.sqlite3"
        _private_file(backup_path)
        with (
            closing(
                sqlite3.connect(source.absolute().as_uri() + "?mode=ro", uri=True)
            ) as original,
            closing(sqlite3.connect(backup_path)) as backup,
        ):
            original.execute("PRAGMA query_only=ON")
            original.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise MigrationError("Backup integrity check failed")
            backup.row_factory = sqlite3.Row
            tables = {
                t: [
                    dict(row)
                    for row in backup.execute(f'SELECT * FROM "{t}" ORDER BY rowid')
                ]
                for t in TABLES
            }
            owners, mapping = _validate_snapshot(backup, tables, owner_mapping)
            schema = [
                tuple(row)
                for row in backup.execute(
                    "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
                )
            ]
        payload = {"format_version": 1, "tables": tables, "owner_mapping": mapping}
        export_path = directory / "export.json"
        _private_file(export_path, _json_bytes(payload))
        manifest = {
            "format_version": 1,
            "counts": {t: len(rows) for t, rows in tables.items()},
            "owner_count": len(owners),
            "backup_sha256": _hash(backup_path),
            "export_sha256": _hash(export_path),
            "schema_sha256": hashlib.sha256(_json_bytes(schema)).hexdigest(),
            "integrity": "ok",
            "cutover_ready": False,
        }
        _private_file(directory / "manifest.json", _json_bytes(manifest))
        return manifest
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        raise MigrationError("Protected backup/export failed") from None


PROJECT_URL = "https://qpheitaamyzcekzvbcox.supabase.co"
PROJECT_REF = "qpheitaamyzcekzvbcox"


def _protected(path, directory=False):
    path = Path(path)
    _require(not path.is_symlink() and not any(p.is_symlink() for p in path.parents))
    _require(path.is_dir() if directory else path.is_file())
    _require(path.stat().st_mode & 0o777 == (0o700 if directory else 0o600))
    _require(path.stat().st_uid == os.getuid())


def _load_export(export_path):
    path = Path(export_path)
    _require(path.name == "export.json")
    _protected(path.parent, True)
    for name in ("export.json", "manifest.json", "backup.sqlite3"):
        _protected(path.parent / name)
    manifest = json.loads((path.parent / "manifest.json").read_text())
    payload = json.loads(path.read_text())
    _require(manifest["format_version"] == payload["format_version"] == 1)
    _require(set(payload) == {"format_version", "tables", "owner_mapping"})
    _require(set(payload["tables"]) == set(TABLES))
    _require(manifest["integrity"] == "ok" and manifest["cutover_ready"] is False)
    _require(_hash(path) == manifest["export_sha256"])
    backup_path = path.parent / "backup.sqlite3"
    _require(_hash(backup_path) == manifest["backup_sha256"])
    with closing(
        sqlite3.connect(backup_path.absolute().as_uri() + "?mode=ro", uri=True)
    ) as db:
        db.execute("PRAGMA query_only=ON")
        _require(db.execute("PRAGMA integrity_check").fetchall() == [("ok",)])
        db.row_factory = sqlite3.Row
        tables = {
            t: [dict(r) for r in db.execute(f'SELECT * FROM "{t}" ORDER BY rowid')]
            for t in TABLES
        }
        owners, mapping = _validate_snapshot(db, tables, payload["owner_mapping"])
        schema = [
            tuple(r)
            for r in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
            )
        ]
    _require(tables == payload["tables"])
    _require(
        hashlib.sha256(_json_bytes(schema)).hexdigest() == manifest["schema_sha256"]
    )
    _require(manifest["owner_count"] == len(owners))
    _require(manifest["counts"] == {t: len(rows) for t, rows in tables.items()})
    _require(all(type(n) is int for n in manifest["counts"].values()))
    return manifest, tables, mapping


def _validate_import_data(tables):
    """Validate all owners' domain rows before the first privileged write."""
    from models import Profile
    from supabase_store import SessionRecord, AttemptRecord

    for table, model in (
        ("profiles", Profile),
        ("sessions", SessionRecord),
        ("attempts", AttemptRecord),
    ):
        for row in tables[table]:
            model.model_validate(json.loads(row["data"]), strict=True)
    actions = {
        "session_created",
        "session_deleted",
        "history_deleted",
        "suspended",
        "unsuspended",
        "upload_created",
        "legacy_imported",
    }
    for table in ("usage", "audit"):
        for row in tables[table]:
            _require(type(row["id"]) is int and 1 <= row["id"] <= 2147483647)
            _timestamp(row["created_at"])
            if table == "audit":
                _require(row["action"] in actions)


def _check_rpc_receipt(receipt, expected, fingerprint, replay=False):
    _require(
        isinstance(receipt, dict)
        and set(receipt) == {"counts", "fingerprint", "replayed"}
    )
    _require(receipt["counts"] == expected and receipt["fingerprint"] == fingerprint)
    _require(all(type(n) is int for n in receipt["counts"].values()))
    _require(type(receipt["replayed"]) is bool)
    _require(not replay or receipt["replayed"] is True)


def import_export(export_path, store, verify_owner=None, readback=None):
    """Import per owner atomically; authorize cutover only after exact private readback."""
    if not callable(verify_owner) or not callable(readback):
        raise MigrationError("Remote import is not implemented; cutover blocked")
    try:
        from datetime import datetime, timezone

        project = getattr(store, "_project_url", None)
        if project is None:
            project = str(store._client.base_url)
            # httpx represents a bare origin with a trailing slash.
            _require(project in (PROJECT_URL, PROJECT_URL + "/"))
        else:
            _require(project == PROJECT_URL)
        manifest, tables, mapping = _load_export(export_path)
        _validate_import_data(tables)
        for owner in sorted(mapping.values()):
            _require(verify_owner(owner) is True)
        # Revalidate protected bytes after external identity callbacks, before writes.
        _require(_load_export(export_path) == (manifest, tables, mapping))
        for source, owner in sorted(mapping.items()):
            payload = {
                t: [dict(r, user_id=owner) for r in rows if r["user_id"] == source]
                for t, rows in tables.items()
            }
            fingerprint = hashlib.sha256(
                _json_bytes([manifest["export_sha256"], owner])
            ).hexdigest()
            payload["fingerprint"] = fingerprint
            counts = {t: len(payload[t]) for t in TABLES}
            first = store.rpc("import_legacy", owner, payload)
            _check_rpc_receipt(first, counts, fingerprint)
            second = store.rpc("import_legacy", owner, payload)
            _check_rpc_receipt(second, counts, fingerprint, replay=True)
            _require(readback(owner, payload) is True)
        return {
            "target": PROJECT_URL,
            "project_ref": PROJECT_REF,
            "export_sha256": manifest["export_sha256"],
            "backup_sha256": manifest["backup_sha256"],
            "source_counts": manifest["counts"],
            "owner_mapping_verified": True,
            "counts_readback_verified": True,
            "cutover_ready": True,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        raise MigrationError("Migration validation failed; cutover blocked") from None


def _timestamp(value):
    from datetime import datetime

    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(date.tzinfo is not None)
    return date


def _normalize_row(table, row):
    row = dict(row)
    if "data" in row and isinstance(row["data"], str):
        row["data"] = json.loads(row["data"])
    if table == "controls":
        _require(
            type(row["suspended"]) is bool
            or (type(row["suspended"]) is int and row["suspended"] in (0, 1))
        )
        row["suspended"] = bool(row["suspended"])
    if "created_at" in row:
        row["created_at"] = _timestamp(row["created_at"])
    return row


def secure_callbacks(store):
    """Privileged Auth verification and narrowly source-ID-filtered REST reads."""
    client = store._client
    _require(str(client.base_url) in (PROJECT_URL, PROJECT_URL + "/"))

    def get(path, params=None):
        response = client.get(path, params=params)
        _require(response.status_code == 200)
        return response.json()

    def verify_owner(owner):
        _uuid(owner)
        result = get("/auth/v1/admin/users/" + owner)
        _require(isinstance(result, dict) and result.get("id") == owner)
        confirmed = result.get("email_confirmed_at") or result.get("phone_confirmed_at")
        _timestamp(confirmed)
        _require(not result.get("deleted_at"))
        return True

    def readback(owner, payload):
        _uuid(owner)
        names = {
            "sessions": "practice_sessions",
            "usage": "usage_records",
            "audit": "audit_events",
        }
        for table in TABLES:
            columns = COLUMNS[table]
            for expected in payload[table]:
                _require(expected["user_id"] == owner)
                params = {"user_id": "eq." + owner, "select": ",".join(columns)}
                if table not in ("profiles", "controls"):
                    key = "key" if table == "operations" else "id"
                    params[key] = "eq." + str(expected[key])
                actual = get("/rest/v1/" + names.get(table, table), params)
                _require(isinstance(actual, list) and len(actual) == 1)
                _require(
                    _normalize_row(table, actual[0]) == _normalize_row(table, expected)
                )
                if table in ("sessions", "attempts"):
                    timestamp = get(
                        "/rest/v1/" + names.get(table, table),
                        params | {"select": "created_at"},
                    )
                    data = expected["data"]
                    data = json.loads(data) if isinstance(data, str) else data
                    _require(
                        len(timestamp) == 1
                        and _timestamp(timestamp[0]["created_at"])
                        == _timestamp(data["created_at"])
                    )
                if table == "attempts":
                    data = expected["data"]
                    data = json.loads(data) if isinstance(data, str) else data
                    child_params = {
                        "user_id": "eq." + owner,
                        "attempt_id": "eq." + expected["id"],
                    }
                    transcripts = get(
                        "/rest/v1/transcripts",
                        child_params | {"select": "attempt_id,user_id,content"},
                    )
                    reports = get(
                        "/rest/v1/coaching_reports",
                        child_params | {"select": "attempt_id,user_id,data"},
                    )
                    _require(
                        transcripts
                        == [
                            {
                                "attempt_id": expected["id"],
                                "user_id": owner,
                                "content": data["transcript"],
                            }
                        ]
                    )
                    _require(
                        reports
                        == [
                            {
                                "attempt_id": expected["id"],
                                "user_id": owner,
                                "data": data["report"],
                            }
                        ]
                    )
        return True

    return verify_owner, readback


def write_cutover_receipt(path, receipt):
    """Exclusive private creation; never replaces an existing cutover marker."""
    path = Path(path)
    _require(
        receipt.get("cutover_ready") is True
        and receipt.get("counts_readback_verified") is True
        and receipt.get("owner_mapping_verified") is True
    )
    _require(
        receipt.get("project_ref") == PROJECT_REF
        and receipt.get("target") == PROJECT_URL
    )
    import re
    from datetime import datetime, timezone

    for key in ("backup_sha256", "export_sha256"):
        _require(
            isinstance(receipt.get(key), str)
            and re.fullmatch(r"[0-9a-f]{64}", receipt[key]) is not None
        )
    _require(_timestamp(receipt["verified_at"]) <= datetime.now(timezone.utc))
    counts = receipt.get("source_counts")
    _require(isinstance(counts, dict) and set(counts) == set(TABLES))
    _require(all(type(n) is int and n >= 0 for n in counts.values()))
    _require(not any(p.is_symlink() for p in (path.parent, *path.parents)))
    if not path.parent.exists():
        path.parent.mkdir(mode=0o700)
    _protected(path.parent, True)
    _private_file(path, _json_bytes(receipt))


def compare_receipt(manifest, receipt):
    """Compare metadata only. Caller must independently authenticate/read back receipt.

    This is not a cutover authorization and does not validate Supabase auth users.
    """
    try:
        _require(isinstance(manifest, dict) and isinstance(receipt, dict))
        _require(receipt.get("project_ref") == "qpheitaamyzcekzvbcox")
        _require(receipt.get("export_sha256") == manifest["export_sha256"])
        _require(receipt.get("source_counts") == manifest["counts"])
        _require(receipt.get("owner_mapping_verified") is True)
        _require(set(manifest["counts"]) == set(TABLES))
        _require(all(type(v) is int and v >= 0 for v in manifest["counts"].values()))
        _require(
            all(type(v) is int and v >= 0 for v in receipt["source_counts"].values())
        )
        return True
    except (KeyError, TypeError, ValueError):
        raise MigrationError("Migration receipt mismatch") from None


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Protected migration preparation and explicitly invoked verified import"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup-export")
    backup.add_argument("source")
    backup.add_argument("directory")
    backup.add_argument(
        "--owner-map", help="Private JSON mapping file, never an inline owner list"
    )
    importer = sub.add_parser("import-export")
    importer.add_argument("export_path")
    importer.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    store = None
    try:
        if args.command == "import-export":
            from app import Settings
            from supabase_store import Store

            target = Path(args.receipt)
            _require(not target.exists() and not target.is_symlink())
            _require(not any(p.is_symlink() for p in target.parents))
            if target.parent.exists():
                _protected(target.parent, True)
            else:
                _require(target.parent.parent.is_dir())
            _load_export(args.export_path)  # Fail before constructing a network client.
            store = Store(Settings())
            verify_owner, readback = secure_callbacks(store)
            result = import_export(args.export_path, store, verify_owner, readback)
            write_cutover_receipt(target, result)
            _protected(target)
            _require(json.loads(target.read_text()) == result)
            print("Import and cutover receipt verified.")
            return 0
        mapping = None
        if args.owner_map:
            path = Path(args.owner_map)
            _require(
                path.is_file()
                and not path.is_symlink()
                and path.stat().st_mode & 0o077 == 0
            )
            mapping = json.loads(path.read_text())
        result = backup_export(args.source, args.directory, mapping)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print("Migration validation failed; cutover blocked", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            close = getattr(store, "close", None) or store._client.close
            close()


if __name__ == "__main__":
    raise SystemExit(main())
