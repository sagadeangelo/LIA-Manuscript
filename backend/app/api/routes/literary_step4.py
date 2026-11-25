from contextvars import copy_context
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from fastapi import File, UploadFile
from fastapi.responses import Response
from lxml import etree

import os
import sqlite3
from threading import Condition, Thread
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ...core.database import connect
from ...services.translation.chapter_pipeline import chapter_slices, translate_chapter
from ...services.translation.literary_memory import build_context
from ...services.translation.step4_store import (
    initialize_step4, list_glossary, add_term, add_version, list_versions, get_version,
    checkpoint_key, clear_segment_checkpoints,
)
from ...services.providers.ollama_provider import OllamaError

router = APIRouter(prefix="/api/projects/{project_id}", tags=["literary-step4"])

_progress: dict[tuple[str, str, UUID], tuple[int, int]] = {}
_progress_lock = Condition()
_controls = {}
_jobs = {}


class TranslationStopped(Exception):
    pass


class TranslationControl(BaseModel):
    action: Literal["pause", "resume", "stop"]


@router.put("/manuscripts/{manuscript_id}/translation-progress/{job_id}/control")
def control_translation(project_id: str, manuscript_id: str, job_id: UUID, payload: TranslationControl):
    key = (project_id, manuscript_id, job_id)
    with _progress_lock:
        if key not in _progress:
            raise HTTPException(status_code=404, detail="La traduccion ya no esta activa.")
        if _controls.get(key) != "stop":
            _controls[key] = payload.action
        _progress_lock.notify_all()
    return {"action": payload.action}


@router.get("/manuscripts/{manuscript_id}/translation-progress/{job_id}")
def translation_progress(project_id: str, manuscript_id: str, job_id: UUID):
    with _progress_lock:
        key = (project_id, manuscript_id, job_id)
        current = _progress.get(key, (0, 0))
        job = dict(_jobs.get(key, {}))
    return {"completed": current[0], "total": current[1], **job}


class GlossaryEntry(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=500)

class EditorialRevision(BaseModel):
    translated_text: str = Field(min_length=1)


class ChapterRequest(BaseModel):
    chapter_index: int = Field(ge=0)
    model: str | None = None
    job_id: UUID | None = None


@router.post("/manuscripts/{manuscript_id}/translation-jobs", status_code=202)
def start_translation_job(project_id: str, manuscript_id: str, payload: ChapterRequest):
    if payload.job_id is None:
        raise HTTPException(status_code=422, detail="Se requiere job_id")
    chunks = chapter_slices(manuscript_text(project_id, manuscript_id))
    if payload.chapter_index >= len(chunks) or not chunks[payload.chapter_index]["text"].strip():
        raise HTTPException(status_code=422, detail="Capitulo invalido o vacio")
    key = (project_id, manuscript_id, payload.job_id)
    with _progress_lock:
        if key in _jobs:
            raise HTTPException(status_code=409, detail="Trabajo ya registrado")
        if any(k[:2] == key[:2] and v["state"] == "running" for k, v in _jobs.items()):
            raise HTTPException(status_code=409, detail="Ya hay una traduccion activa para este manuscrito")
        terminal = [k for k, v in _jobs.items() if v["state"] != "running"]
        for old in terminal[:-63]:
            _jobs.pop(old, None)
        _jobs[key] = {"state": "running"}

    def run():
        try:
            result = translate_one_chapter(project_id, manuscript_id, payload)
            outcome = {"state": "completed", "result": result}
        except HTTPException as exc:
            outcome = {"state": "failed", "status_code": exc.status_code, "detail": exc.detail}
        except Exception:
            outcome = {"state": "failed", "status_code": 500,
                       "detail": "Error interno durante la traduccion. Revisa el servicio local."}
        with _progress_lock:
            _jobs[key] = outcome

    try:
        Thread(target=copy_context().run, args=(run,), daemon=True).start()
    except Exception:
        with _progress_lock:
            _jobs.pop(key, None)
        raise HTTPException(status_code=503, detail="No se pudo iniciar la traduccion")
    return {"job_id": str(payload.job_id), "state": "running"}


