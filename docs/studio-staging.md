# Writer Studio · entorno de evaluación

El punto de restauración del traductor es `411b9ca669a731ddcc2c06680274a5c1fcc9e3e4`. La aplicación de escritorio arranca con su entrada anterior. El Studio arranca con `app.studio.server:app` y una carpeta de datos independiente. El portal permite probar un proyecto desde el navegador con cuentas invitadas y documentos ficticios.

## Arranque y servicios

Desde backend, instalar requirements-studio.txt en Python 3.12, Pandoc y las fuentes DejaVu en el sistema. Ejecutar LanguageTool con su servidor HTTP y usar Ollama con un modelo descargado para la evaluación. Configurar las variables en el entorno antes de ejecutar `uvicorn app.studio.server:app --host 127.0.0.1 --port 8129 --workers 1 --no-access-log`. Abrir /studio. El docker-compose alternativo es compose.studio.yml e incluye solamente la aplicación. LanguageTool y Ollama deben ser accesibles desde ese contenedor por su nombre de servicio o dirección interna. El módulo de Python no se despliega en Cloudflare Pages.

| Variable | Uso |
|---|---|
| STUDIO_ORIGIN | Origen HTTPS exacto del navegador. En pruebas locales, http://127.0.0.1:8129. Con Vite usar el origen del frontend. |
| STUDIO_DATA_DIR | Directorio privado persistente, fuera del árbol público. Una base de cuentas y una base editorial por cuenta. |
| STUDIO_INVITE | Invitación aleatoria privada de al menos 24 caracteres. Rotarla al terminar la prueba. |
| STUDIO_ADMIN_TOKEN | Segundo secreto aleatorio, mínimo 32 caracteres, para consultar /studio/admin desde una sesión autenticada. |
| STUDIO_LT_URL | Servidor propio LanguageTool para español. En el ensayo se usó 6.6. |
| LIA_OLLAMA_URL y LIA_OLLAMA_MODEL | Servicio interno de inferencia y modelo. La licencia depende de la versión exacta. |
| STUDIO_SMTP_HOST, STUDIO_SMTP_PORT, STUDIO_SMTP_USER, STUDIO_SMTP_PASSWORD y STUDIO_MAIL_FROM | Relay de staging con STARTTLS. Configurarlo activa verificación previa al inicio de sesión y recuperación mediante token de un solo uso. En el ensayo se simula la entrega de correo. |
| STUDIO_STRIPE_TEST_KEY y STUDIO_STRIPE_TEST_WEBHOOK | Opcionales para un pase de 30 días. Sólo clave sk_test y secreto del endpoint de pruebas. No guardarlos en Git. |

La pantalla de suscripción permite simular planes sin cuenta bancaria. La integración opcional POST /api/checkout genera una sesión Stripe de prueba de 10 MXN para verificar el protocolo. El cliente conserva el order_id para reintentos. El navegador vuelve a /studio. La activación la realiza el webhook /webhooks/stripe-test cuando coinciden firma, antigüedad, modo de pruebas, orden, sesión, importe y moneda. Las altas recurrentes, prorrateos, reembolsos y facturación fiscal requieren desarrollo adicional.

## Arquitectura y flujo

