from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ...core.database import connect
from ...services.analysis.manuscript_analysis import analyze
from ...services.translation.translator import translate_segment
from ...services.providers.ollama_provider import OllamaError

router = APIRouter(prefix='/api', tags=['literary-translation'])

class TranslationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    protected_terms: list[str] = Field(default_factory=list, max_length=100)
    model: str | None = None

@router.get('/projects/{project_id}/manuscripts/{manuscript_id}/analysis')
def manuscript_analysis(project_id: str, manuscript_id: str):
    with connect() as db:
        row = db.execute('SELECT text FROM manuscripts WHERE id=? AND project_id=?', (manuscript_id, project_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Manuscrito no encontrado')
    return analyze(row['text'])

@router.post('/translations/preview')
def translation_preview(payload: TranslationRequest):
    if any(len(term) > 120 for term in payload.protected_terms):
        raise HTTPException(status_code=422, detail='Término protegido demasiado largo')
    try:
        return translate_segment(payload.text, payload.protected_terms, payload.model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
