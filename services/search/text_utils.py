"""Search text and lexical-scoring helpers."""

import re


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"\b[a-z0-9]{3,}\b", text.lower()))


def keyword_overlap_score(query_tokens: set[str], text_content: str) -> float:
    if not query_tokens:
        return 0.0
    chunk_tokens = tokenize(text_content)
    if not chunk_tokens:
        return 0.0
    overlap = len(query_tokens & chunk_tokens)
    return overlap / max(len(query_tokens), 1)


def extract_quoted_phrases(query: str) -> list[str]:
    phrases = re.findall(r"'([^']+)'|\"([^\"]+)\"", query)
    cleaned: list[str] = []
    for a, b in phrases:
        candidate = (a or b).strip().lower()
        if candidate:
            cleaned.append(candidate)
    return cleaned


def quoted_phrase_boost(phrases: list[str], text_content: str) -> float:
    if not phrases:
        return 0.0
    lowered = text_content.lower()
    matches = sum(1 for phrase in phrases if phrase in lowered)
    if matches == 0:
        return 0.0
    return min(0.15, 0.05 * matches)


def trim_context(text_content: str, max_chars: int) -> str:
    cleaned = " ".join(text_content.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3] + "..."
