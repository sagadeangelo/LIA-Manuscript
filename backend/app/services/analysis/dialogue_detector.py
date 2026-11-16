import re

# La raya literaria puede comenzar una linea o seguir al titulo/narracion.
# No interpretar guiones internos de palabras como dialogos.
DIALOGUE = re.compile(r"^\s*[—–-]\s*(\S.*)$")

def detect_dialogues(text: str) -> list[dict]:
    result = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = DIALOGUE.match(line)
        if match:
            result.append({"line": number, "text": match.group(1).strip()})
    return result
