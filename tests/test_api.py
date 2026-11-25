"""API tests. They need FastAPI + httpx (see requirements-dev.txt) and are skipped otherwise."""
import os
import unittest

try:
    from fastapi.testclient import TestClient
    from app import main
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        os.environ["GEMINI_API_KEY"] = "test-key"
        self.client = TestClient(main.app)
        main._extract_limiter._hits.clear()
        main._analyze_limiter._hits.clear()
        self._original = main.extract_receipt

    def tearDown(self):
        main.extract_receipt = self._original
        os.environ.pop("GEMINI_API_KEY", None)

    def test_health_and_headers(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_index_page_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_extract_success_and_per_file_errors(self):
        main.extract_receipt = lambda data, mime, settings: {
            "vendor": "Swiggy", "amount": 100.0, "currency": "INR", "date": None,
            "language": None, "category": "Food & Dining", "confidence": 0.9}
        files = [("files", ("a.png", PNG, "image/png")),
                 ("files", ("evil.png", b"<script>alert(1)</script>", "image/png"))]
        body = self.client.post("/api/extract", files=files).json()
        self.assertTrue(body["results"][0]["ok"])
        self.assertFalse(body["results"][1]["ok"])
        self.assertIn("JPEG, PNG or WebP", body["results"][1]["error"])

    def test_extract_without_key_is_503(self):
        os.environ["GEMINI_API_KEY"] = ""
        response = self.client.post("/api/extract", files=[("files", ("a.png", PNG, "image/png"))])
        self.assertEqual(response.status_code, 503)

    def test_extract_too_many_files(self):
        files = [("files", (f"{i}.png", PNG, "image/png")) for i in range(6)]
        self.assertEqual(self.client.post("/api/extract", files=files).status_code, 400)

    def test_extract_rate_limited(self):
        main.extract_receipt = lambda *a, **k: {"vendor": "x", "amount": 1.0, "currency": "INR", "date": None,
                                               "language": None, "category": "Other", "confidence": 1.0}
        codes = [self.client.post("/api/extract", files=[("files", ("a.png", PNG, "image/png"))]).status_code
                 for _ in range(25)]
        self.assertIn(429, codes)

    def test_analyze_ok(self):
        payload = {"expenses": [{"vendor": "Swiggy", "amount": 900, "category": "Food & Dining", "date": "2026-11-05"}],
                   "budgets": {"Food & Dining": 500}, "month": "2026-11"}
        data = self.client.post("/api/analyze", json=payload).json()
        self.assertEqual(data["total_spent"], 900.0)
        self.assertEqual(data["categories"][0]["status"], "over")

    def test_analyze_rejects_bad_input(self):
        bad_payloads = [
            {"expenses": [{"vendor": "x", "amount": -5, "category": "Other"}]},
            {"expenses": [{"vendor": "x", "amount": 5, "category": "Crypto"}]},
            {"expenses": [{"vendor": "x", "amount": 5, "category": "Other", "date": "2026-02-31"}]},
            {"expenses": [], "budgets": {"Nope": 5}},
            {"expenses": [], "month": "2026-13"},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/api/analyze", json=payload).status_code, 422)


if __name__ == "__main__":
    unittest.main()
