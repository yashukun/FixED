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
        self.assertEqual(body["source"], "live")
        self.assertIn("metrics", body)
        self.assertIn("todayFocus", body)

    def test_learn_books(self):
        response = self.client.get("/learn/books")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("books", body)

    def test_upcoming_events(self):
        response = self.client.get("/upcoming/events")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "live")
        self.assertIn("events", body)

    def test_analytics_summary(self):
        response = self.client.get("/dashboard/analytics/summary")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "live")
        self.assertIn("usage_volume", body)
        self.assertIn("total_tokens", body)

    def test_analytics_timeseries(self):
        response = self.client.get("/dashboard/analytics/timeseries")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "live")
        self.assertIn("points", body)

    def test_analytics_breakdown(self):
        response = self.client.get("/dashboard/analytics/breakdown")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "live")
        self.assertIn("by_service", body)
        self.assertIn("by_model", body)
        self.assertIn("by_kind", body)


if __name__ == "__main__":
    unittest.main()
