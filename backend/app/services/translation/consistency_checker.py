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
    return warnings
