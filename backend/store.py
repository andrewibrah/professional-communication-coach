import sqlite3
from datetime import datetime, timezone
from fastapi import HTTPException
import json
from pathlib import Path
from contextlib import contextmanager
from models import Profile


class Store:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS profiles (user_id TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,data TEXT NOT NULL, UNIQUE(id,user_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY,user_id TEXT NOT NULL,session_id TEXT NOT NULL,data TEXT NOT NULL, FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS operations (user_id TEXT NOT NULL,key TEXT NOT NULL,session_id TEXT NOT NULL,state TEXT NOT NULL,attempt_id TEXT, PRIMARY KEY(user_id,key), FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,created_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS controls (user_id TEXT PRIMARY KEY,suspended INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,action TEXT NOT NULL,created_at TEXT NOT NULL)"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def suspend(self, owner, value):
        with self.connect() as db:
            db.execute(
                "INSERT INTO controls VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET suspended=excluded.suspended",
                (owner, int(value)),
            )
            db.execute(
                "INSERT INTO audit(user_id,action,created_at) VALUES (?,?,?)",
                (
                    owner,
                    "suspended" if value else "unsuspended",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def require_active(self, owner, db=None):
        if db is None:
            with self.connect() as conn:
                return self.require_active(owner, conn)
        row = db.execute(
            "SELECT suspended FROM controls WHERE user_id=?", (owner,)
        ).fetchone()
        if row and row["suspended"]:
            raise HTTPException(403, "Account suspended")

    def usage(self, owner, daily, monthly, db=None):
        if db is None:
            with self.connect() as conn:
                return self.usage(owner, daily, monthly, conn)
        today = datetime.now(timezone.utc).date().isoformat()
        rows = db.execute(
            "SELECT created_at FROM usage WHERE user_id=? AND created_at>=?",
            (owner, today[:7]),
        ).fetchall()
        return dict(
            daily_used=sum(r["created_at"][:10] == today for r in rows),
            daily_limit=daily,
            monthly_used=len(rows),
            monthly_limit=monthly,
        )

    def reserve(self, owner, daily, monthly):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_active(owner, db)
            used = self.usage(owner, daily, monthly, db)
            if used["daily_used"] >= daily or used["monthly_used"] >= monthly:
                raise HTTPException(429, "AI quota reached")
            db.execute(
                "INSERT INTO usage(user_id,created_at) VALUES (?,?)",
                (owner, datetime.now(timezone.utc).isoformat()),
            )

    def save_session(self, owner, data):
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?)",
                (data["id"], owner, json.dumps(data)),
            )
        return data

    def session(self, owner, id):
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM sessions WHERE user_id=? AND id=?", (owner, id)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")
        return json.loads(row["data"])

    def sessions(self, owner):
        with self.connect() as db:
            rows = db.execute(
                "SELECT data FROM sessions WHERE user_id=? ORDER BY rowid DESC",
                (owner,),
            ).fetchall()
        result = []
        for row in rows:
            session = json.loads(row["data"])
            attempts = self.attempts(owner, session["id"])
            result.append(
                session
                | dict(
                    attempt_count=len(attempts),
                    latest_score=attempts[-1]["report"]["overall_score"]
                    if attempts
                    else None,
                )
            )
        return result

    def attempts(self, owner, id):
        with self.connect() as db:
            return [
                json.loads(row["data"])
                for row in db.execute(
                    "SELECT data FROM attempts WHERE user_id=? AND session_id=? ORDER BY rowid",
                    (owner, id),
                )
            ]

    def begin_attempt(self, owner, session, key, daily, monthly):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_active(owner, db)
            if not db.execute(
                "SELECT 1 FROM sessions WHERE user_id=? AND id=?", (owner, session)
            ).fetchone():
                raise HTTPException(404, "Session not found")
            row = db.execute(
                "SELECT * FROM operations WHERE user_id=? AND key=?", (owner, key)
            ).fetchone()
            if row:
                if row["session_id"] != session or row["state"] != "complete":
                    raise HTTPException(
                        409,
                        "Request already processing or key unavailable; use a new key for a failed attempt",
                    )
                saved = db.execute(
                    "SELECT data FROM attempts WHERE user_id=? AND id=?",
                    (owner, row["attempt_id"]),
                ).fetchone()
                return json.loads(saved["data"])
            used = self.usage(owner, daily, monthly, db)
            if used["daily_used"] >= daily or used["monthly_used"] >= monthly:
                raise HTTPException(429, "AI quota reached")
            db.execute(
                "INSERT INTO operations VALUES (?,?,?,?,NULL)",
                (owner, key, session, "processing"),
            )
            db.execute(
                "INSERT INTO usage(user_id,created_at) VALUES (?,?)",
                (owner, datetime.now(timezone.utc).isoformat()),
            )
        return None

    def finish_attempt(self, owner, key, attempt):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM operations WHERE user_id=? AND key=? AND state=?",
                (owner, key, "processing"),
            ).fetchone():
                raise HTTPException(409, "Session was deleted during processing")
            db.execute(
                "INSERT INTO attempts VALUES (?,?,?,?)",
                (attempt["id"], owner, attempt["session_id"], json.dumps(attempt)),
            )
            db.execute(
                "UPDATE operations SET state=?,attempt_id=? WHERE user_id=? AND key=?",
                ("complete", attempt["id"], owner, key),
            )
        return attempt

    def fail_attempt(self, owner, key):
        with self.connect() as db:
            db.execute(
                "UPDATE operations SET state=? WHERE user_id=? AND key=? AND state=?",
                ("failed", owner, key, "processing"),
            )

    def delete(self, owner, id=None):
        with self.connect() as db:
            if id:
                result = db.execute(
                    "DELETE FROM sessions WHERE user_id=? AND id=?", (owner, id)
                )
                if not result.rowcount:
                    raise HTTPException(404, "Session not found")
            else:
                db.execute("DELETE FROM sessions WHERE user_id=?", (owner,))
            db.execute(
                "INSERT INTO audit(user_id,action,created_at) VALUES (?,?,?)",
                (
                    owner,
                    "session_deleted" if id else "history_deleted",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def profile(self, owner, data=None):
        with self.connect() as db:
            if data is not None:
                db.execute(
                    "INSERT INTO profiles VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data",
                    (owner, json.dumps(data)),
                )
            row = db.execute(
                "SELECT data FROM profiles WHERE user_id=?", (owner,)
            ).fetchone()
            return json.loads(row["data"]) if row else Profile().model_dump()
