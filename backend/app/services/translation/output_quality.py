"""Deterministic output checks, never a semantic quality score.

These checks reject transport/task failures. Ambiguity and literary quality
remain review warnings; this module does not rewrite the author's text.
"""
import re


def words(value):
    return re.findall(r"[^\W\d_]+", value.casefold())


def output_issues(source, target):
    """Return stable, non-manuscript diagnostic codes for unsafe output."""
    if not isinstance(target, str):
        return ["invalid_translation_type"]
    if not target.strip():
        return ["empty_translation"]
    issues = []
    original, translated = words(source), words(target)
    if len(original) >= 5 and original == translated:
        issues.append("copied_source")
    es = set("el la los las de del que en una por para con sus esta este pero porque fue eran como donde".split())
    en = set("the of and in to was were with from for that this it they had their but as on".split())
    es_hits = sum(word in es for word in translated)
    en_hits = sum(word in en for word in translated)
    if es_hits >= 4 and es_hits >= 2 * en_hits + 2:
        issues.append("probably_source_language")
    if (sum(bool(line.strip()) for line in source.splitlines()) == 1
            and sum(bool(line.strip()) for line in target.splitlines()) != 1):
        issues.append("paragraph_structure_changed")

    # Colon artefacts recorded in model responses, not general punctuation cleanup.
    # A matching literal expression in the source may be intentional.
    malformed = r"\b(?:to|the|a|an|our|your|my|his|her|its|their)\s*:\s+[A-Za-z]+"
    for match in re.finditer(malformed, target, re.I):
        if match[0].casefold() not in source.casefold():
            issues.append("broken_function_word_colon")
            break

    # Model/task envelopes are not translated novel prose. Do not strip them and
    # silently accept a guessed remainder; retry the task instead.
    envelopes = (
        r"(?im)^\s*(?:PREVIOUS CONTEXT|FOLLOWING CONTEXT|SOURCE TEXT)\s*:\s*$",
        r"(?i)^\s*translate the following (?:text|segment) into (?:american )?english",
        r"<\uff5chy_(?:User|Assistant|EOT)\uff5c>",
    )
    if any(re.search(pattern, target) and not re.search(pattern, source)
           for pattern in envelopes):
        issues.append("model_instruction_leakage")
    discusses_translation = re.search(r"\b(?:texto|text|traducci\w*|translat\w*)\b", source, re.I)
    meta_response = re.search(
        r"(?i)^\s*(?:here is the translation\s*:|(?:the text provided is|the provided text is)"
        r".*(?:no content|series of periods|no actual|instruction|translation field))", target)
    if meta_response and not discusses_translation:
        issues.append("model_instruction_leakage")
    if target.lstrip().startswith("```") and not source.lstrip().startswith("```"):
        issues.append("unexpected_code_fence")
    wrapper = r'^\s*\{\s*"translation"\s*:'
    if re.search(wrapper, target) and not re.search(wrapper, source):
        issues.append("unexpected_translation_wrapper")
    broken_name = r"\b([A-Za-z]):\s+([A-Za-z]{3,})"
    for match in re.finditer(broken_name, target):
        letter, name = match.groups()
        if (name.casefold().startswith(letter.casefold())
                and match[0] not in source
                and not re.search(rf"(?<!\w){re.escape(letter)}(?!\w)", source)):
            issues.append("broken_name_fragment")
            break
    dangling = r"\b(?:the|a|an|of|to|and|or|with|into|from)\s*:\s*[\"'\u2019\u201d]*$"
    if re.search(dangling, target, re.I) and not source.rstrip().endswith(":"):
        issues.append("unfinished_colon_fragment")
    return list(dict.fromkeys(issues))


def paragraph_output_warnings(source, target):
    """Annotate existing versions only when paragraph alignment is unambiguous."""
    sources = [line for line in source.splitlines() if line.strip()]
    targets = [line for line in target.splitlines() if line.strip()]
    if len(sources) != len(targets):
        return []  # The consistency checker supplies the alignment warning.
    return [
        {"code": issue, "type": "output_quality_review", "severity": "review",
         "source_paragraph": index,
         "message": "Salida a cotejar con el original: " + issue}
        for index, (original, translated) in enumerate(zip(sources, targets), 1)
        for issue in output_issues(original, translated)
    ]
