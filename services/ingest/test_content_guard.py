import unittest

from content_guard import analyze_document_text


class ContentGuardTests(unittest.TestCase):
    def test_accepts_clear_academic_document_text(self):
        text = (
            "Abstract Introduction Methods Results Discussion Conclusion References "
            "This chapter presents a study guide for biology students with theorem-style "
            "explanations, exercises, and learning outcomes. "
        ) * 8
        result = analyze_document_text(text)
        self.assertTrue(result.is_academic)
        self.assertEqual(result.harmful_categories, [])
        self.assertIsNone(result.reason)

    def test_rejects_non_academic_content(self):
        text = (
            "Family vacation memories and random diary entries about daily routine, "
            "food preferences, shopping list, and weather updates."
        ) * 10
        result = analyze_document_text(text)
        self.assertFalse(result.is_academic)
        self.assertIn("does not appear to be academic or educational", result.reason or "")

    def test_accepts_educational_biography_material(self):
        text = (
            "Chapter 1 Biography of Dr. B. R. Ambedkar. This history lesson explains his "
            "education, social reforms, and constitutional work in modern India. "
            "The literature and historical context helps students understand political science. "
        ) * 8
        result = analyze_document_text(text)
        self.assertTrue(result.is_academic)
        self.assertEqual(result.harmful_categories, [])
        self.assertIsNone(result.reason)

    def test_rejects_harmful_promotional_content_even_if_educational_terms_exist(self):
        text = (
            "Chapter 1 Introduction to marketing. Buy now! Limited time offer! "
            "Click here to subscribe now and use promo code SAVE20. "
        ) * 8
        result = analyze_document_text(text)
        self.assertIn("spam or promotional solicitation", result.harmful_categories)
        self.assertIn("not allowed", result.reason or "")


if __name__ == "__main__":
    unittest.main()
