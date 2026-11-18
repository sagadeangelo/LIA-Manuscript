import re

def check_consistency(source: str, translated: str, protected_terms: list[str] | None = None) -> list[dict]:
    warnings = []
    if not translated.strip():
        return [{"code": "empty_translation", "message": "La traducción está vacía"}]
    for term in protected_terms or []:
        if term and re.search(re.escape(term), source, flags=re.IGNORECASE) and not re.search(re.escape(term), translated, flags=re.IGNORECASE):
            warnings.append({"code": "protected_term_missing", "term": term, "message": "Término protegido ausente"})
    source_numbers = re.findall(r'(?<!\w)\d+(?:[.,]\d+)?(?!\w)', source)
    target_numbers = re.findall(r'(?<!\w)\d+(?:[.,]\d+)?(?!\w)', translated)
    if source_numbers != target_numbers:
        warnings.append({"code": "numbers_changed", "message": "Revisar cifras", "source": source_numbers, "target": target_numbers})
    return warnings + fidelity_warnings(source, translated)

def fidelity_warnings(source: str, translated: str) -> list[dict]:
    """Heuristic review candidates; absence of warnings does not certify fidelity."""
    warnings = []
    src, dst = source.casefold(), translated.casefold().replace("\u2019", "'")

    def flag(code, message):
        warnings.append({"code": code, "type": "fidelity_review",
                         "message": message, "severity": "review"})

    if re.search(r"\bmiles de millones\b", src) and not re.search(r"\bbillions?\b", dst):
        flag("quantity_scale", "Posible cambio de escala numerica: cotejar miles de millones.")
    if (re.search(r"\bacaso\b.*\bno\b", src)
            and re.search(r"\b(?:perhaps|maybe)\b.*\b(?:not|wasn't|isn't)\b", dst)):
        flag("rhetorical_negation", "Posible inversion de una pregunta retorica negativa.")
    source_negation = re.search(r"\b(?:no|nunca|jamas|jamás|ni|sin|evit\w*|impid\w*)\b", src)
    target_negation = re.search(
        r"\b(?:not|never|no|without|neither|nor|cannot|avoid\w*|prevent\w*|"
        r"impossible|unable|lack\w*|fail\w*)\b|\b\w+n't\b", dst)
    complex_scope = re.search(
        r"\b(?:evit\w*|impid\w*)\b|\bno\s+(?:\w+\s+){0,3}(?:\w+ara|\w+iera|\w+ase|\w+iese)\b", src)
    if source_negation and (not target_negation or complex_scope):
        flag("negation_scope", "Cotejar la negacion y su alcance: que accion se evita o se niega.")
    if (re.search(r"\b(?:tenernos|mantenernos|ser|estar)\s+(?:mas |más )?controlad\w*", src)
            and re.search(r"\b(?:we|us|our)\b.*\b(?:maintain|have|gain|take)\b.*\bcontrol\b", dst)):
        flag("control_roles", "Posible cambio de roles: estar bajo control frente a tener el control.")
    if ("por debajo del agua" in src
            and re.search(r"\b(?:under\s*water|beneath\s+(?:the\s+)?water|under\s+the\s+water)\b", dst)
            and re.search(r"\b(?:gobern\w*|dirig\w*|paises|países|politic\w*|polític\w*)\b", src)):
        flag("literal_idiom", "Posible traduccion literal de una expresion figurada en contexto politico.")
    if (re.search(r"\bbombas?\b", src) and re.search(r"\bbombs?\b", dst)
            and re.search(r"\b(?:vert\w*|bombeo|tuber\w*|filtr\w*|riego)\b", src)):
        flag("ambiguous_equipment", "Cotejar bombas en contexto de fluidos: pumps frente a bombs.")
    if (re.search(r"\b(?:eleg\w*|escog\w*|seleccion\w*)\b", src)
            and re.search(r"\blista de diez\b", src)
            and re.search(r"\b(?:choose|select|pick)\s+ten\b", dst)):
        flag("selection_quantity", "Posible cambio de cantidad: elegir de una lista no implica elegir a todos.")
    return warnings


def paragraph_fidelity_warnings(source: str, translated: str) -> list[dict]:
    """Only assign a paragraph when a one-to-one nonempty line alignment exists."""
    source_lines = [line for line in source.splitlines() if line.strip()]
    target_lines = [line for line in translated.splitlines() if line.strip()]
    if len(source_lines) != len(target_lines):
        return [{"code": "fidelity_alignment_pending", "type": "fidelity_review",
                 "message": "No se puede asignar el cotejo automatico por parrafo: revisar alineacion.",
                 "severity": "review"}]
    return [
        {**warning, "source_paragraph": index}
        for index, (original, target) in enumerate(zip(source_lines, target_lines), 1)
        for warning in fidelity_warnings(original, target)
    ]
