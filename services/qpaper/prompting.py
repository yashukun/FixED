import json
from typing import Any


def build_question_paper_prompt(
    topic: str,
    mode: str,
    total_marks: int,
    section_mark_targets: dict[str, int],
) -> str:
    schema_hint = {
        "mcq": [
            {
                "question": "string",
                "options": ["string", "string", "string", "string"],
                "answer": "string",
                "marks": 1,
                "source_refs": ["Ref 1"],
            }
        ],
        "subjective": [
            {
                "question": "string",
                "answer": "string",
                "marks": 5,
                "source_refs": ["Ref 2"],
            }
        ],
        "true_false": [
            {
                "question": "string",
                "answer": "True or False",
                "marks": 1,
                "source_refs": ["Ref 3"],
            }
        ],
        "fill_blank": [
            {
                "question": "string with ____",
                "answer": "string",
                "marks": 1,
                "source_refs": ["Ref 4"],
            }
        ],
    }
    return (
        "You are a teacher assistant generating a grounded question paper from retrieved textbook context.\n"
        "Output JSON only. Do not output markdown, explanations, headings, or extra keys.\n"
        "All questions must be answerable strictly from the provided context. Do not invent facts.\n"
        "Use source references from provided IDs like Ref 1, Ref 2.\n"
        f"Mode: {mode}\n"
        f"Topic: {topic}\n"
        f"Total marks target: {total_marks}\n"
        f"Section mark targets: {json.dumps(section_mark_targets)}\n"
        "You must include all keys exactly: mcq, subjective, true_false, fill_blank.\n"
        "Each key must map to an array (can be empty).\n"
        "Each question must include: question, answer, marks, source_refs.\n"
        "MCQ entries should also include options (4 options).\n"
        "Prefer fewer, higher-quality questions by using reasonable per-question marks instead of too many 1-mark questions.\n"
        "Suggested marks per question: mcq 1-2, subjective 4-8, true_false 1, fill_blank 1.\n"
        "Aim for a compact paper length where possible while still matching mark targets.\n"
        "The total marks across all questions must equal the total marks target.\n"
        "The marks inside each section should closely match section mark targets.\n"
        f"Expected JSON shape example: {json.dumps(schema_hint)}"
    )


def build_repair_prompt(
    previous_json_text: str,
    total_marks: int,
    section_mark_targets: dict[str, int],
    validation_errors: list[str],
) -> str:
    return (
        "Repair the JSON output so it strictly follows the required schema.\n"
        "Return JSON only.\n"
        f"Total marks target: {total_marks}\n"
        f"Section mark targets: {json.dumps(section_mark_targets)}\n"
        f"Validation errors to fix: {json.dumps(validation_errors)}\n"
        f"Previous output: {previous_json_text}"
    )


def normalize_distribution(raw: dict[str, Any]) -> dict[str, int]:
    normalized = {
        "mcq": int(raw.get("mcq", 0) or 0),
        "subjective": int(raw.get("subjective", 0) or 0),
        "true_false": int(raw.get("true_false", 0) or 0),
        "fill_blank": int(raw.get("fill_blank", 0) or 0),
    }
    return normalized

