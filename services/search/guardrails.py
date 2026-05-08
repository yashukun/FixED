"""Deterministic guardrails for non-book assistant queries."""

from __future__ import annotations

import re

BOOK_NUDGE = "Let me know if you have any questions from the book you selected."

_BOOK_CONTEXT_KEYWORDS = (
    "book",
    "chapter",
    "page",
    "document",
    "topic",
    "explain",
    "summarize",
    "summary",
    "quiz",
    "question",
    "concept",
    "paragraph",
    "source",
    "reference",
)

_GREETING_PATTERNS = (
    r"^\s*(hi|hello|hey|hii|yo)\s*[!.?]*\s*$",
    r"^\s*good\s+(morning|afternoon|evening)\s*[!.?]*\s*$",
    r"^\s*(thanks|thank you)\s*[!.?]*\s*$",
    r"^\s*how are you\s*[?.!]*\s*$",
)

_ARITHMETIC_PATTERN = re.compile(
    r"^\s*(?:(?:what\s+is|what's|calculate|solve)\s+)?"
    r"([-+]?\d+(?:\.\d+)?)\s*([+\-*/])\s*([-+]?\d+(?:\.\d+)?)\s*[=?]?\s*\??\s*$",
    re.IGNORECASE,
)


def _contains_book_context(query: str) -> bool:
    lowered = query.lower()
    return any(keyword in lowered for keyword in _BOOK_CONTEXT_KEYWORDS)


def _is_greeting_or_smalltalk(query: str) -> bool:
    lowered = query.lower().strip()
    return any(re.match(pattern, lowered) for pattern in _GREETING_PATTERNS)


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6g}"


def _solve_simple_arithmetic(query: str) -> str | None:
    match = _ARITHMETIC_PATTERN.match(query.strip())
    if not match:
        return None

    left = float(match.group(1))
    operator = match.group(2)
    right = float(match.group(3))

    if operator == "+":
        return _format_number(left + right)
    if operator == "-":
        return _format_number(left - right)
    if operator == "*":
        return _format_number(left * right)
    if operator == "/":
        if right == 0:
            return "undefined (division by zero)"
        return _format_number(left / right)
    return None


def build_guardrail_answer(query: str) -> str | None:
    if _contains_book_context(query):
        return None

    arithmetic_result = _solve_simple_arithmetic(query)
    if arithmetic_result is not None:
        return f"It's {arithmetic_result}. {BOOK_NUDGE}"

    if _is_greeting_or_smalltalk(query):
        return f"Hi! {BOOK_NUDGE}"

    return None
