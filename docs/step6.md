# LIA Manuscript - Paso 6

Interfaz Flutter conectada a FastAPI local. Crear proyectos, importar TXT/DOCX (15 MB), leer capítulos reales, registrar glosario, traducir por Ollama y consultar versiones SQLite.

La traducción del Paso 4 es síncrona, limitada a capítulos de 30000 caracteres. La barra es indeterminada y no hay cancelación de trabajos en servidor. El glosario registra términos y protege fuentes; no garantiza la aplicación de equivalencias destino en el prompt. No hay edición/guardado manual de borradores todavía.

Iniciar backend: desde backend, `..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8102`.
Iniciar Flutter: desde frontend, `flutter run -d windows`.
Requiere Ollama ejecutándose localmente y modelo instalado para traducciones reales.
