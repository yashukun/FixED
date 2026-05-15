import unittest
from unittest.mock import patch

import embedder


class EmbedderValidationTests(unittest.TestCase):
    def test_process_and_store_fails_when_async_validation_fails(self):
        with (
            patch(
                "embedder.validate_upload_content",
                side_effect=ValueError("The uploaded PDF does not appear to be academic or educational."),
            ),
            patch("embedder.set_status") as set_status_mock,
        ):
            with self.assertRaises(ValueError):
                embedder.process_and_store(
                    file_bytes=b"%PDF-1.4 fake",
                    filename="notes.pdf",
                    file_id="job-1",
                )

        set_status_mock.assert_any_call("job-1", embedder.JobStatus.PROCESSING)
        set_status_mock.assert_any_call(
            "job-1",
            embedder.JobStatus.FAILED,
            error="The uploaded PDF does not appear to be academic or educational.",
        )


if __name__ == "__main__":
    unittest.main()
