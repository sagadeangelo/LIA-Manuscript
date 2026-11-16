import json
from datetime import datetime, timezone
from uuid import uuid4
from ...core.database import connect


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize_step4():
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS literary_glossary (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            source TEXT NOT NULL, target TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(project_id, source),
            FOREIGN KEY(project_id) REFERENCES projects(id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS literary_versions (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, manuscript_id TEXT NOT NULL,
            chapter_index INTEGER NOT NULL, chapter_title TEXT NOT NULL,
            source_text TEXT NOT NULL, translated_text TEXT NOT NULL,
            warnings_json TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id),
            FOREIGN KEY(manuscript_id) REFERENCES manuscripts(id))""")


def list_glossary(project_id):
    with connect() as db:
        return [dict(x) for x in db.execute(
            "SELECT id,source,target,note,created_at FROM literary_glossary WHERE project_id=? ORDER BY source",
            (project_id,)).fetchall()]


def add_term(project_id, source, target, note):
    item = {"id": str(uuid4()), "project_id": project_id, "source": source,
            "target": target, "note": note, "created_at": now()}
    with connect() as db:
        db.execute("""INSERT INTO literary_glossary
            (id,project_id,source,target,note,created_at)
            VALUES (:id,:project_id,:source,:target,:note,:created_at)""", item)
    return item


def add_version(project_id, manuscript_id, chapter_index, title, source, translation, warnings):
    item = {"id": str(uuid4()), "project_id": project_id, "manuscript_id": manuscript_id,
            "chapter_index": chapter_index, "chapter_title": title, "source_text": source,
            "translated_text": translation, "warnings_json": json.dumps(warnings, ensure_ascii=False),
            "status": "draft", "created_at": now()}
    with connect() as db:
        db.execute("""INSERT INTO literary_versions
            (id,project_id,manuscript_id,chapter_index,chapter_title,source_text,translated_text,
             warnings_json,status,created_at)
            VALUES (:id,:project_id,:manuscript_id,:chapter_index,:chapter_title,:source_text,
             :translated_text,:warnings_json,:status,:created_at)""", item)
    return {**item, "warnings": warnings, "warnings_json": None}


def list_versions(project_id, manuscript_id):
    with connect() as db:
        rows = db.execute("""SELECT id,chapter_index,chapter_title,status,created_at,
            length(translated_text) AS characters FROM literary_versions
            WHERE project_id=? AND manuscript_id=? ORDER BY created_at DESC, rowid DESC""",
            (project_id, manuscript_id)).fetchall()
    return [dict(x) for x in rows]


def get_version(project_id, manuscript_id, version_id):
    with connect() as db:
        row = db.execute("""SELECT * FROM literary_versions
            WHERE project_id=? AND manuscript_id=? AND id=?""",
            (project_id, manuscript_id, version_id)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["warnings"] = json.loads(item.pop("warnings_json"))
    return item
