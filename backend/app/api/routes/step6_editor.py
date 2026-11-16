from fastapi import APIRouter, HTTPException
from ...core.database import connect
from ...services.translation.chapter_pipeline import chapter_slices

router = APIRouter(prefix="/api/projects/{project_id}/manuscripts/{manuscript_id}", tags=["editor-step6"])

@router.get("/chapters/{chapter_index}")
def chapter_detail(project_id: str, manuscript_id: str, chapter_index: int):
    with connect() as db:
        row = db.execute("SELECT text FROM manuscripts WHERE project_id=? AND id=?", (project_id, manuscript_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Manuscrito no encontrado")
    chunks = chapter_slices(row["text"])
    if chapter_index < 0 or chapter_index >= len(chunks):
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")
    return {"index": chapter_index, **chunks[chapter_index]}
