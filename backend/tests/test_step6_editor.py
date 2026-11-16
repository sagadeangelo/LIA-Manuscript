import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

def test_editor_chapter_detail():
    with tempfile.TemporaryDirectory() as folder:
        old = settings.data_dir
        settings.data_dir = Path(folder)
        try:
            with TestClient(app) as client:
                p = client.post('/api/projects', json={'name':'Paso 6'}).json()['id']
                upload = client.post(f'/api/projects/{p}/manuscripts', files={'file':('novela.txt', 'Capítulo 1\nHola.\nCapítulo 2\nAdiós.'.encode('utf-8'), 'text/plain')})
                assert upload.status_code == 201
                mid = upload.json()['id']
                chapters = client.get(f'/api/projects/{p}/manuscripts/{mid}/chapters').json()
                assert len(chapters) == 2
                detail = client.get(f'/api/projects/{p}/manuscripts/{mid}/chapters/1')
                assert detail.status_code == 200
                assert 'Adiós.' in detail.json()['text']
                assert client.get(f'/api/projects/{p}/manuscripts/{mid}/chapters/9').status_code == 404
        finally:
            settings.data_dir = old
