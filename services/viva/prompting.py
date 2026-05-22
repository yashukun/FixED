import json


def build_initial_question_prompt(topic: str, chapter_number: int | None, question_count: int, context_text: str) -> str:
    chapter_line = f"Chapter number: {chapter_number}" if chapter_number is not None else "Chapter number: not specified"
    return (
        "You are an oral viva examiner generating textbook-grounded questions.\n"
        "Use only the retrieved textbook context. Do not use outside facts.\n"
        "Keep the question concise, clear, and academically meaningful.\n"
        f"Topic: {topic}\n"
        f"{chapter_line}\n"
        f"Total questions in session: {question_count}\n"
        f"Retrieved textbook context:\n{context_text}\n"
        "Output JSON only with keys: question, expected_points."
    )


def build_question_bank_prompt(topic: str, chapter_number: int | None, question_count: int, context_text: str) -> str:
    chapter_line = f"Chapter number: {chapter_number}" if chapter_number is not None else "Chapter number: not specified"
    return (
        "You are an oral viva examiner generating textbook-grounded questions.\n"
        "Use only the retrieved textbook context. Do not use outside facts.\n"
        "Generate a full base question bank for this session.\n"
        "Questions must progress from fundamentals to deeper understanding and stay concise.\n"
        f"Topic: {topic}\n"
        f"{chapter_line}\n"
        f"Total questions required: {question_count}\n"
        f"Retrieved textbook context:\n{context_text}\n"
        "Output strict JSON only with this schema:\n"
        "{\"questions\": [{\"question\": \"...\", \"expected_points\": [\"...\", \"...\"]}]}\n"
        "Return exactly the requested number of questions."
    )


def build_followup_prompt(
    topic: str,
    previous_question: str,
    answer_transcript: str,
    question_index: int,
    total_questions: int,
    context_text: str,
) -> str:
    return (
        "You are an oral viva examiner generating textbook-grounded follow-up questions.\n"
        "Use only the retrieved textbook context. Do not use outside facts.\n"
        "Generate the next question as JSON.\n"
        "Use the student's prior response quality to decide if follow-up should deepen or remediate.\n"
        f"Topic: {topic}\n"
        f"Previous question: {previous_question}\n"
        f"Student answer transcript: {answer_transcript}\n"
        f"Next question index: {question_index + 1} of {total_questions}\n"
        f"Retrieved textbook context:\n{context_text}\n"
        "Output JSON only with keys: question, expected_points."
    )


def build_answer_evaluation_prompt(
    question: str,
    expected_points: list[str],
    answer_transcript: str,
    context_text: str,
) -> str:
    return (
        "Evaluate this oral viva answer using the expected points and retrieved textbook context.\n"
        "Do not evaluate using outside facts.\n"
        "Return JSON only with keys: score, max_score, strengths, weaknesses, feedback.\n"
        f"Question: {question}\n"
        f"Expected points: {json.dumps(expected_points)}\n"
        f"Answer transcript: {answer_transcript}\n"
        f"Retrieved textbook context:\n{context_text}\n"
        "Use max_score = 10 and score as a number between 0 and 10."
    )


def build_result_summary_prompt(topic: str, question_breakdown: list[dict]) -> str:
    return (
        "Create a concise viva performance summary and recommendations from question-level outcomes.\n"
        "Return JSON only with keys: summary, strengths, weak_areas, recommendations.\n"
        f"Topic: {topic}\n"
        f"Question breakdown: {json.dumps(question_breakdown)}"
    )