def manuscript_text(project_id: str, manuscript_id: str) -> str:
    with connect() as db:
        row = db.execute("SELECT text FROM manuscripts WHERE project_id=? AND id=?",
                         (project_id, manuscript_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Manuscrito no encontrado")
    return row["text"]


def require_project(project_id: str):
    with connect() as db:
        exists = db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

@router.get("/glossary")
def glossary(project_id: str):
    require_project(project_id)
    initialize_step4()
    return list_glossary(project_id)

@router.post("/glossary", status_code=201)
def create_term(project_id: str, payload: GlossaryEntry):
    require_project(project_id)
    initialize_step4()
    try:
        return add_term(project_id, payload.source.strip(), payload.target.strip(), payload.note)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Termino ya registrado") from exc

@router.get("/manuscripts/{manuscript_id}/chapters")
def chapters(project_id: str, manuscript_id: str):
    chunks = chapter_slices(manuscript_text(project_id, manuscript_id))
    return [{"index": i, "title": c["title"], "characters": len(c["text"])}
            for i, c in enumerate(chunks)]

@router.get("/manuscripts/{manuscript_id}/versions")
def versions(project_id: str, manuscript_id: str):
    manuscript_text(project_id, manuscript_id)
    initialize_step4()
    return list_versions(project_id, manuscript_id)

@router.get("/manuscripts/{manuscript_id}/versions/{version_id}")
def version_detail(project_id: str, manuscript_id: str, version_id: str):
    manuscript_text(project_id, manuscript_id)
    initialize_step4()
    result = get_version(project_id, manuscript_id, version_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Version no encontrada")
    return result


@router.post("/manuscripts/{manuscript_id}/versions/{version_id}/revisions", status_code=201)
def save_revision(project_id: str, manuscript_id: str, version_id: str, payload: EditorialRevision):
    base = version_detail(project_id, manuscript_id, version_id)
    if not payload.translated_text.strip():
        raise HTTPException(status_code=422, detail="La revision esta vacia")
    saved = add_version(
        project_id, manuscript_id, base["chapter_index"], base["chapter_title"],
        base["source_text"], payload.translated_text, [],
    )
    return {"id": saved["id"]}


@router.get("/manuscripts/{manuscript_id}/memory")
def memory(project_id: str, manuscript_id: str):
    manuscript_text(project_id, manuscript_id)
    initialize_step4()
    return build_context(list_glossary(project_id))

@router.post("/manuscripts/{manuscript_id}/translate-chapter", status_code=201)
def translate_one_chapter(project_id: str, manuscript_id: str, payload: ChapterRequest):
    text = manuscript_text(project_id, manuscript_id)
    chapters = chapter_slices(text)
    if payload.chapter_index >= len(chapters):
        raise HTTPException(status_code=422, detail="Indice de capitulo invalido")
    selected = chapters[payload.chapter_index]
    if not selected["text"].strip():
        raise HTTPException(status_code=422, detail="Capitulo vacio")
    initialize_step4()
    glossary_entries = list_glossary(project_id)
    terms = {entry["source"]: entry["target"] for entry in glossary_entries}
    model_name = payload.model or os.getenv("LIA_OLLAMA_MODEL", "llama3.1:8b")
    checkpoint = checkpoint_key(project_id, manuscript_id, payload.chapter_index,
                                selected["text"], model_name, terms)
    key = (project_id, manuscript_id, payload.job_id) if payload.job_id else None
    if key is not None:
        with _progress_lock:
            if key in _progress:
                raise HTTPException(status_code=409, detail="Traduccion en curso")
            _progress[key] = (0, 0)

    def update_progress(completed: int, total: int):
        if key is not None:
            with _progress_lock:
                _progress[key] = (completed, total)
                ready = _progress_lock.wait_for(
                    lambda: _controls.get(key) != "pause", timeout=25 * 60,
                )
                if not ready or _controls.get(key) == "stop":
                    raise TranslationStopped()

    try:
        translated = translate_chapter(selected["text"], terms, model_name, update_progress,
                                       checkpoint=checkpoint)
    except TranslationStopped as exc:
        raise HTTPException(status_code=409, detail="Traduccion detenida. Los segmentos validados quedaron guardados; vuelve a traducir con el mismo modelo y glosario para continuar.") from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if key is not None:
            with _progress_lock:
                _progress.pop(key, None)
                _controls.pop(key, None)
    result = add_version(project_id, manuscript_id, payload.chapter_index,
                         selected["title"], selected["text"],
                         translated["translation"], translated["warnings"])
    clear_segment_checkpoints(checkpoint)
    return {"id": result["id"], "status": "draft", "segments": translated["segments"],
            "resumed_segments": translated.get("resumed_segments", 0),
            "warnings": translated["warnings"], "chapter_index": payload.chapter_index}


from .manuscripts import ensure_docx_storage


@router.put("/manuscripts/{manuscript_id}/docx-template")
def link_docx_template(project_id: str, manuscript_id: str, file: UploadFile = File(...)):
    expected = manuscript_text(project_id, manuscript_id)
    limit = 15 * 1024 * 1024
    raw = file.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(status_code=413, detail="El DOCX supera 15 MB.")
    try:
        document = Document(BytesIO(raw))
        if document.part.partname != "/word/document.xml":
            raise ValueError("Estructura DOCX no compatible")
    except (BadZipFile, PackageNotFoundError, KeyError, ValueError, etree.XMLSyntaxError) as exc:
        raise HTTPException(status_code=422, detail="No se pudo abrir el DOCX original.") from exc
    if "\n".join(p.text for p in document.paragraphs) != expected:
        raise HTTPException(status_code=422, detail="El DOCX no coincide con el manuscrito importado.")
    with connect() as db:
        ensure_docx_storage(db)
        db.execute(
            "INSERT OR IGNORE INTO manuscript_docx (manuscript_id, content) VALUES (?, ?)",
            (manuscript_id, raw),
        )
    return {"linked": True}


@router.post("/manuscripts/{manuscript_id}/versions/{version_id}/export-docx")
def export_preface_docx(
    project_id: str, manuscript_id: str, version_id: str, file: UploadFile | None = File(None)
):
    version = version_detail(project_id, manuscript_id, version_id)
    if version["chapter_index"] != 0 or version["chapter_title"] != "Prefacio / inicio":
        raise HTTPException(status_code=422, detail="Esta exportacion admite Prefacio / inicio.")

    limit = 15 * 1024 * 1024
    with connect() as db:
        ensure_docx_storage(db)
        stored = db.execute(
            "SELECT content FROM manuscript_docx WHERE manuscript_id = ?",
            (manuscript_id,),
        ).fetchone()
    if stored is not None:
        raw = stored["content"]
    elif file is not None:
        raw = file.file.read(limit + 1)
    else:
        raise HTTPException(status_code=409, detail="DOCX_TEMPLATE_REQUIRED")
    if len(raw) > limit:
        raise HTTPException(status_code=413, detail="El DOCX supera 15 MB.")
    try:
        document = Document(BytesIO(raw))
        if document.part.partname != "/word/document.xml":
            raise ValueError("La estructura del DOCX no es compatible.")
    except (BadZipFile, PackageNotFoundError, KeyError, ValueError, etree.XMLSyntaxError) as exc:
        raise HTTPException(status_code=422, detail="No se pudo abrir el DOCX original.") from exc

    paragraphs = document.paragraphs
    source = version["source_text"]
    full_text = "\n".join(p.text for p in paragraphs)
    if stored is None and full_text != manuscript_text(project_id, manuscript_id):
        raise HTTPException(status_code=422, detail="Selecciona el DOCX original del manuscrito importado.")
    if not source or not full_text.startswith(source):
        raise HTTPException(status_code=422, detail="Este DOCX no coincide con el prefacio original.")
    if len(source) < len(full_text) and not (
        source.endswith("\n") or full_text[len(source)] == "\n"
    ):
        raise HTTPException(status_code=422, detail="El limite cae dentro de un parrafo de Word.")

    selected = []
    position = 0
    for paragraph in paragraphs:
        if position >= len(source):
            break
        text = paragraph.text
        if position + len(text) > len(source) or "\n" in text or "\r" in text:
            raise HTTPException(status_code=422, detail="El prefacio contiene un salto interno que requiere alineacion.")
        if text.strip():
            selected.append(paragraph)
        position += len(text) + 1

    translated = [line for line in version["translated_text"].splitlines() if line.strip()]
    if not selected or len(selected) != len(translated):
        raise HTTPException(
            status_code=422,
            detail=f"No se pueden alinear los parrafos: Word={len(selected)}, revision={len(translated)}.",
        )

    w_text, w_run, w_props = map(qn, ("w:t", "w:r", "w:rPr"))
    structural_tags = {qn("w:" + tag) for tag in
                       ("br", "cr", "tab", "drawing", "fldChar", "instrText")}
    xml_space = "{http://www.w3.org/XML/1998/namespace}space"
    for number, (paragraph, replacement) in enumerate(zip(selected, translated), 1):
        if paragraph.text == replacement:
            continue
        nodes = list(paragraph._p.iter(w_text))
        if not nodes or "".join(node.text or "" for node in nodes) != paragraph.text:
            raise HTTPException(status_code=422, detail=f"Parrafo {number}: texto con estructura especial.")
        styles = set()
        for node in nodes:
            run = node.getparent()
            if run.tag != w_run or run.getparent() is not paragraph._p:
                raise HTTPException(status_code=422, detail=f"Parrafo {number}: enlace u otro elemento especial.")
            props = run.find(w_props)
            styles.add(etree.tostring(props, method="c14n") if props is not None else b"")
        if len(styles) > 1:
            raise HTTPException(status_code=422, detail=f"Parrafo {number}: formato mixto. Requiere alinear el enfasis.")
        ordered = [node for node in paragraph._p.iter() if node.tag == w_text or node.tag in structural_tags]
        first, last = ordered.index(nodes[0]), ordered.index(nodes[-1])
        if any(node.tag != w_text for node in ordered[first:last + 1]):
            raise HTTPException(status_code=422, detail=f"Parrafo {number}: salto u objeto entre fragmentos.")
        nodes[0].text = replacement
        if replacement != replacement.strip():
            nodes[0].set(xml_space, "preserve")
        for node in nodes[1:]:
            node.text = ""

    xml = etree.tostring(document.element, encoding="UTF-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as template, ZipFile(output, "w") as result:
        for member in template.infolist():
            data = xml if member.filename == "word/document.xml" else template.read(member)
            result.writestr(member, data)
    if stored is None:
        with connect() as db:
            ensure_docx_storage(db)
            db.execute(
                "INSERT OR IGNORE INTO manuscript_docx (manuscript_id, content) VALUES (?, ?)",
                (manuscript_id, raw),
            )
    return Response(
        output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
