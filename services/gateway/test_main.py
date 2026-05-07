import unittest
from fastapi.testclient import TestClient

from main import app


class GatewayMockEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_dashboard_overview(self):
        response = self.client.get("/dashboard/overview")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "mock")
        self.assertTrue(len(body["metrics"]) > 0)

    def test_learn_books(self):
        response = self.client.get("/learn/books")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("teacherUploaded", body)
        self.assertIn("studentUploaded", body)

    def test_upcoming_events(self):
        response = self.client.get("/upcoming/events")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "mock")
        self.assertTrue(len(body["events"]) > 0)


if __name__ == "__main__":
    unittest.main()
