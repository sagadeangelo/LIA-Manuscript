from fastapi import APIRouter
from ...core.database import connect

router = APIRouter(tags=["health"])

@router.get("/health")
def health():
    with connect() as db:
        db.execute("SELECT 1").fetchone()
    return {"status": "ok", "database": "ok", "service": "lia-manuscript"}