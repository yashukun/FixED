import json
from typing import Any
from typing import Optional


def build_question_paper_prompt(
    topic: str,
    mode: str,
    total_marks: int,
    exam_time_minutes: int,
    estimated_time_minutes: int,
    section_mark_targets: dict[str, int],
    section_question_plan: dict[str, dict[str, Any]],
    source_request: str,
) -> str:
    schema_hint = {
        "marks_summary_heading": "Final Marks Summary",
        "section_headers": {
            "mcq": "Section A - Multiple Choice Questions",
            "subjective": "Section B - Subjective Questions",
            "true_false": "Section C - True / False",
            "fill_blank": "Section D - Fill in the Blanks",
        },
        "mcq": [
            {
                "question": "string",
                "options": ["string", "string", "string", "string"],
                "answer": "exactly one of the options",
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
        "marks_summary": [
            {
                "section_key": "mcq",
                "section_title": "Section A - Multiple Choice Questions",
                "target_marks": 10,
                "actual_marks": 10,
                "question_count": 10,
            },
            {
                "section_key": "grand_total",
                "section_title": "Grand Total",
                "target_marks": 40,
                "actual_marks": 40,
                "question_count": 18,
            },
        ],
    }
    return (
        "You are a teacher assistant generating a grounded question paper from retrieved textbook context.\n"
        "Output JSON only. Do not output markdown, explanations, headings, or extra keys.\n"
        "All questions must be answerable strictly from the provided context. Do not invent facts.\n"
        "Use source references from provided IDs like Ref 1, Ref 2.\n"
        f"Original user request: {source_request}\n"
        f"Mode: {mode}\n"
        f"Topic: {topic}\n"
        f"Total marks target: {total_marks}\n"
        f"Exam time in minutes: {exam_time_minutes}\n"
        f"Default estimated time if user gave none (1 mark ~= 1.2 min): {estimated_time_minutes}\n"
        f"Section mark targets: {json.dumps(section_mark_targets)}\n"
        f"Section question planning constraints: {json.dumps(section_question_plan)}\n"
        "You must include all keys exactly: mcq, subjective, true_false, fill_blank.\n"
        "Also include marks_summary_heading, section_headers, and marks_summary.\n"
        "marks_summary_heading must be exactly 'Final Marks Summary'.\n"
        "Each key must map to an array.\n"
        "If a section mark target is greater than 0, that section must contain at least one question.\n"
        "Each question must include: question, answer, marks, source_refs.\n"
        "MCQ entries must include exactly 4 options and exactly one correct answer that appears in options.\n"
        "For each MCQ, use answer as the answer key value itself (not option index/label), and that value must match one option exactly.\n"
        "True/False answers must be only True or False.\n"
        "Fill blank questions must include ____ in the question text.\n"
        "Use professional exam wording. Do not prefix question text with numbering like '1.' or 'Q1'.\n"
        "Do not use placeholder text like Option A/Option B or generic stems.\n"
        "Use per-question marks from section question planning constraints exactly; prefer more lower-mark questions when multiple valid combinations exist.\n"
        "For every section with target marks > 0, generate exactly len(question_marks) questions and assign marks in that exact sequence.\n"
        "Objective sections (MCQ, true_false, fill_blank) should stay 1 mark each.\n"
        "Subjective marks should follow requested style hints (short 2-3, case 4-5, long/derivation 5-8 where applicable).\n"
        "The total marks across all questions must equal the total marks target.\n"
        "The marks inside each section must exactly match section mark targets.\n"
        "marks_summary must reconcile section totals and include a final Grand Total row.\n"
        f"Expected JSON shape example: {json.dumps(schema_hint)}"
    )


def build_repair_prompt(
    previous_json_text: str,
    total_marks: int,
    section_mark_targets: dict[str, int],
    section_question_plan: dict[str, dict[str, Any]],
    validation_errors: list[str],
    focus_sections: Optional[list[str]] = None,
    source_request: str = "",
) -> str:
    focus_text = (
        f"Focus especially on these sections that are currently invalid or empty: {json.dumps(focus_sections)}\n"
        if focus_sections
        else ""
    )
    return (
        "Repair the JSON output so it strictly follows the required schema.\n"
        "Return JSON only.\n"
        "Keep all four section keys: mcq, subjective, true_false, fill_blank.\n"
        "Keep marks_summary_heading, section_headers, and marks_summary.\n"
        "marks_summary_heading must be exactly 'Final Marks Summary'.\n"
        "Any section with target marks > 0 must include at least one valid question.\n"
        "MCQ requires exactly 4 non-placeholder options and one correct answer from those options.\n"
        "For MCQ, answer must be the answer key value itself and match exactly one option string.\n"
        "True/False answers must be True or False. Fill blank questions must include ____.\n"
        "Use professional exam wording and do not use placeholder text.\n"
        "For every section with target marks > 0, generate exactly len(question_marks) questions and assign marks in that exact sequence.\n"
        f"Original user request: {source_request}\n"
        f"Total marks target: {total_marks}\n"
        f"Section mark targets: {json.dumps(section_mark_targets)}\n"
        f"Section question planning constraints: {json.dumps(section_question_plan)}\n"
        f"{focus_text}"
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

