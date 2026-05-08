"""Prompt and context-budget helpers for search answers."""

from config import CHAPTER_CONTEXT_CHARS, FACTOID_CONTEXT_CHARS, WHOLE_BOOK_CONTEXT_CHARS


def build_system_prompt(task: str, style: str, language: str) -> str:
    task_instructions = {
        "summarize": "Give a compact explanation of the main ideas in paragraph form.",
        "explain": "Explain the concept in connected teaching-style paragraphs with simple examples when useful.",
        "qa": "Answer directly in natural paragraph form.",
        "generate_questions": "Only generate practice questions when the user explicitly asks for them.",
        "compare": "Explain similarities and differences in paragraph form unless the user explicitly asks for a table.",
        "translate": f"Translate accurately into {language} in natural paragraph form.",
        "mind_map": "Only provide mind-map style output if the user explicitly asks for it.",
        "quiz": "Only provide quiz format if the user explicitly asks for it.",
        "other": "Answer clearly in paragraph form using the available context.",
    }
    style_instructions = {
        "beginner": "Use simple classroom language suitable for a beginner student.",
        "child": "Use very simple, age-appropriate classroom language.",
        "academic": "Use formal but clear academic language.",
        "default": "Use clear teacher-like classroom language.",
    }
    return (
        "You are a teacher helping a student understand textbook content.\n"
        "Answer strictly from retrieved context and do not invent facts.\n"
        "Default to natural explanatory paragraphs, not headings, bullet points, or conclusion blocks.\n"
        "Use lists, tables, or other structured formats only when the user explicitly asks for them.\n"
        "Keep the tone instructional, clear, and calm; avoid robotic or overly chatty phrasing.\n"
        "Cite references naturally as [Ref N], and include page/location guidance only when it adds value.\n"
        "Never use the word 'chunk' in citations.\n"
        f"Task behavior: {task_instructions.get(task, task_instructions['other'])}\n"
        f"Style behavior: {style_instructions.get(style, style_instructions['default'])}"
    )


def context_char_budget(scope: str) -> int:
    if scope == "whole_book":
        return WHOLE_BOOK_CONTEXT_CHARS
    if scope in ("chapter", "page", "paragraph"):
        return CHAPTER_CONTEXT_CHARS
    return FACTOID_CONTEXT_CHARS
