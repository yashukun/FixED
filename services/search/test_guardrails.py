import unittest

from guardrails import build_guardrail_answer


class GuardrailTests(unittest.TestCase):
    def test_greeting_returns_book_nudge(self):
        answer = build_guardrail_answer("hi")
        self.assertIsNotNone(answer)
        self.assertIn("Let me know if you have any questions from the book you selected.", answer)

    def test_smalltalk_returns_book_nudge(self):
        answer = build_guardrail_answer("How are you?")
        self.assertIsNotNone(answer)
        self.assertTrue(answer.startswith("Hi!"))

    def test_simple_arithmetic_returns_answer_and_nudge(self):
        answer = build_guardrail_answer("1 + 1")
        self.assertEqual(
            answer,
            "It's 2. Let me know if you have any questions from the book you selected.",
        )

    def test_division_by_zero_response(self):
        answer = build_guardrail_answer("what is 5 / 0?")
        self.assertEqual(
            answer,
            "It's undefined (division by zero). Let me know if you have any questions from the book you selected.",
        )

    def test_book_context_query_not_guardrailed(self):
        answer = build_guardrail_answer("Explain chapter 2 from this book")
        self.assertIsNone(answer)


if __name__ == "__main__":
    unittest.main()
