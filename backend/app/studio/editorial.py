"""Web adapters for LanguageTool and portable book export in private staging."""

import json
import os
import subprocess
from datetime import datetime, timezone
from uuid import uuid4
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..api.routes.manuscripts import get_manuscript
from ..api.routes.literary_step4 import version_detail
from ..core.database import connect
from ..services.translation.chapter_pipeline import chapter_slices

router = APIRouter(prefix="/api/projects/{project_id}/manuscripts/{manuscript_id}")


class Passage(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class Term(BaseModel):
    word: str = Field(min_length=1, max_length=100)


class Correction(BaseModel):
    chapter: int = Field(ge=0)
    text: str = Field(max_length=2_000_000)


def words(db):
    db.execute("CREATE TABLE IF NOT EXISTS dictionary(word TEXT PRIMARY KEY)")


@router.post("/dictionary", status_code=201)
def add_word(project_id: str, manuscript_id: str, payload: Term):
    with connect() as db:
        if not db.execute(
            "SELECT 1 FROM manuscripts WHERE id=? AND project_id=?",
            (manuscript_id, project_id),
        ).fetchone():
            raise HTTPException(404, "Manuscrito desconocido")
        words(db)
        db.execute(
            "INSERT OR IGNORE INTO dictionary VALUES(?)",
            (payload.word.strip().casefold(),),
        )
    return {"ok": True}


@router.post("/review")
def review(project_id: str, manuscript_id: str, payload: Passage):
    with connect() as db:
        if not db.execute(
            "SELECT 1 FROM manuscripts WHERE id=? AND project_id=?",
            (manuscript_id, project_id),
        ).fetchone():
            raise HTTPException(404, "Manuscrito desconocido")
        words(db)
        dictionary = {r[0] for r in db.execute("SELECT word FROM dictionary")}
    url = os.getenv("STUDIO_LT_URL", "http://127.0.0.1:8131").rstrip("/") + "/v2/check"
    try:
        with urlopen(
            Request(
                url, data=urlencode({"language": "es", "text": payload.text}).encode()
            ),
            timeout=45,
        ) as res:
            matches = json.load(res)["matches"]
    except (URLError, TimeoutError, ValueError, KeyError):
        raise HTTPException(503, "LanguageTool no está disponible")
    encoded = payload.text.encode("utf-16-le")
    results = []
    for m in matches:
        start, size = m["offset"], m["length"]
        term = encoded[2 * start : 2 * (start + size)].decode("utf-16-le")
        category = m["rule"].get("category", {}).get("name", "Revisión")
        spelling = m["rule"].get("issueType") == "misspelling"
        if spelling and term.casefold() in dictionary:
            continue
        results.append(
            {
                "offset": start,
                "length": size,
                "term": term,
                "category": category,
                "message": m["message"],
                "spelling": spelling,
                "choices": [r["value"] for r in m["replacements"][:8]],
            }
        )
    return results


@router.post("/corrected", status_code=201)
def save_corrected(project_id: str, manuscript_id: str, payload: Correction):
    parent = get_manuscript(project_id, manuscript_id)
    parts = chapter_slices(parent["text"])
    if payload.chapter >= len(parts):
        raise HTTPException(422, "Capítulo desconocido")
    part = parts[payload.chapter]
    # The chapter splitter omits leading blank lines before a first heading.
    start = len(parent["text"]) - sum(len(p["text"]) for p in parts[payload.chapter :])
    updated = (
        parent["text"][:start]
        + payload.text
        + parent["text"][start + len(part["text"]) :]
    )
    if not updated.strip():
        raise HTTPException(422, "El manuscrito está vacío")
    child = str(uuid4())
    with connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS editorial_lineage(child TEXT PRIMARY KEY,parent TEXT,stage TEXT)"
        )
        db.execute(
            "INSERT INTO manuscripts(id,project_id,filename,text,created_at) VALUES(?,?,?,?,?)",
            (
                child,
                project_id,
                "Revisión · " + parent["filename"],
                updated,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.execute(
            "INSERT INTO editorial_lineage VALUES(?,?,?)",
            (child, manuscript_id, "corrected"),
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS edition_language(id TEXT PRIMARY KEY,lang TEXT)"
        )
        db.execute(
            "INSERT INTO edition_language SELECT ?,lang FROM edition_language WHERE id=?",
            (child, manuscript_id),
        )
    return {"id": child}


@router.get("/export/{fmt}")
def export(project_id: str, manuscript_id: str, fmt: str):
    if fmt not in {"epub", "docx"}:
        raise HTTPException(404)
    book = get_manuscript(project_id, manuscript_id)
    title = book["filename"].rsplit(".", 1)[0]
    with connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS edition_language(id TEXT PRIMARY KEY,lang TEXT)"
        )
        row = db.execute(
            "SELECT lang FROM edition_language WHERE id=?", (manuscript_id,)
        ).fetchone()
    language = row[0] if row else "es"
    # Use escaped HTML text nodes. Source markup and remote resource URLs remain text.
    from html import escape

    blocks = [
        "<!doctype html><html><head><title>" + escape(title) + "</title></head><body>"
    ]
    for chapter in chapter_slices(book["text"]):
        lines = chapter["text"].splitlines()
        if lines and lines[0].strip() == chapter["title"]:
            lines = lines[1:]
        blocks.append("<h1>" + escape(chapter["title"]) + "</h1>")
        blocks.extend("<p>" + escape(line) + "</p>" for line in lines)
    blocks.append("</body></html>")
    mime = (
        "application/epub+zip"
        if fmt == "epub"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    try:
        result = subprocess.run(
            ["pandoc", "-f", "html", "-t", fmt, "-M", "lang=" + language, "-o", "-"],
            input="\n".join(blocks).encode(),
            capture_output=True,
            timeout=90,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise HTTPException(503, "No se pudo generar el archivo editorial")
    return Response(
        result.stdout,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="manuscrito.{fmt}"'},
    )


@router.post("/versions/{version_id}/prepare", status_code=201)
def prepare_translation(project_id: str, manuscript_id: str, version_id: str):
    version = version_detail(project_id, manuscript_id, version_id)
    child = str(uuid4())
    with connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS editorial_lineage(child TEXT PRIMARY KEY,parent TEXT,stage TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS edition_language(id TEXT PRIMARY KEY,lang TEXT)"
        )
        db.execute(
            "INSERT INTO manuscripts(id,project_id,filename,text,created_at) VALUES(?,?,?,?,?)",
            (
                child,
                project_id,
                version["chapter_title"] + " · EN.txt",
                version["translated_text"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.execute(
            "INSERT INTO editorial_lineage VALUES(?,?,?)",
            (child, version_id, "translated"),
        )
        db.execute("INSERT INTO edition_language VALUES(?,?)", (child, "en-US"))
    return {"id": child}
