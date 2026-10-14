"""Check tracking-target selection, DagsHub authentication and transfer hashes without network access."""

import base64
import hashlib
import http.client
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tracking.import_reference_run import ImportFailure, LocalClient
from tracking.track_pipeline_run import PipelineTracker, TrackingFailure


DAGSHUB_URI = "https://dagshub.com/SiR1979/prediction_severity_car_accidents.mlflow"
PREFIX = "/SiR1979/prediction_severity_car_accidents.mlflow"
TOKEN = "fixture-token-0123456789"
CREDENTIALS = {"MLFLOW_TRACKING_USERNAME": "fixture-user", "MLFLOW_TRACKING_PASSWORD": TOKEN}
RUN = {"info": {"artifact_uri": "mlflow-artifacts:/exp/run/artifacts"}}


class FakeResponse:
    def __init__(self, status, body=b""):
        self.status = status
        self.body = body

    def read(self, size=-1):
        content, self.body = (self.body, b"") if size < 0 else (self.body[:size], self.body[size:])
        return content


class FakeConnection:
    """Record one request and answer with a fixed response."""

    def __init__(self, response):
        self.response = response
        self.method = self.url = None
        self.headers = {}
        self.sent = b""

    def request(self, method, url, body=None, headers=None):
        self.method, self.url = method, url
        self.headers = dict(headers or {})
        self.sent = body or b""

    def putrequest(self, method, url):
        self.method, self.url = method, url

    def putheader(self, header, value):
        self.headers[header] = value

    def endheaders(self):
        pass

    def send(self, chunk):
        self.sent += chunk

    def getresponse(self):
        return self.response

    def close(self):
        pass


def dagshub_client():
    return LocalClient(DAGSHUB_URI, environ=CREDENTIALS)


def answer(client, status, body=b""):
    connection = FakeConnection(FakeResponse(status, body))
    patch.object(client, "connection", return_value=connection).start()
    return connection


class TargetSelectionTests(unittest.TestCase):
    def tearDown(self):
        patch.stopall()

    def test_local_target_uses_plain_http_without_credentials(self):
        client = LocalClient("http://mlflow:5000", environ=CREDENTIALS)
        self.assertEqual((client.target, client.host, client.port, client.prefix), ("local", "mlflow", 5000, ""))
        self.assertIsInstance(client.connection(), http.client.HTTPConnection)
        self.assertNotIsInstance(client.connection(), http.client.HTTPSConnection)
        connection = answer(client, 200, b"{}")
        client.post("experiments/search", {})
        self.assertEqual(connection.url, "/api/2.0/mlflow/experiments/search")
        self.assertNotIn("Authorization", connection.headers)

    def test_dagshub_target_uses_verified_https_with_prefix_and_token(self):
        client = dagshub_client()
        self.assertEqual((client.target, client.host, client.port, client.prefix), ("dagshub", "dagshub.com", 443, PREFIX))
        connection = client.connection()
        self.assertIsInstance(connection, http.client.HTTPSConnection)
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(connection._context.check_hostname)
        fake = answer(client, 200, b'{"experiments": []}')
        client.post("experiments/search", {})
        self.assertEqual(fake.url, PREFIX + "/api/2.0/mlflow/experiments/search")
        expected = "Basic " + base64.b64encode(b"fixture-user:" + TOKEN.encode()).decode()
        self.assertEqual(fake.headers["Authorization"], expected)

    def test_rejected_tracking_uris(self):
        for uri in ("http://dagshub.com" + PREFIX, "https://dagshub.com:8443" + PREFIX,
                    "https://user:secret@dagshub.com" + PREFIX, "https://dagshub.com/SiR1979/repo",
                    "https://dagshub.com" + PREFIX + "/extra", "https://dagshub.com" + PREFIX + "?a=b",
                    "https://dagshub.com.example.org" + PREFIX, "https://example.org" + PREFIX,
                    "https://localhost:5000", "http://example.org:5000", "http://localhost:5000/path"):
            with self.subTest(uri=uri), self.assertRaises(ImportFailure):
                LocalClient(uri, environ=CREDENTIALS)

    def test_dagshub_requires_both_credentials(self):
        for environ in ({}, {"MLFLOW_TRACKING_USERNAME": "fixture-user"}, {"MLFLOW_TRACKING_PASSWORD": TOKEN},
                        {"MLFLOW_TRACKING_USERNAME": "", "MLFLOW_TRACKING_PASSWORD": TOKEN},
                        {"MLFLOW_TRACKING_USERNAME": "a:b", "MLFLOW_TRACKING_PASSWORD": TOKEN}):
            with self.subTest(environ=sorted(environ)), self.assertRaises(ImportFailure) as raised:
                LocalClient(DAGSHUB_URI, environ=environ)
            self.assertNotIn(TOKEN, str(raised.exception))

    def test_token_is_not_exposed_by_client_representation(self):
        client = dagshub_client()
        self.assertNotIn(TOKEN, repr(client))
        self.assertNotIn(TOKEN, str(client))


