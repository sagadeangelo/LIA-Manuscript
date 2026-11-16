from contextlib import asynccontextmanager
from fastapi import FastAPI
from .core.database import initialize
from .api.routes import health, projects, manuscripts, translations, literary_step4

@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    yield

app = FastAPI(title="LIA Manuscript API", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(projects.router)
app.include_router(manuscripts.router)
app.include_router(translations.router)

app.include_router(literary_step4.router)

from .api.routes import step6_editor
app.include_router(step6_editor.router)
