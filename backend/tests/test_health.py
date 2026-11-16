import os
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app


def test_health_and_project_creation():
    with tempfile.TemporaryDirectory() as temp:
        original = settings.data_dir
        settings.data_dir = Path(temp)
        try:
            with TestClient(app) as client:
                response = client.get("/health")
                assert response.status_code == 200
                assert response.json()["status"] == "ok"
                created = client.post("/api/projects", json={"name": "Novela de prueba"})
                assert created.status_code == 201
                pid = created.json()["id"]
                uploaded = client.post(f"/api/projects/{pid}/manuscripts", files={"file": ("novela.txt", b"Capitulo 1\nTexto de prueba", "text/plain")})
                assert uploaded.status_code == 201
                assert uploaded.json()["characters"] > 0
                assert client.get(f"/api/projects/{pid}/manuscripts").json()
        finally:
            settings.data_dir = original