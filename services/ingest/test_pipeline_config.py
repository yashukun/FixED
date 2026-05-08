import importlib
import os
import unittest


class IngestPipelineConfigTests(unittest.TestCase):
    def test_default_chunk_values(self):
        config = importlib.import_module("pipeline_config")
        self.assertEqual(config.CHUNK_SIZE, 350)
        self.assertEqual(config.CHUNK_OVERLAP, 70)

    def test_reads_override_from_environment(self):
        prev = os.environ.get("INGEST_CHUNK_SIZE")
        os.environ["INGEST_CHUNK_SIZE"] = "512"
        try:
            config = importlib.import_module("pipeline_config")
            config = importlib.reload(config)
            self.assertEqual(config.CHUNK_SIZE, 512)
        finally:
            if prev is None:
                del os.environ["INGEST_CHUNK_SIZE"]
            else:
                os.environ["INGEST_CHUNK_SIZE"] = prev


if __name__ == "__main__":
    unittest.main()