La landing de Vite conserva el sitio y puede habilitar un enlace a /studio con VITE_WRITER_STUDIO=true. En desarrollo el proxy apunta a 127.0.0.1:8129. En staging remoto, enrutar /studio, /studio/* y /api/* al Studio antes de la regla general de Pages. El webhook externo usa una ruta independiente. Configurar TLS, límites de carga antes del parser multipart, aislamiento de motores, volumen cifrado, copias externas y acceso privado. Utilizar un solo proceso de Uvicorn mientras el estado activo de traducción resida en memoria.

1. Crear una cuenta por invitación y un proyecto. Importar el original DOCX o TXT una sola vez.
2. Staylo analiza cada capítulo en fragmentos con LanguageTool. Las sugerencias aceptadas se guardan como otro manuscrito. El diccionario pertenece a la cuenta.
3. Manuscript usa los capítulos y segmentos del backend, el glosario y los controles de pausa, reanudación y parada. La revisión del inglés conserva la versión previa. Se puede preparar una versión traducida de un capítulo para Publish sin descargar archivos intermedios.
4. Publish usa Pandoc en el servidor para generar EPUB o DOCX con capítulos. Esta adaptación portátil reconstruye el documento editorial a partir del texto. El exportador privado de escritorio usa dart:io y carpetas temporales. Falta equiparar portada, tipografías, notas, imágenes, tablas, estilos de Word, sangrado, preflight de imprenta y composición de todas las traducciones como un solo libro.

Propuesta comercial por etapas: frontend estático en Pages; API FastAPI autenticada; PostgreSQL con propietario obligatorio por proyecto y políticas de filas; originales y derivados privados en R2; cola con reserva de créditos y trabajos durables. Separar trabajadores de LanguageTool, traducción y exportación. Cada versión debe apuntar al original, etapa y modelo. Usar claves opacas de objeto, permisos de un solo proyecto y URLs de descarga de vida corta. Para el piloto evitar Redis hasta que la concurrencia justifique una cola independiente. La administración devuelve contadores y planes agregados.

## Validación reproducible

Desde backend, ejecutar `python -m pytest -q` con Pandoc disponible. Para el recorrido de navegador instalar Playwright para Python y Chromium. Indicar LT_SERVER_JAR y, si corresponde, CHROMIUM_BINARY. Desde backend ejecutar `python ../scripts/smoke_studio_browser.py`. La prueba crea servicios de bucle local, invitación efímera y datos ficticios. STUDIO_TEST_MODEL=1 habilita la traducción real con el proveedor elegido; STUDIO_TEST_EPUB permite conservar el EPUB de prueba para EPUBCheck. La interfaz del escritorio tiene su propio ciclo de pruebas Flutter.

## Restauración y operación

Detener el Studio y permitir que los trabajos activos terminen o se detengan entre segmentos. Tomar una copia íntegra del directorio privado con permisos restringidos y cifrado externo. Restaurar en un directorio nuevo, verificar SQLite con PRAGMA integrity_check en cada base, invalidar las sesiones en la copia, iniciar un proceso aislado y verificar acceso, conteos y versiones con una cuenta sintética. Conservar la copia anterior hasta validar. El procedimiento requiere ensayos en el host elegido; el sistema de archivos del contenedor sin volumen es temporal.

## Condiciones para el piloto comercial

- Elegir licencia y proveedor de IA por variante de modelo; Qwen2.5-3B-Instruct indica uso no comercial salvo licencia concedida. Probar traducción ciega con lectores bilingües para fidelidad, voces y diálogo. Dos frases exitosamente procesadas sirven para medir transporte y descubrir fallas, no para certificar calidad de una novela.
- Verificar recepción real de correos y recuperación con el relay elegido; baja y eliminación incluidas copias de seguridad; reservas de créditos contables, cola durable, recuperación tras caída del host, cifrado y gestión de claves, observabilidad sin manuscritos. Límite de intentos de autenticación por dirección puede agrupar usuarios detrás de un proxy; definir el proxy de confianza del host.
- Resolver límites de archivos complejos y trabajos simultáneos; comprobar licencias de tipografías, diccionarios, modelos, dependencias y recursos de portada. El núcleo de LanguageTool indica LGPL 2.1 o posterior; usar instancia propia o contrato Enterprise para automatización.
- Obtener visto bueno de precios, periodo de conservación, responsables de privacidad y soporte. Completar recuperación y cancelación antes de recibir clientes. Usar infraestructura contratada por el negocio, con autorización, separada de la computadora del autor.
- La publicación comercial requiere probar el proveedor de pagos en su sandbox con sus credenciales, contratos de tratamiento y evaluación del dominio. El portal público y las cuentas con datos reales quedan fuera del entorno de prueba.

Fuentes: https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE · https://github.com/languagetool-org/languagetool · https://dev.languagetool.org/public-http-api.html · https://docs.stripe.com/webhooks/signature

Las cuotas diarias por cuenta cuentan intentos de uso de cada herramienta, incluso cuando un motor falla. No representan créditos facturables. La API administrativa PUT /api/admin/limits modifica el máximo diario sin recompilar.

Para realizar el ensayo de copia fuera de servicio: python scripts/studio_snapshot.py backup ORIGEN RESPALDO_NUEVO. Para restaurar: python scripts/studio_snapshot.py restore RESPALDO_NUEVO DESTINO_NUEVO. No arrancar el Studio hasta finalizar la copia. La restauración invalida sesiones y enlaces de correo pendientes. Las copias incluyen manuscritos; usar almacenamiento cifrado con permisos privados.

El interior PDF usa ReportLab y fuentes DejaVu incrustadas. Cada configuración crea una edición nueva recuperable: portadilla, autor, página legal, dedicatoria, índice de títulos, tamaño A5, 5×8 o 6×9 pulgadas, margen y numeración. El PDF se abre en el navegador. La aceptación de KDP y otras imprentas requiere preflight específico.
