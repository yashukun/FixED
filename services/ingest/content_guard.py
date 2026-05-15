from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Dict, List

from pypdf import PdfReader

MAX_PAGES_TO_SCAN = 25
MIN_WORDS_FOR_ACADEMIC_CONFIDENCE = 120

ACADEMIC_KEYWORDS = {
    "abstract",
    "introduction",
    "methodology",
    "methods",
    "results",
    "discussion",
    "conclusion",
    "references",
    "bibliography",
    "chapter",
    "exercise",
    "curriculum",
    "syllabus",
    "lecture",
    "lesson",
    "theorem",
    "proof",
    "experiment",
    "assignment",
    "question",
    "objective",
    "learning outcomes",
    "study guide",
    "journal",
    "thesis",
    "dissertation",
}

ACADEMIC_PATTERNS = [
    re.compile(r"\b(abstract|introduction|conclusion|references)\b", re.IGNORECASE),
    re.compile(r"\b(chapter|unit)\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b(figure|table)\s+\d+\b", re.IGNORECASE),
    re.compile(r"\[[0-9]{1,3}\]"),
    re.compile(r"\bdoi:\s*10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE),
]

EDUCATIONAL_NONFICTION_KEYWORDS = {
    "biography",
    "autobiography",
    "memoir",
    "historical",
    "history",
    "civilization",
    "geography",
    "literature",
    "philosophy",
    "economics",
    "political science",
    "curriculum",
    "student",
    "teacher",
}

HARMFUL_PATTERNS: Dict[str, List[re.Pattern[str]]] = {
    "adult/explicit sexual material": [
        re.compile(r"\b(hardcore porn|pornographic|xxx)\b", re.IGNORECASE),
        re.compile(r"\b(explicit sex|sexual services|escort services)\b", re.IGNORECASE),
    ],
    "hate or discriminatory content": [
        re.compile(r"\b(ethnic cleansing|racial supremacy)\b", re.IGNORECASE),
        re.compile(r"\b(kill all\s+[a-z]+)\b", re.IGNORECASE),
        re.compile(r"\b(hate speech)\b", re.IGNORECASE),
    ],
    "graphic violence or disturbing content": [
        re.compile(r"\b(beheading|dismembered|gore)\b", re.IGNORECASE),
        re.compile(r"\b(graphic violence|snuff)\b", re.IGNORECASE),
    ],
    "spam or promotional solicitation": [
        re.compile(r"\b(buy now|limited time offer|act now)\b", re.IGNORECASE),
        re.compile(r"\b(click here|subscribe now|promo code)\b", re.IGNORECASE),
        re.compile(r"\b(earn money fast|guaranteed returns)\b", re.IGNORECASE),
    ],
}

HARMFUL_THRESHOLDS = {
    "adult/explicit sexual material": 1,
    "hate or discriminatory content": 1,
    "graphic violence or disturbing content": 1,
    "spam or promotional solicitation": 2,
}


@dataclass
class ContentValidationResult:
    is_academic: bool
    harmful_categories: list[str]
    reason: str | None = None


def _extract_pdf_text(file_bytes: bytes, max_pages: int = MAX_PAGES_TO_SCAN) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    extracted_parts: list[str] = []
    for index, page in enumerate(reader.pages):
        if index >= max_pages:
            break
        text = (page.extract_text() or "").strip()
        if text:
            extracted_parts.append(text)
    return "\n".join(extracted_parts).strip()


def analyze_document_text(text: str) -> ContentValidationResult:
    normalized = re.sub(r"\s+", " ", text).strip()
    words = normalized.split()
    word_count = len(words)
    lower_text = normalized.lower()

    keyword_hits = sum(1 for keyword in ACADEMIC_KEYWORDS if keyword in lower_text)
    pattern_hits = sum(1 for pattern in ACADEMIC_PATTERNS if pattern.search(normalized))
    educational_nonfiction_hits = sum(
        1 for keyword in EDUCATIONAL_NONFICTION_KEYWORDS if keyword in lower_text
    )

    has_academic_structure = keyword_hits >= 3 or pattern_hits >= 2 or (keyword_hits >= 2 and pattern_hits >= 1)
    has_educational_nonfiction_signal = educational_nonfiction_hits >= 2 and keyword_hits >= 1
    is_academic = word_count >= MIN_WORDS_FOR_ACADEMIC_CONFIDENCE and (
        has_academic_structure or has_educational_nonfiction_signal
    )

    harmful_categories: list[str] = []
    for category, patterns in HARMFUL_PATTERNS.items():
        hit_count = sum(len(pattern.findall(normalized)) for pattern in patterns)
        if hit_count >= HARMFUL_THRESHOLDS[category]:
            harmful_categories.append(category)

    if harmful_categories:
        reason = (
            "The file appears to contain content not allowed for this workspace: "
            + ", ".join(harmful_categories)
            + ". Please upload educational material without this type of content."
        )
        return ContentValidationResult(
            is_academic=is_academic,
            harmful_categories=harmful_categories,
            reason=reason,
        )

    if not is_academic:
        return ContentValidationResult(
            is_academic=False,
            harmful_categories=[],
            reason=(
                "The uploaded PDF does not appear to be academic or educational. "
                "Please upload learning-oriented material such as textbooks, lecture notes, "
                "study guides, journals, theses, or course handbooks."
            ),
        )

    return ContentValidationResult(is_academic=True, harmful_categories=[])


def validate_upload_content(filename: str, file_bytes: bytes) -> None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext != "pdf":
        return

    try:
        text = _extract_pdf_text(file_bytes)
    except Exception as exc:
        raise ValueError("The uploaded file is not a readable PDF document.") from exc
    if not text:
        raise ValueError(
            "Could not extract readable text from this PDF. Please upload a text-based academic PDF."
        )

    result = analyze_document_text(text)
    if result.reason:
        raise ValueError(result.reason)
