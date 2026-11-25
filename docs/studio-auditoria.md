# Auditoría inicial y registro de validación · 25 de noviembre de 2026

## Fuentes y bases de recuperación

| Componente | Evidencia revisada | Decisión |
|---|---|---|
| Landing | lia-landing-v3, main e6568df. Vite, JavaScript, assets públicos y rutas de Train y Simulador. El sitio con guion devolvió HTTP 200 y el título de la plataforma. El sitio sin guion devolvió un documento que envía a /lander. | Integración optativa en la sección de aplicaciones. Verificar titularidad y reglas en la cuenta Cloudflare antes de cualquier cambio de dominio. |
| Staylo | main 69bc90e, ramas chore/apply-codex-review y codex/fix-grammar-error-handling-in-app, PR 1 y 2. Flutter, FastAPI y LanguageTool. El paquete de recuperación V43 incluye prueba de normalización, sugerencias y paneles. | Referencia funcional de interfaz: V43. Las ramas remotas de 2025 no acreditan la última compilación Windows. Se adaptó el flujo del diccionario, revisión por capítulo y sugerencias sin estructuras internas al navegador. |
| Manuscript | main 5b37bed. La rama work/modelos-ollama-y-progreso en 411b9ca avanzó 76 commits sobre main. Python/FastAPI, SQLite, Flutter, Ollama, importación DOCX, glosario, versiones y checkpoints. | El Studio extiende esta rama. El escritorio sigue teniendo su punto de entrada. El contexto de datos de la cuenta se propaga al hilo del trabajo. |
| Publish | Identificado el repositorio correcto en la cuenta. Contrastados main y dos ramas históricas, el código del adaptador, construcción de capítulos, navegación, manifiesto y escritor de paquetes. | Las operaciones con dart:io y archivos temporales requieren un servidor o adaptador. El staging prueba un exportador portátil de texto y capítulos usando Pandoc. No se equipara al módulo completo de escritorio. |

La auditoría de fuentes permite elegir una base por cada flujo. La funcionalidad más reciente del escritorio se confirma sólo con builds comparables y muestras autorizadas. La captura directa del sitio no acredita control de DNS. La distribución de Publish, fuentes editoriales, modelos e imágenes necesita inventario de licencias antes de entregar binarios a terceros.

## Resultados observados

| Comprobación | Resultado |
|---|---|
| Suite del traductor antes de cambios | 63 pruebas aprobadas y 32 subpruebas. |
| Backend con Studio | 65 pruebas aprobadas y 32 subpruebas. Dos advertencias de deprecación del entorno de pytest/FastAPI. |
| Landing | Build Vite y 7 de 7 regresiones Playwright. Se restauró el contenedor del hero que faltaba en la base. npm audit pasó de 3 alertas altas a 0 en el lockfile probado. |
| Navegación entre servicios | Entrada desde la landing compilable con enlace optativo; proxy Vite a FastAPI; la API responde 401 sin sesión. |
| Chromium | 1280 y 390 píxeles: alta invitada, proyecto, importación TXT, análisis real LanguageTool, revisión, versión, EPUB y salida. En escritorio además se probó traducir con Ollama real, editar la traducción y prepararla en Publish. |
| EPUB, DOCX y PDF | Importación de DOCX con dos capítulos y exportación de ambos formatos. EPUBCheck 5.2.1 pasó el EPUB generado por el navegador. Se generó un interior PDF desde una edición guardada y se comprobó el acceso por propietario. |
| Privacidad | Segunda cuenta sin acceso al proyecto, manuscrito, progreso ni exportación de la primera. Consulta administrativa requiere sesión y segundo secreto. |
| Suscripción y correo | Simulación duplicada idempotente. Webhook sintético firmado probado; rechazo de firma ausente. Verificación y restablecimiento probados con entrega de correo simulada. |
| Recuperación | Backup y restauración en destino nuevo con comprobación de integridad, invalidación de sesiones y recuperación del proyecto después de volver a iniciar sesión. |
| Motor real | Qwen2.5:3b por CPU. Una oración narrativa tardó 21.6 s incluyendo el arranque; un diálogo tardó 2.67 s en caliente y presentó comillas mal situadas. Se añadió control con regresión específica. La revisión humana de estilo y fidelidad sigue siendo necesaria. |

### Rendimiento de archivos

Dos cuentas en paralelo por tanda. TXT repetitivo sin imágenes. Tiempos de este host con SQLite y Pandoc; el segundo tiempo incluye descargar el EPUB y volver a verificar el texto del original. Excluye traducción y corrección gramatical completa.

| Palabras | Importación s | Exportación y verificación s |
|---:|---:|---:|
| 10,000 | 0.019 | 0.395 |
| 50,000 | 0.008 | 0.908 |
| 80,000 | 0.008 | 1.272 |
| 120,000 | 0.008 | 1.441 |

## Qué falta verificar

Pagos contra cuenta Stripe de pruebas, envío SMTP real, URL externa privada, hardware de producción, Docker en el host final, seguridad en el perímetro, aislamiento PostgreSQL/R2, cancelación recurrente y reembolsos. Quedan pruebas de duración con novelas completas, memoria máxima por proceso, fallos durante un trabajo activo y prueba de aceptación editorial. La base local restaurada verifica recuperación lógica, no alta disponibilidad ni recuperación ante pérdida física de un servidor. Las condiciones comerciales y jurídicas están en borrador.
