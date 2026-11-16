# Paso 3: análisis y traducción literaria

- `GET /api/projects/{project_id}/manuscripts/{manuscript_id}/analysis`: análisis heurístico inicial.
- `POST /api/translations/preview`: traducción real con Ollama local, sin persistir ni reemplazar el original.
- Requiere Ollama activo en `http://127.0.0.1:11434` y un modelo instalado.
- Variables opcionales: `LIA_OLLAMA_URL`, `LIA_OLLAMA_MODEL`.
- Las pruebas simulan Ollama: no prueban la calidad literaria ni requieren GPU.
- El detector de personajes es heurístico; no constituye identificación exhaustiva.
- Pendientes: segmentación avanzada, memoria persistente, revisión humana, exportación, interfaz Flutter.
