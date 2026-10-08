"""Check the new gateway and its round trip through the existing live API."""

import json
import os
import unittest
import urllib.error
import urllib.request

import httpx
from fastapi.testclient import TestClient

from src.app import service

CONTRACT = "prepared-features-v1"


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.reply = None

        def upstream(request):
            self.calls.append(request)
            if self.reply is not None:
                return self.reply(request)
            body = {"model_sha256": "a" * 64, "contract_version": CONTRACT}
            body.update({"status": "ready"} if request.method == "GET" else {"prediction_code": 1})
            return httpx.Response(200, json=body)

        self.client = TestClient(service.create_app(transport=httpx.MockTransport(upstream)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_page_assets_and_source_boundary(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="feature-form"', page.text)
        for asset in ("app.js", "styles.css"):
            response = self.client.get("/static/" + asset)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/static/service.py").status_code, 404)
        self.assertEqual(self.client.get("/docs").status_code, 404)
        self.assertIn("script-src 'self'", page.headers["content-security-policy"])

    def test_example_is_the_baked_reference(self):
        expected = json.loads((service.HERE / "example_features.json").read_text())
        response = self.client.get("/api/example")
        self.assertEqual(response.json(), {"features": expected})
        self.assertEqual(len(expected), 28)
        self.assertEqual(expected["year_acc"], 2021)
        self.assertEqual(self.calls, [])

    def test_prediction_bytes_and_identity_are_preserved(self):
        body = b'{"features":{"place":10,"place":11}}'
        response = self.client.post("/api/predict", content=body,
                                    headers={"Content-Type": "application/json", "Authorization": "unused"})
        self.assertEqual(response.json(), {"prediction_code": 1, "model_sha256": "a" * 64,
                                           "contract_version": CONTRACT})
        self.assertEqual(self.calls[0].content, body)
        self.assertEqual(str(self.calls[0].url), "http://api:8000/predict")
        self.assertNotIn("authorization", self.calls[0].headers)

    def test_api_error_status_and_detail_are_preserved(self):
        for status in (400, 422, 500, 503):
            with self.subTest(status=status):
                self.reply = lambda request: httpx.Response(status, json={"detail": "API rejected request."})
                response = self.client.post("/api/predict", content=b"{}",
                                            headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json(), {"detail": "API rejected request."})

    def test_local_media_type_and_body_limit(self):
        self.assertEqual(self.client.post("/api/predict", content="{}").status_code, 415)
        large = self.client.post("/api/predict", content=b" " * (service.MAX_BODY_BYTES + 1),
                                 headers={"Content-Type": "application/json"})
        self.assertEqual(large.status_code, 413)
        self.assertEqual(self.calls, [])

    def test_unavailable_and_unexpected_upstream(self):
        def unavailable(request):
            raise httpx.ConnectError("Internal connection information", request=request)

        self.reply = unavailable
        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Internal connection information", response.text)
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.reply = lambda request: httpx.Response(200, text="Unexpected HTML")
        self.assertEqual(self.client.get("/health/ready").status_code, 502)

    def test_readiness_preserves_api_contract(self):
        response = self.client.get("/api/health/ready")
        self.assertEqual(response.json(), {"status": "ready", "model_sha256": "a" * 64,
                                           "contract_version": CONTRACT})
        self.assertEqual(str(self.calls[0].url), "http://api:8000/health/ready")


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "Running Compose services required")
class LiveRoundTripTests(unittest.TestCase):
    def request(self, base, path, body=None):
        data = None if body is None else body.encode()
        request = urllib.request.Request(base + path, data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=35)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read()

    def test_application_to_selected_live_api(self):
        local = "http://127.0.0.1:8080"
        status, html = self.request(local, "/")
        self.assertEqual(status, 200)
        self.assertIn(b'id="feature-form"', html)
        for asset in ("app.js", "styles.css"):
            self.assertEqual(self.request(local, "/static/" + asset)[0], 200)
        status, ready = self.request(local, "/api/health/ready")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(ready)["model_sha256"], os.environ["EXPECTED_MODEL_SHA256"])
        status, example = self.request(local, "/api/example")
        self.assertEqual(status, 200)
        proxied = self.request(local, "/api/predict", example.decode())
        direct = self.request("http://api:8000", "/predict", example.decode())
        self.assertEqual(proxied[0], 200)
        self.assertEqual(json.loads(proxied[1]), json.loads(direct[1]))
        result = json.loads(proxied[1])
        self.assertIn(result["prediction_code"], (0, 1))
        self.assertEqual(result["contract_version"], CONTRACT)
        print(json.dumps({"model_sha256": result["model_sha256"],
                          "example_prediction_code": result["prediction_code"],
                          "direct_and_proxied_responses_equal": True}))

    def test_live_api_rejection_through_application(self):
        features = json.loads((service.HERE / "example_features.json").read_text())
        features["place"] = True
        bodies = [(json.dumps({"features": features}), 422), ("{", 400),
                  ('{"features":{},"features":{}}', 422)]
        for body, expected in bodies:
            with self.subTest(expected=expected):
                status, result = self.request("http://127.0.0.1:8080", "/api/predict", body)
                direct = self.request("http://api:8000", "/predict", body)
                self.assertEqual(status, expected)
                self.assertEqual(json.loads(result), json.loads(direct[1]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
