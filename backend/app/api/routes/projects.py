from datetime import datetime, timezone
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ...core.database import connect

router = APIRouter(prefix="/api/projects", tags=["projects"])

class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

@router.post("", status_code=201)
def create_project(payload: ProjectCreate):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="El nombre no puede estar vacÃ­o")
    record = {"id": str(uuid4()), "name": name, "created_at": datetime.now(timezone.utc).isoformat()}
    with connect() as db:
        db.execute("INSERT INTO projects (id,name,created_at) VALUES (:id,:name,:created_at)", record)
    return record

@router.get("")
def list_projects():
    with connect() as db:
        rows = db.execute("SELECT id,name,created_at FROM projects ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]

@router.get("/{project_id}")
def get_project(project_id: str):
    with connect() as db:
        row = db.execute("SELECT id,name,created_at FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return dict(row)