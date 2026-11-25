"""PDF interior for text-led editions. Measurements are in millimetres."""

import json
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
from ..api.routes.manuscripts import get_manuscript
from ..core.database import connect
from ..services.translation.chapter_pipeline import chapter_slices

router = APIRouter(prefix="/api/projects/{project_id}/manuscripts/{manuscript_id}")
sizes = {"6x9": (152.4, 228.6), "a5": (148, 210), "5x8": (127, 203.2)}


class Edition(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(default="", max_length=150)
    trim: Literal["6x9", "a5", "5x8"] = "6x9"
    margin: int = Field(default=20, ge=12, le=35)
    font: Literal["serif", "sans"] = "serif"
    legal: str = Field(default="", max_length=4000)
    dedication: str = Field(default="", max_length=4000)


def table(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS layouts(id TEXT PRIMARY KEY, manuscript TEXT, settings TEXT, created TEXT)"
    )


@router.post("/layouts", status_code=201)
def save(project_id: str, manuscript_id: str, payload: Edition):
    get_manuscript(project_id, manuscript_id)
    identity = str(uuid4())
    with connect() as db:
        table(db)
        db.execute(
            "INSERT INTO layouts VALUES(?,?,?,?)",
            (
                identity,
                manuscript_id,
                payload.model_dump_json(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return {"id": identity}


@router.get("/layouts")
def layouts(project_id: str, manuscript_id: str):
    get_manuscript(project_id, manuscript_id)
    with connect() as db:
        table(db)
        rows = db.execute(
            "SELECT * FROM layouts WHERE manuscript=? ORDER BY created DESC",
            (manuscript_id,),
        ).fetchall()
    return [
        {"id": r["id"], "created": r["created"], **json.loads(r["settings"])}
        for r in rows
    ]


@router.get("/layouts/{layout_id}/interior.pdf")
def interior(project_id: str, manuscript_id: str, layout_id: str):
    book = get_manuscript(project_id, manuscript_id)
    with connect() as db:
        table(db)
        row = db.execute(
            "SELECT settings FROM layouts WHERE id=? AND manuscript=?",
            (layout_id, manuscript_id),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Edición desconocida")
    edition = Edition.model_validate_json(row[0])
    width, height = [n * mm for n in sizes[edition.trim]]
    margin = edition.margin * mm
    family = "DejaVuSerif" if edition.font == "serif" else "DejaVuSans"
    fontpath = Path("/usr/share/fonts/truetype/dejavu") / (family + ".ttf")
    if not fontpath.is_file():
        raise HTTPException(
            503, "Instala las fuentes DejaVu en el servicio de impresión"
        )
    pdfmetrics.registerFont(TTFont(family, str(fontpath)))
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=(width, height),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=edition.title,
        author=edition.author,
    )
    body = ParagraphStyle(
        "body", fontName=family, fontSize=10.5, leading=15, spaceAfter=6
    )
    heading = ParagraphStyle(
        "heading", parent=body, fontSize=17, leading=22, spaceAfter=16
    )
    parts = [Spacer(1, 20 * mm), Paragraph(escape(edition.title), heading)]
    if edition.author:
        parts.append(Paragraph(escape(edition.author), body))
    for front in (edition.legal, edition.dedication):
        if front:
            parts.extend(
                [PageBreak(), Paragraph(escape(front).replace("\n", "<br/>"), body)]
            )
    chapters = chapter_slices(book["text"])
    if len(chapters) > 1:
        parts.extend([PageBreak(), Paragraph("Índice", heading)])
        parts.extend(Paragraph(escape(c["title"]), body) for c in chapters)
    for c in chapters:
        parts.extend([PageBreak(), Paragraph(escape(c["title"]), heading)])
        lines = c["text"].splitlines()
        if lines and lines[0].strip() == c["title"]:
            lines = lines[1:]
        parts.extend(
            Paragraph(escape(v), body) if v.strip() else Spacer(1, 6) for v in lines
        )

    def footer(canvas, document):
        canvas.setFont(family, 8)
        canvas.drawCentredString(width / 2, margin / 2, str(document.page))

    doc.build(parts, onLaterPages=footer)
    return Response(
        stream.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="interior.pdf"'},
    )
