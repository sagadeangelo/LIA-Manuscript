import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4
from ...core.database import connect
from .consistency_checker import paragraph_fidelity_warnings


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

        db.execute("""CREATE TABLE IF NOT EXISTS literary_segment_checkpoints (
            checkpoint_key TEXT NOT NULL, segment_index INTEGER NOT NULL,
            source_text TEXT NOT NULL, translated_text TEXT NOT NULL,
            warnings_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(checkpoint_key, segment_index))""")


def checkpoint_key(project_id, manuscript_id, chapter_index, source, model, glossary):
    # Bump revision when segmentation, prompts or validation rules change.
    identity = ["paragraph-review-v3-context", project_id, manuscript_id, chapter_index,
                source, model, glossary]
    if any(name in model.casefold() for name in ("hy-mt2", "hymt2")):
        identity.append("hymt-native-single-passage-v2")
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_segment_checkpoints(key):
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM literary_segment_checkpoints WHERE checkpoint_key=?", (key,),
        ).fetchall()
    results = {}
    for row in rows:
        try:
            warnings = json.loads(row["warnings_json"])
        except (ValueError, TypeError):
            continue
        translated = row["translated_text"]
        if (not translated.strip() or len(translated.strip().splitlines()) != 1
                or not isinstance(warnings, list)
                or any(not isinstance(warning, dict) for warning in warnings)):
            continue
        results[row["segment_index"]] = (row["source_text"], translated, warnings)
    return results


def save_segment_checkpoint(key, index, source, translation, warnings):
    with connect() as db:
        db.execute("""INSERT INTO literary_segment_checkpoints
            (checkpoint_key,segment_index,source_text,translated_text,warnings_json,created_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(checkpoint_key,segment_index) DO UPDATE SET
                source_text=excluded.source_text, translated_text=excluded.translated_text,
                warnings_json=excluded.warnings_json, created_at=excluded.created_at""",
            (key, index, source, translation, json.dumps(warnings, ensure_ascii=False), now()))


def clear_segment_checkpoints(key):
    with connect() as db:
        db.execute("DELETE FROM literary_segment_checkpoints WHERE checkpoint_key=?", (key,))


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
    # Re-evaluate on read so existing and manually revised versions get current checks.
    # Do not rewrite the stored translation or its historical metadata.
    current = paragraph_fidelity_warnings(item["source_text"], item["translated_text"])
    item["warnings"] = [
        warning for warning in item["warnings"]
        if warning.get("type") != "fidelity_review"
    ] + current
    return item

