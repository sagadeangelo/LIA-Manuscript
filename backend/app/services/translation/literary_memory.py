def build_context(glossary: list[dict], previous_excerpt: str = "", max_chars: int = 900) -> dict:
    """Context metadata for editors; not automatically sent to a remote provider."""
    return {
        "glossary": [{"source": x["source"], "target": x["target"]} for x in glossary],
        "previous_excerpt": previous_excerpt[-max_chars:],
        "note": "Contexto editorial. Verificar continuidad manualmente.",
    }
