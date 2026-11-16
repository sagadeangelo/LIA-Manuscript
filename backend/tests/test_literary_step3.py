import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core.config import settings
from app.main import app
from app.services.analysis.manuscript_analysis import analyze
from app.services.translation.consistency_checker import check_consistency

def test_analysis_and_consistency():
    text = 'Capítulo 1\n—Hola —dijo Ángelo.\nEl año era 2024.'
    result = analyze(text)
    assert len(result['chapters']) == 1
    assert len(result['dialogues']) == 1
    assert 'Ángelo' in result['characters']
    warnings = check_consistency(text, 'Hello, said someone in 2025.', ['Ángelo'])
    assert {w['code'] for w in warnings} == {'protected_term_missing', 'numbers_changed'}

def test_preview_mocked_and_analysis_route():
    with tempfile.TemporaryDirectory() as tmp:
        original = settings.data_dir
        settings.data_dir = Path(tmp)
        try:
            with TestClient(app) as client:
                project = client.post('/api/projects', json={'name':'Prueba literaria'}).json()
                pid = project['id']
                upload = client.post(f'/api/projects/{pid}/manuscripts', files={'file':('book.txt', 'Capítulo 1\n—Hola —dijo Ángelo.'.encode(), 'text/plain')})
                assert upload.status_code == 201
                mid = upload.json()['id']
                analysis = client.get(f'/api/projects/{pid}/manuscripts/{mid}/analysis')
                assert analysis.status_code == 200
                assert len(analysis.json()['chapters']) == 1
                with patch('app.services.translation.translator.generate', return_value='Hello, said Ángelo.'):
                    translated = client.post('/api/translations/preview', json={'text':'Hola, dijo Ángelo.', 'protected_terms':['Ángelo']})
                assert translated.status_code == 200
                assert translated.json()['provider'] == 'ollama'
                assert translated.json()['warnings'] == []
        finally:
            settings.data_dir = original

def test_ollama_unavailable_returns_503():
    from app.services.providers.ollama_provider import OllamaError
    with TestClient(app) as client:
        with patch('app.services.translation.translator.generate', side_effect=OllamaError('No disponible')):
            response = client.post('/api/translations/preview', json={'text':'Hola'})
        assert response.status_code == 503
