"""Count staging operations without storing passages, filenames or provider responses."""

from contextlib import closing
from datetime import datetime, timezone
import sqlite3

from fastapi import HTTPException


def consume(path, account, tool):
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        today = datetime.now(timezone.utc).date().isoformat()
        db.execute("BEGIN IMMEDIATE")
        limit = db.execute(
            "SELECT allowance FROM daily_limits WHERE tool=?", (tool,)
        ).fetchone()[0]
        used = db.execute(
            "SELECT calls FROM daily_usage WHERE account=? AND day=? AND tool=?",
            (account, today, tool),
        ).fetchone()
        if used and used[0] >= limit or limit == 0:
            raise HTTPException(429, "Límite diario de esta herramienta alcanzado")
        db.execute(
            """INSERT INTO daily_usage VALUES(?,?,?,1) ON CONFLICT(account,day,tool)
                      DO UPDATE SET calls=calls+1""",
            (account, today, tool),
        )


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS daily_limits(tool TEXT PRIMARY KEY,allowance INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS daily_usage(account TEXT,day TEXT,tool TEXT,calls INTEGER,
                                                PRIMARY KEY(account,day,tool));
        INSERT OR IGNORE INTO daily_limits VALUES('staylo',500),('manuscript',30),('publish',50);
    """)
