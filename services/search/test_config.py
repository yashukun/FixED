import importlib
import os
import unittest


class SearchConfigTests(unittest.TestCase):
    def test_default_top_k_and_max_top_k(self):
        config = importlib.import_module("config")
        self.assertEqual(config.DEFAULT_TOP_K, 5)
        self.assertEqual(config.MAX_TOP_K, 20)

    def test_hybrid_weight_clamped_between_zero_and_one(self):
        prev = os.environ.get("SEARCH_HYBRID_VECTOR_WEIGHT")
        os.environ["SEARCH_HYBRID_VECTOR_WEIGHT"] = "2.5"
        try:
            config = importlib.import_module("config")
            config = importlib.reload(config)
            self.assertEqual(config.HYBRID_VECTOR_WEIGHT, 1.0)
        finally:
            if prev is None:
                del os.environ["SEARCH_HYBRID_VECTOR_WEIGHT"]
            else:
                os.environ["SEARCH_HYBRID_VECTOR_WEIGHT"] = prev


if __name__ == "__main__":
    unittest.main()
