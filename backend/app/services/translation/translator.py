import json
import os
import re
from .consistency_checker import check_consistency
from ..providers.ollama_provider import OllamaError, generate

MAX_SEGMENT = 6000


def _term_pattern(term):
    return rf"(?<!\w){re.escape(term)}(?!\w)"


def _segment_glossary(text, protected_terms):
    if isinstance(protected_terms, dict):
        entries = protected_terms
        legacy = []
    else:
        entries = {}
        legacy = list(protected_terms or [])

    active = {
        source: target for source, target in entries.items()
        if source and target and re.search(_term_pattern(source), text)
    }
    if re.search(_term_pattern("Millenicalls"), text) and "Millenicalls" not in active:
        active["Millenicalls"] = "Millenicalls"
    return active, list(dict.fromkeys([*legacy, *active.values()]))


def _apply_glossary(text, glossary):
    # Already translated terms take priority if they overlap a source term.
    targets = set(glossary.values())
    aliases = {source: target for source, target in glossary.items()
               if source != target and source not in targets}
    if not aliases:
        return text
    forms = sorted(targets | aliases.keys(), key=lambda value: (-len(value), value))
    pattern = "|".join(_term_pattern(form) for form in forms)
    return re.sub(pattern, lambda match: aliases.get(match[0], match[0]), text)


def _missing_terms(text, glossary):
    return [
        target for target in dict.fromkeys(glossary.values())
        if not re.search(_term_pattern(target), text)
    ]


def translate_segment(text: str, protected_terms: list[str] | dict[str, str] | None = None, model: str | None = None) -> dict:
    if not text.strip():
        raise ValueError('El segmento está vacío')
    if len(text) > MAX_SEGMENT:
        raise ValueError(f'El segmento supera {MAX_SEGMENT} caracteres; divídelo antes de traducir')
    glossary, terms = _segment_glossary(text, protected_terms)
    has_genocide = bool(re.search(r"\bgenocidio\b", text, re.IGNORECASE))

    heading = re.match(r"(?im)^[ \t]*(dedicatoria|prefacio)[ \t]*\r?$", text.lstrip())
    expected_heading = None
    if heading:
        label = heading.group(1)
        expected_heading = {"dedicatoria": "Dedication", "prefacio": "Preface"}[label.casefold()]
        if label.isupper():
            expected_heading = expected_heading.upper()
    model_name = model or os.getenv('LIA_OLLAMA_MODEL', 'llama3.1:8b')
    base_url = os.getenv('LIA_OLLAMA_URL', 'http://127.0.0.1:11434')
    source_words = re.findall(r"[^\W\d_]+", text.casefold())
    spanish = set("el la los las de del que en una por para con sus esta este pero porque fue eran como donde".split())
    english = set("the of and in to was were with from for that this it they had their but as on".split())

    for retry in (False, True):
        translated = generate(
            text.strip() if retry or expected_heading else text,
            model_name,
            base_url,
            structured_translation=True,
            protected_terms=terms,
            retry_translation=retry,
            glossary=glossary,
        )
        translated = _apply_glossary(translated, glossary)
        words = re.findall(r"[^\W\d_]+", translated.casefold())
        spanish_hits = sum(word in spanish for word in words)
        english_hits = sum(word in english for word in words)
        copied = len(source_words) >= 5 and source_words == words
        likely_spanish = spanish_hits >= 4 and spanish_hits >= 2 * english_hits + 2
        issues = []
        if copied or likely_spanish:
            issues.append("copia del original" if copied else "salida probablemente en espanol")

        if expected_heading:
            first_line, newline, rest = translated.partition("\n")
            label = first_line.strip().lstrip("#").strip().strip("*").strip().rstrip(":")
            if label.casefold() in {"dedicatoria", "dedication", "prefacio", "preface"} and (
                label.casefold() in {"dedicatoria", "dedication"}
            ) == (expected_heading.casefold() == "dedication"):
                translated = expected_heading + newline + rest
            else:
                issues.append(f"falta el encabezado {expected_heading}")

        for term in _missing_terms(translated, glossary):
            issues.append(f"falta el termino del glosario: {term}")
        if has_genocide and not re.search(r"\bgenocid(?:e|al)\b", translated, re.IGNORECASE):
            issues.append("falta la referencia al genocidio")

        if not issues:
            break
    else:
        reason = "; ".join(issues)
        raise ValueError(
            f"Traduccion rechazada tras 2 intentos: {reason} "
            f"(marcadores ES={spanish_hits}, EN={english_hits})."
        )
    return {"translation": translated, "provider": "ollama", "model": model_name,
            "warnings": check_consistency(text, translated, terms)}


def translate_and_review(text, protected_terms=None, model=None, *, previous="", following=""):
    draft = translate_segment(text, protected_terms=protected_terms, model=model)
    glossary, terms = _segment_glossary(text, protected_terms)
    original = draft["translation"]

    def paragraph_count(value):
        return sum(bool(line.strip()) for line in value.splitlines())

    try:
        revised = generate(
            json.dumps({
                "source": text, "draft": original,
                "previous_context": previous[-350:], "following_context": following[:350],
            }, ensure_ascii=False),
            draft["model"], os.getenv("LIA_OLLAMA_URL", "http://127.0.0.1:11434"),
            timeout=90, structured_translation=True, protected_terms=terms,
            editorial_review=True, glossary=glossary,
        )
        revised = _apply_glossary(revised, glossary)
        if _missing_terms(revised, glossary):
            raise ValueError("La revision omitio un termino del glosario.")
        words = re.findall(r"[^\W\d_]+", revised.casefold())
        spanish = set("el la los las de del que en una por para con sus esta este pero porque fue eran como donde".split())
        english = set("the of and in to was were with from for that this it they had their but as on".split())
        es = sum(word in spanish for word in words)
        en = sum(word in english for word in words)
        if (not words or words == re.findall(r"[^\W\d_]+", text.casefold())
                or es >= 4 and es >= 2 * en + 2
                or paragraph_count(revised) != paragraph_count(original)
                or any(term in original and term not in revised for term in terms)
                or re.search(r"\bgenocidio\b", text, re.I)
                and not re.search(r"\bgenocid(?:e|al)\b", revised, re.I)):
            raise ValueError("La revision no conservo la estructura, el idioma o los terminos.")
        warnings = check_consistency(text, revised, terms)
        if any(warning not in draft["warnings"] for warning in warnings):
            raise ValueError("La revision introdujo un aviso de consistencia.")
    except (OllamaError, ValueError) as exc:
        return {**draft, "warnings": [
            *draft["warnings"],
            {"type": "editorial_review_pending",
             "message": f"Revision automatica pendiente ({type(exc).__name__}). Se conservo el borrador."},
        ]}
    return {**draft, "translation": revised, "warnings": warnings}
