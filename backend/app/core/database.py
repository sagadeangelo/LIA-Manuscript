from contextlib import contextmanager
from contextvars import ContextVar
import sqlite3
from pathlib import Path
from .config import settings


workspace_dir: ContextVar[Path | None] = ContextVar("workspace_dir", default=None)


@contextmanager
def connect():
    directory = workspace_dir.get() or settings.data_dir
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / "lia_manuscript.sqlite3")
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS manuscripts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        )""")