class AuthenticationAndTransferTests(unittest.TestCase):
    def tearDown(self):
        patch.stopall()

    def test_authentication_failures_name_the_cause_without_the_token(self):
        for status in (401, 403):
            client = dagshub_client()
            answer(client, status, b"ATTENTION")
            with self.subTest(status=status), self.assertRaises(ImportFailure) as raised:
                client.post("experiments/search", {})
            self.assertIn(str(status), str(raised.exception))
            self.assertIn("access token", str(raised.exception))
            self.assertNotIn(TOKEN, str(raised.exception))
            patch.stopall()

    def test_redirects_are_not_followed(self):
        client = dagshub_client()
        answer(client, 302)
        with self.assertRaises(ImportFailure):
            client.post("experiments/search", {})

    def test_upload_sends_bytes_with_token_under_the_prefix(self):
        client = dagshub_client()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.bin"
            path.write_bytes(b"opaque model bytes")
            fake = answer(client, 200, b"{}")
            client.upload(RUN, "pipeline/model.bin", path, hashlib.sha256(b"opaque model bytes").hexdigest())
        self.assertEqual((fake.method, fake.url), ("PUT", PREFIX + "/api/2.0/mlflow-artifacts/artifacts/exp/run/artifacts/pipeline/model.bin"))
        self.assertEqual(fake.sent, b"opaque model bytes")
        self.assertIn("Authorization", fake.headers)

    def test_upload_detects_a_source_hash_mismatch(self):
        client = dagshub_client()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.bin"
            path.write_bytes(b"opaque model bytes")
            answer(client, 200, b"{}")
            with self.assertRaises(ImportFailure):
                client.upload(RUN, "pipeline/model.bin", path, "0" * 64)

    def test_download_returns_the_stored_hash_and_checks_size(self):
        client = dagshub_client()
        fake = answer(client, 200, b"stored bytes")
        self.assertEqual(client.download_hash(RUN, "pipeline/model.bin", 12), hashlib.sha256(b"stored bytes").hexdigest())
        self.assertEqual((fake.method, fake.url), ("GET", PREFIX + "/api/2.0/mlflow-artifacts/artifacts/exp/run/artifacts/pipeline/model.bin"))
        self.assertIn("Authorization", fake.headers)
        for size in (11, 13):
            answer(client, 200, b"stored bytes")
            with self.subTest(size=size), self.assertRaises(ImportFailure):
                client.download_hash(RUN, "pipeline/model.bin", size)


class TrackerVersionTests(unittest.TestCase):
    def tearDown(self):
        patch.stopall()

    def tracker(self, uri):
        with patch.dict("os.environ", CREDENTIALS):
            return PipelineTracker(uri, "unused-context.json")

    def test_local_server_must_be_the_pinned_version(self):
        tracker = self.tracker("http://mlflow:5000")
        answer(tracker.client, 200, b"3.17.0")
        tracker.check_version()
        self.assertEqual((tracker.target, tracker.server_version), ("local", "3.17.0"))
        answer(tracker.client, 200, b"3.5.1")
        with self.assertRaises(TrackingFailure):
            tracker.check_version()

    def test_dagshub_accepts_mlflow_3_and_records_the_version(self):
        tracker = self.tracker(DAGSHUB_URI)
        fake = answer(tracker.client, 200, b"3.5.1")
        tracker.check_version()
        self.assertEqual((tracker.target, tracker.server_version), ("dagshub", "3.5.1"))
        self.assertEqual(fake.url, PREFIX + "/version")
        for version in (b"2.9.2", b"unknown"):
            answer(tracker.client, 200, version)
            with self.subTest(version=version), self.assertRaises(TrackingFailure):
                tracker.check_version()


if __name__ == "__main__":
    unittest.main()
