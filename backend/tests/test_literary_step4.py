import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app
from app.services.translation.chapter_pipeline import split_segments, chapter_slices


def test_split_is_lossless():
    text = "Capítulo 1\n" + "Ángelo caminó. " * 900 + "\n\nCapítulo 2\nFinal."
    parts = split_segments(text, 500)
    assert len(parts) > 2
    assert "".join(parts) == text
    assert len(chapter_slices(text)) == 2


def test_glossary_versions_and_isolation():
    with tempfile.TemporaryDirectory() as temp:
        old = settings.data_dir
        settings.data_dir = Path(temp)
        try:
            with TestClient(app) as client:
                p = client.post("/api/projects", json={"name": "Ficción"}).json()["id"]
                other = client.post("/api/projects", json={"name": "Otro"}).json()["id"]
                upload = client.post(f"/api/projects/{p}/manuscripts", files={
                    "file": ("novela.txt", "Capítulo 1\nÁngelo llegó.\n\nCapítulo 2\nSe fue.".encode(), "text/plain")})
                assert upload.status_code == 201
                mid = upload.json()["id"]
                term = client.post(f"/api/projects/{p}/glossary", json={
                    "source": "Ángelo", "target": "Ángelo"})
                assert term.status_code == 201
                assert client.post(f"/api/projects/{p}/glossary", json={
                    "source": "Ángelo", "target": "Ángelo"}).status_code == 409
                assert len(client.get(f"/api/projects/{p}/glossary").json()) == 1
                assert len(client.get(f"/api/projects/{p}/manuscripts/{mid}/chapters").json()) == 2
                assert client.get(f"/api/projects/{other}/manuscripts/{mid}/chapters").status_code == 404
                with patch("app.api.routes.literary_step4.translate_chapter", return_value={
                    "translation": "Chapter 1\nÁngelo arrived.\n\n", "segments": 1, "warnings": []}):
                    res = client.post(f"/api/projects/{p}/manuscripts/{mid}/translate-chapter",
                                      json={"chapter_index": 0})
                assert res.status_code == 201, res.text
                vid = res.json()["id"]
                assert len(client.get(f"/api/projects/{p}/manuscripts/{mid}/versions").json()) == 1
                detail = client.get(f"/api/projects/{p}/manuscripts/{mid}/versions/{vid}")
                assert detail.status_code == 200
                assert "Ángelo llegó" in detail.json()["source_text"]
                assert client.get(f"/api/projects/{other}/manuscripts/{mid}/versions/{vid}").status_code == 404
                assert client.post(f"/api/projects/{p}/manuscripts/{mid}/translate-chapter",
                                   json={"chapter_index": 99}).status_code == 422
        finally:
            settings.data_dir = old
