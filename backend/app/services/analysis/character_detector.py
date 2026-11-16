import re

ATTRIBUTION = re.compile(r'\b(?:dijo|preguntó|respondió|exclamó|susurró)\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ-]+)')

def detect_characters(text: str) -> list[str]:
    return sorted(set(ATTRIBUTION.findall(text)), key=str.casefold)
