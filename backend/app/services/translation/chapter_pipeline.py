import re
from collections.abc import Callable
from ..analysis.chapter_detector import detect_chapters
from .translator import translate_and_review
from ..providers.ollama_provider import OllamaError

MAX_SEGMENT = 2000

def split_segments(text: str, limit: int = MAX_SEGMENT) -> list[str]:
    if not text.strip():
        raise ValueError("Texto vacio")
    if limit < 100 or limit > 6000:
        raise ValueError("Limite invalido")
    parts = []
    for paragraph in re.split(r"(\n\s*\n)", text):
        if not paragraph:
            continue
        if len(paragraph) <= limit:
            parts.append(paragraph)
        else:
            # Preserve every character, even for very long paragraphs.
            while len(paragraph) > limit:
                window = paragraph[:limit]
                boundaries = list(re.finditer(r"[.!?](?:[\x22\x27??)]*)\s+", window))
                spaces = list(re.finditer(r"\s+", window))
                cut = next((m.end() for m in reversed(boundaries) if m.end() >= limit // 2),
                           spaces[-1].end() if spaces else limit)
                parts.append(paragraph[:cut])
                paragraph = paragraph[cut:]
            if paragraph:
                parts.append(paragraph)
    output = []
    for part in parts:
        if output and len(output[-1]) + len(part) <= limit:
            output[-1] += part
        else:
            output.append(part)
    assert "".join(output) == text
    return output

def chapter_slices(text: str) -> list[dict]:
    headers = detect_chapters(text)
    lines = text.splitlines(keepends=True)
    if not headers:
        return [{"title": "Manuscrito completo", "text": text}]
    starts = [sum(len(line) for line in lines[:h["line"] - 1]) for h in headers]
    results = []
    if starts[0] > 0 and text[:starts[0]].strip():
        results.append({"title": "Prefacio / inicio", "text": text[:starts[0]]})
    for i, header in enumerate(headers):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        results.append({"title": header["title"], "text": text[starts[i]:end]})
    return results


_DITOX_COVER = [
    "\u00c1ngelo & El Proyecto Dit\u00f3x.",
    "Copyright \u00a9 2017-2024",
    "ISBN: 9798322812210",
    "Kindle Direct Publishing",
]



def _translate_lines(sections, terms, model, on_progress):
    pieces = []
    for index, section in enumerate(sections):
        lines = [line.strip() for line in section.splitlines() if line.strip()]
        if index == 0 and lines == _DITOX_COVER:
            pieces.append((section, None))
            continue

        for line in section.splitlines(keepends=True):
            label = line.strip()
            if not label:
                pieces.append((line, None))
                continue

            heading = {"dedicatoria": "Dedication", "prefacio": "Preface"}.get(label.casefold())
            if heading is not None:
                if label.isupper():
                    heading = heading.upper()
                leading = line[:len(line) - len(line.lstrip())]
                trailing = line[len(line.rstrip()):]
                pieces.append((leading + heading + trailing, None))
                continue

            for segment in split_segments(line):
                pieces.append((segment, bool(segment.strip())))

    total = sum(needs_translation is True for _, needs_translation in pieces)
    if total == 0:
        raise ValueError("El capitulo no contiene parrafos traducibles.")
    if on_progress:
        on_progress(0, total)

    prose = [source.strip() for source, needs_translation in pieces if needs_translation]
    results = {}
    failures = {}

    def translate_piece(index):
        result = translate_and_review(
            prose[index], protected_terms=terms, model=model,
            previous=prose[index - 1] if index else "",
            following=prose[index + 1] if index + 1 < total else "",
        )
        translated = result["translation"].strip()
        if not translated:
            raise ValueError("Ollama devolvio una traduccion vacia.")
        if len(translated.splitlines()) != 1:
            raise ValueError("La traduccion cambio la estructura del parrafo.")
        results[index] = (translated, result["warnings"])
        failures.pop(index, None)
        if on_progress:
            on_progress(len(results), total)

    # Retry only missing pieces before assembling or saving the chapter.
    for index in range(total):
        try:
            translate_piece(index)
        except (OllamaError, ValueError) as exc:
            failures[index] = exc

    for index in list(failures):
        try:
            translate_piece(index)
        except (OllamaError, ValueError) as exc:
            failures[index] = exc

    if failures:
        details = "; ".join(
            f"tramo {index + 1}/{total}: {error}"
            for index, error in failures.items()
        )
        message = f"{model or 'Modelo predeterminado'} - capitulo incompleto: {details}"
        if any(isinstance(error, OllamaError) for error in failures.values()):
            raise OllamaError(message)
        raise ValueError(message)

    outputs, warnings = [], []
    index = 0
    for source, needs_translation in pieces:
        if not needs_translation:
            outputs.append(source)
            continue
        translated, notices = results[index]
        leading = source[:len(source) - len(source.lstrip())]
        trailing = source[len(source.rstrip()):]
        outputs.append(leading + translated + trailing)
        warnings.extend({**warning, "segment": index + 1} for warning in notices)
        index += 1
    return {"translation": "".join(outputs), "segments": total, "warnings": warnings}


def translate_chapter(
    text: str, terms: list[str] | dict[str, str], model: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    front_matter_sections = re.split(
        r"(?im)(?=^[ \t]*(?:dedicatoria|prefacio)[ \t]*\r?$)", text
    )
    return _translate_lines(front_matter_sections, terms, model, on_progress)
