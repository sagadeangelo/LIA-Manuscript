from .chapter_detector import detect_chapters
from .dialogue_detector import detect_dialogues
from .character_detector import detect_characters

def analyze(text: str) -> dict:
    return {"characters_count": len(text), "chapters": detect_chapters(text),
            "dialogues": detect_dialogues(text), "characters": detect_characters(text)}
