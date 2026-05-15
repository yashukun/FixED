import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class _FakeDbSession:
    def __init__(self):
        self.rows = []

    def add(self, row):
        self.rows.append(row)


@contextmanager
def _fake_db_context():
    yield _FakeDbSession()


class IngestUploadEndpointTests(unittest.TestCase):
    def setUp(self):
        self.init_db_patcher = patch("main.init_db", return_value=None)
        self.init_db_patcher.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.init_db_patcher.stop()

    def test_upload_queues_pdf_for_async_validation_and_processing(self):
        with (
            patch("main.storage.upload", return_value="documents/job-id/notes.pdf"),
            patch("main.get_db_context", side_effect=_fake_db_context),
            patch("main.process_document_task.delay", return_value=None),
        ) as (_, _, delay_mock):
            response = self.client.post(
                "/upload",
                files={"file": ("notes.pdf", b"%PDF-1.4 valid", "application/pdf")},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("job_id", payload)
        self.assertEqual(payload["status"], "pending")
        self.assertTrue(delay_mock.called)


if __name__ == "__main__":
    unittest.main()
