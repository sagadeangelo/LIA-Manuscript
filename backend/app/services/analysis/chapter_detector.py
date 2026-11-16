import re

CHAPTER = re.compile(
    r"^\s*(?:cap[ií]tulo|chapter)\s+(?:\d+|[ivxlcdm]+)\b(?:\s*[:.\-–]\s*.*)?\s*$",
    re.IGNORECASE,
)

def detect_chapters(text: str) -> list[dict]:
    return [
        {"title": line.strip(), "line": number}
        for number, line in enumerate(text.splitlines(), start=1)
        if CHAPTER.fullmatch(line)
    ]
