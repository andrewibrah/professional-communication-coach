"""Disposable, Unix-socket-only PostgreSQL verifier; never uses runtime credentials."""

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Database:
    def __init__(self, socket, env):
        self.env = env | {
            "PGHOST": str(socket),
            "PGPORT": "55439",
            "PGUSER": "postgres",
            "PGDATABASE": "postgres",
        }

    def sql(self, text, check=True):
        result = subprocess.run(
            ["psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1"],
            input=text,
            text=True,
            capture_output=True,
            env=self.env,
            timeout=30,
            check=False,
        )
        if check and result.returncode:
            raise AssertionError(result.stderr)
        return result

    def scalar(self, text):
        return self.sql(text).stdout.strip()

    def rpc(self, action, owner, payload=None, role="service_role"):
        body = json.dumps(payload or {}).replace("'", "''")
        identifier = "NULL" if owner is None else "'" + owner + "'"
        return self.sql(
            f"SET ROLE {role}; SELECT public.speechclear_api('{action}',{identifier},'{body}'::jsonb);"
        )


@contextmanager
def disposable_database(migrate=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    # Homebrew libpq supplies initdb but no server; prefer installed server bins.
    for candidate in sorted(
        Path("/opt/homebrew/opt").glob("postgresql@*/bin"), reverse=True
    ):
        if (candidate / "postgres").exists():
            env["PATH"] = str(candidate) + os.pathsep + env.get("PATH", "")
            break
    scratch = Path.home() / ".hermes/profiles/telegramlite/cache/scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="sc-pg-", dir=scratch))
    base.chmod(0o700)
    data, socket = base / "data", base / "socket"
    socket.mkdir(mode=0o700)
    env.update(
        PGPASSFILE=str(base / "no-password"),
        PGSERVICEFILE=str(base / "no-service"),
        PGSYSCONFDIR=str(base),
        TMPDIR=str(scratch),
    )
    started = False
    try:
        subprocess.run(
            [
                "initdb",
                "-D",
                str(data),
                "-U",
                "postgres",
                "-A",
                "trust",
                "--no-locale",
                "-E",
                "UTF8",
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "pg_ctl",
                "-D",
                str(data),
                "-l",
                str(base / "postgres.log"),
                "-o",
                f"-c listen_addresses='' -c unix_socket_directories='{socket}' -p 55439",
                "-w",
                "start",
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        started = True
        db = Database(socket, env)
        assert db.scalar("SHOW listen_addresses;") == ""
        db.sql("""CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; CREATE ROLE service_role NOLOGIN BYPASSRLS;
        CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
        CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
        GRANT USAGE ON SCHEMA auth TO anon,authenticated,service_role;
        CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
        CREATE TABLE storage.objects(id uuid PRIMARY KEY,bucket_id text,name text); ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
        GRANT USAGE ON SCHEMA storage TO anon,authenticated,service_role;
        GRANT SELECT,INSERT,UPDATE,DELETE ON storage.objects TO anon,authenticated,service_role;
        """)
        if migrate:
            for migration in sorted((ROOT / "supabase/migrations").glob("*.sql")):
                db.sql("BEGIN;\n" + migration.read_text() + "\nCOMMIT;")
        yield db
    finally:
        if started or (data / "postmaster.pid").exists():
            subprocess.run(
                ["pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop"],
                env=env,
                check=True,
                capture_output=True,
            )
        shutil.rmtree(base)
        assert not base.exists()


if __name__ == "__main__":
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    raise SystemExit(
        subprocess.call(
            [
                "uv",
                "run",
                "--frozen",
                "pytest",
                "tests/test_postgres_schema.py",
                "tests/test_guided_postgres.py",
                "tests/test_guided_watchdog.py",
                "tests/test_guided_durable_budgets.py",
                "-q",
            ],
            cwd=ROOT / "backend",
            env=clean_env,
        )
    )
