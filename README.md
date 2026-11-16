<div align="center">

# LIA-Manuscript

**Traducción literaria del español al inglés americano**

![Ollama](https://img.shields.io/badge/IA_local-Ollama-22D3EE?style=flat-square)
![Flutter](https://img.shields.io/badge/Escritorio-Flutter-A78BFA?style=flat-square)
![FastAPI](https://img.shields.io/badge/API-FastAPI-4ADE80?style=flat-square)
![LanguageTool](https://img.shields.io/badge/Correcci%C3%B3n-en--US-FDE047?style=flat-square)

</div>

LIA-Manuscript es una aplicación local para traducir novelas y otros manuscritos por capítulo. Permite cotejar el original con el borrador en inglés, corregir pasajes y guardar revisiones sin sobrescribir las versiones anteriores.

## Flujo editorial

| Etapa | Qué puedes hacer |
| --- | --- |
| 🟦 **Importar** | Cargar un manuscrito TXT o DOCX y navegar por sus capítulos. |
| 🟪 **Traducir** | Elegir un modelo local de Ollama y consultar el progreso por segmentos. |
| 🟩 **Revisar** | Comparar español e inglés, editar el borrador y consultar los avisos disponibles. |
| 🟨 **Pulir el inglés** | Usar LanguageTool en `en-US` para marcar fragmentos, aplicar sugerencias y agregar nombres al diccionario local. |
| 💾 **Guardar** | Crear una versión revisada para conservar el historial del capítulo. |

El **glosario editorial** define equivalencias entre el original y la traducción. El **diccionario local** conserva grafías elegidas por el autor, como nombres propios o términos inventados.

## Arquitectura

| Componente | Función |
| --- | --- |
| Flutter para Windows | Editor comparativo y revisión bilingüe |
| FastAPI · `127.0.0.1:8102` | Importación, traducción y gestión de versiones |
| SQLite | Proyectos, manuscritos y revisiones |
| Ollama · `127.0.0.1:11434` | Traducción y revisión automática local |
| LanguageTool · `127.0.0.1:8101` | Ortografía, gramática y estilo en inglés americano |

## Arranque local

La instalación de desarrollo usa Windows, PowerShell, Python, Flutter y Ollama. El corrector inglés usa el servidor local de LanguageTool con Java.

Desde la raíz de una instalación que ya tenga sus dependencias y sus iniciadores configurados:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\INICIAR_LIA_MANUSCRIPT_CON_LT.ps1
```

Selecciona un modelo instalado, como `qwen2.5:3b` o `qwen3:4b`, y empieza con un capítulo corto. La calidad y el tiempo de traducción dependen del modelo, el manuscrito y el equipo.

## Estado del proyecto

El flujo local de traducción, revisión y guardado se ha probado con fragmentos de un manuscrito real. La **exportación DOCX con maquetación** sigue en validación con el prefacio. El objetivo es aplicar una versión guardada sobre una copia del Word original, conservando estilos, márgenes, encabezados y saltos manuales. La paginación automática puede variar con la longitud del inglés.

Este repositorio se está preparando para incorporar el código de la instalación de desarrollo.
