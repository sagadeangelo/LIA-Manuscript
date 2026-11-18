import json
import logging
from urllib import request, error

class OllamaError(RuntimeError):
    pass

def generate(prompt: str, model: str, base_url: str, timeout: int = 360, *, structured_translation: bool = False, protected_terms: list[str] | None = None, retry_translation: bool = False, editorial_review: bool = False, glossary: dict[str, str] | None = None, previous: str = "", following: str = "") -> str:
    # La URL se configura localmente; nunca se envía el manuscrito a un proveedor externo por defecto.
    url = base_url.rstrip('/') + '/api/generate'
    options = {"model": model, "prompt": prompt, "stream": False}
    show = request.Request(
        base_url.rstrip("/") + "/api/show",
        data=json.dumps({"model": model}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(show, timeout=5) as response:
            capabilities = json.load(response).get("capabilities") or []
    except (error.URLError, TimeoutError, ValueError):
        capabilities = []
    if "thinking" in capabilities:
        options["think"] = False
    if structured_translation:
        options["system"] = (
            "Translate Spanish literary prose into natural American English. "
            "Preserve the narrator, all actions, names, time references, and paragraph breaks. "
            "Preserve negation and its scope, who performs each action, causality, quantities "
            "and modality. Interpret idioms using the narrative context rather than literally. "
            "Do not embellish, summarize, invent actions or reverse an avoided action into one performed. "
            "Put only the complete translation in the translation field."
            + (" Preserve these exact terms: " + ", ".join(protected_terms) if protected_terms else "")
        )
        options["format"] = {
            "type": "object",
            "properties": {"translation": {"type": "string"}},
            "required": ["translation"],
            "additionalProperties": False,
        }
        if retry_translation:
            options["system"] += (
                " Translate every heading and paragraph into English. "
                "For example, Dedicatoria becomes Dedication and Prefacio becomes Preface. "
                "Keep proper names as written. Return the translation without commentary."
            )
        options["options"] = {"temperature": 0.2 if retry_translation else 0}
    if structured_translation and not editorial_review and (previous or following):
        options["system"] += (
            " The input is a JSON record. Translate ONLY its source field. "
            "Use previous_context and following_context only to resolve meaning and antecedents. "
            "Do not include the context in the translation."
        )
        options["prompt"] = json.dumps({
            "source": prompt, "previous_context": previous[-700:],
            "following_context": following[:700],
        }, ensure_ascii=False)
    if editorial_review:
        options["system"] += (
            " The input is a JSON record containing the Spanish source, its English draft, "
            "and optional adjacent Spanish context. Proofread the draft against the source. "
            "Resolve antecedents using the context, but do not translate the context. "
            "Correct omissions, narrator perspective, chronology and unnatural English. "
            "Preserve every source fact, heading, proper name, and paragraph boundary. "
            "Keep a faithful draft as written. Return only the revised source translation."
        )
    if structured_translation and glossary:
        options["system"] += (
            " Use these exact source-to-English glossary equivalents: "
            + json.dumps(glossary, ensure_ascii=False)
        )

    translation_model = any(name in model.casefold() for name in ("hy-mt2", "hymt2"))
    if translation_model and structured_translation:
        if editorial_review:
            raise OllamaError("Este perfil usa traduccion nativa, no revision editorial generativa.")
        # Native single-passage task: adjacent prose was translated as extra output.
        # Keep the exact prompt shape verified locally; do not append context blocks.
        instructions = ""
        if glossary:
            instructions = "Reference the following translations:\n" + "\n".join(
                json.dumps(source, ensure_ascii=False) + " translates to " +
                json.dumps(target, ensure_ascii=False)
                for source, target in glossary.items()
            ) + "\n"
        instructions += (
            "Translate the following text into American English. "
            "Note that you should only output the translated result "
            "without any additional explanation:\n" + prompt
        )
        # Explicit official control tokens bypass the broken imported Ollama template.
        options.pop("system", None)
        options.pop("format", None)
        options["raw"] = True
        options["prompt"] = (
            "<\uff5chy_begin\u2581of\u2581sentence\uff5c>"
            "<\uff5chy_User\uff5c>" + instructions + "<\uff5chy_Assistant\uff5c>"
        )
        options["options"] = {
            "num_ctx": 4096, "num_predict": 2048,
            "temperature": 0.2 if retry_translation else 0.3,
            "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05,
            "stop": ["<\uff5chy_EOT\uff5c>", "<\uff5chy_end\u2581of\u2581sentence\uff5c>"],
        }
    payload = json.dumps(options).encode("utf-8")
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method='POST')
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = json.load(response)
    except error.HTTPError as exc:
        detail = ""
        try:
            data = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
            if isinstance(data, dict) and isinstance(data.get("error"), str):
                detail = data["error"].replace(prompt, "[texto omitido]")[:500]
        except (OSError, ValueError):
            pass
        finally:
            exc.close()
        raise OllamaError(f"Ollama HTTP {exc.code}: {detail or exc.reason}") from exc
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise OllamaError(f"No se pudo completar la solicitud a Ollama: {type(exc).__name__} (modelo {model}, espera {timeout}s)") from exc
    logging.getLogger("uvicorn.error").info(
        "Ollama model=%s think=%s stop=%s load_ms=%.0f input_ms=%.0f generation_ms=%.0f input_tokens=%s output_tokens=%s attempt=%s",
        model, options.get("think"), body.get("done_reason"),
        (body.get("load_duration") or 0) / 1e6,
        (body.get("prompt_eval_duration") or 0) / 1e6,
        (body.get("eval_duration") or 0) / 1e6,
        body.get("prompt_eval_count"), body.get("eval_count"),
        "retry" if retry_translation else "initial",
    )
    if body.get("done_reason") == "length":
        raise OllamaError(f"{model}: Ollama interrumpio la respuesta por limite de longitud.")
    result = body.get('response')
    if structured_translation and not translation_model:
        try:
            document = json.loads(result)
        except (TypeError, ValueError) as exc:
            raise OllamaError("Ollama devolvio JSON de traduccion invalido.") from exc
        if not isinstance(document, dict) or set(document) != {"translation"}:
            raise OllamaError("Ollama no devolvio el campo translation esperado.")
        result = document["translation"]
    if not isinstance(result, str) or not result.strip():
        raise OllamaError('Ollama no devolvió una traducción válida')
    return result.strip()

