import unittest

from text_utils import (
    extract_quoted_phrases,
    keyword_overlap_score,
    quoted_phrase_boost,
    tokenize,
    trim_context,
)


class TextUtilsTests(unittest.TestCase):
    def test_tokenize_and_overlap(self):
        query_tokens = tokenize("Explain Chapter 3 photosynthesis")
        score = keyword_overlap_score(query_tokens, "This chapter explains photosynthesis in detail.")
        self.assertGreater(score, 0.0)

    def test_extract_quoted_phrases(self):
        phrases = extract_quoted_phrases('Explain "cell membrane" and \'osmosis\'')
        self.assertEqual(phrases, ["cell membrane", "osmosis"])

    def test_phrase_boost_caps(self):
        boost = quoted_phrase_boost(["a", "b", "c", "d"], "a b c d a b")
        self.assertEqual(boost, 0.15)

    def test_trim_context_shortens(self):
        text = "word " * 30
        trimmed = trim_context(text, 20)
        self.assertTrue(trimmed.endswith("..."))
        self.assertLessEqual(len(trimmed), 20)


if __name__ == "__main__":
    unittest.main()
