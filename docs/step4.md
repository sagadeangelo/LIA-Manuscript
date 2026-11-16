# PASO 4 — Traducción literaria por capítulos

- `GET /api/projects/{project_id}/glossary`: lista términos persistentes.
- `POST /api/projects/{project_id}/glossary`: agrega término (source, target, note).
- `GET /api/projects/{project_id}/manuscripts/{manuscript_id}/chapters`: índices de capítulos.
- `POST /api/projects/{project_id}/manuscripts/{manuscript_id}/translate-chapter`: traduce **un** capítulo, de forma síncrona, usando Ollama local; crea una versión borrador solo si termina sin errores.
- `GET /api/projects/{project_id}/manuscripts/{manuscript_id}/versions`: lista borradores.
- `GET /api/projects/{project_id}/manuscripts/{manuscript_id}/versions/{version_id}`: recupera original y traducción.
- `GET /api/projects/{project_id}/manuscripts/{manuscript_id}/memory`: metadatos editoriales para continuidad.

**Límites:** 30 000 caracteres por capítulo y 4 500 por segmento. La operación es síncrona, sin cola ni porcentaje de progreso en tiempo real. El glosario protege términos fuente y guarda equivalencias, pero la equivalencia destino aún no se inyecta en los prompts. La memoria editorial aún no se utiliza automáticamente al traducir. Las versiones son borradores inmutables. No hay edición ni aprobación de versiones todavía. El original no se modifica. Las pruebas simulan el proveedor IA, no certifican calidad de traducción.
