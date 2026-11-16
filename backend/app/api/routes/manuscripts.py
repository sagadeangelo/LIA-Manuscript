from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4
from fastapi import APIRouter, HTTPException, UploadFile, File
from docx import Document
from ...core.config import settings
from ...core.database import connect
from ...services.analysis.chapter_detector import detect_chapters

router = APIRouter(prefix="/api/projects/{project_id}/manuscripts", tags=["manuscripts"])

@router.post("", status_code=201)
async def upload_manuscript(project_id: str, file: UploadFile = File(...)):
    filename = (file.filename or "").replace("\\", "/").split("/")[-1]
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if extension not in {"txt", "docx"}:
        raise HTTPException(status_code=415, detail="Solo se admiten archivos TXT y DOCX")
    with connect() as db:
        if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    raw = await file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="El archivo supera 15 MB")
    if not raw:
        raise HTTPException(status_code=422, detail="Archivo vacÃ­o")
    try:
        if extension == "txt":
            text = raw.decode("utf-8-sig")
        else:
            document = Document(BytesIO(raw))
            text = "\n".join(p.text for p in document.paragraphs)
    except (UnicodeError, ValueError, Exception) as exc:
        raise HTTPException(status_code=422, detail="No se pudo leer el manuscrito") from exc
    if not text.strip():
        raise HTTPException(status_code=422, detail="El manuscrito no contiene texto")
    record = {"id": str(uuid4()), "project_id": project_id, "filename": filename,
              "text": text, "created_at": datetime.now(timezone.utc).isoformat()}
    with connect() as db:
        db.execute("INSERT INTO manuscripts (id,project_id,filename,text,created_at) VALUES (:id,:project_id,:filename,:text,:created_at)", record)
    return {"id": record["id"], "project_id": project_id, "filename": filename,
            "characters": len(text), "chapters": detect_chapters(text)}

@router.get("")
def list_manuscripts(project_id: str):
    with connect() as db:
        if db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Proyecto no encontrado")
        rows = db.execute("SELECT id,filename,created_at,length(text) AS characters FROM manuscripts WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    return [dict(row) for row in rows]

@router.get("/{manuscript_id}")
def get_manuscript(project_id: str, manuscript_id: str):
    with connect() as db:
        row = db.execute("SELECT id,project_id,filename,text,created_at FROM manuscripts WHERE id=? AND project_id=?", (manuscript_id,project_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Manuscrito no encontrado")
    record = dict(row)
    record["chapters"] = detect_chapters(record["text"])
    return record