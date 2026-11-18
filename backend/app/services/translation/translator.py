import json
import os
import re
from .consistency_checker import check_consistency
from ..providers.ollama_provider import OllamaError, generate

MAX_SEGMENT = 6000


def is_layout_only(text):
    """Punctuation, ornament lines and scene separators need no model."""
    return bool(text.strip()) and not any(char.isalnum() for char in text)


def _repetition_signatures(text):
    words = re.findall(r"[^\W_]+", text.casefold())
    phrases = {}
    for index in range(len(words) - 4):
        phrase = tuple(words[index:index + 5])
        phrases[phrase] = phrases.get(phrase, 0) + 1
    return {phrase: count for phrase, count in phrases.items() if count > 1}


def review_damage_reasons(draft, revised):
    """Conservative surface checks, not a semantic fidelity score."""
    reasons = []
    before = re.findall(r"[^\W_]+", draft)
    after = re.findall(r"[^\W_]+", revised)
    if len(before) >= 12 and len(after) < len(before) * 0.80:
        reasons.append("posible omision: la revision elimino mas del 20% de las palabras")
    old_repeats = _repetition_signatures(draft)
    if any(count > old_repeats.get(phrase, 1)
           for phrase, count in _repetition_signatures(revised).items()):
        reasons.append("la revision introdujo una frase repetida")
    # Preserve repetitions already present in a deliberate literary draft.
    pattern = r"\b([^\W\d_]+)[\s,:;]+\1\b"
    old_adjacent = {match[0].casefold() for match in re.finditer(pattern, draft, re.I)}
    if any(match[0].casefold() not in old_adjacent
           for match in re.finditer(pattern, revised, re.I)):
        reasons.append("la revision introdujo palabras duplicadas")
    dangling = r"\b(?:the|a|an|of|to|and|or|with|into|from)\s*[:;,]?\s*[\"'\u2019\u201d]*$"
    if re.search(dangling, revised, re.I) and not re.search(dangling, draft, re.I):
        reasons.append("la revision termino con una construccion incompleta")
    broken = r"\b[A-Za-z]:\s+[A-Za-z]{3,}"
    if re.search(broken, revised) and not re.search(broken, draft):
        reasons.append("la revision introdujo un fragmento de palabra con dos puntos")
    return reasons


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
    if is_layout_only(text):
        return {"translation": text, "provider": "passthrough",
                "model": model or os.getenv("LIA_OLLAMA_MODEL", "llama3.1:8b"),
                "warnings": []}
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
    if draft["provider"] == "passthrough":
        return draft
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
        damage = review_damage_reasons(original, revised)
        if damage:
            raise ValueError("; ".join(damage))
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
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        return {**draft, "warnings": [
            *draft["warnings"],
            {"type": "editorial_review_pending",
             "message": f"Revision automatica pendiente ({reason}). Se conservo el borrador."},
        ]}
    return {**draft, "translation": revised, "warnings": warnings}
