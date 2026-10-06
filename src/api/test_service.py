"""Check request handling, model binding and the running local API."""

import copy
import hashlib
import json
import os
import platform
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import sklearn
from fastapi.testclient import TestClient
from sklearn.ensemble import RandomForestClassifier

from src.api import service

EXAMPLE = {
    "place": 10, "catu": 3, "sexe": 1, "secu1": 0.0, "year_acc": 2021,
    "victim_age": 60, "catv": 2, "obsm": 1, "motor": 1, "catr": 3,
    "circ": 2, "surf": 1, "situ": 1, "vma": 50, "jour": 7, "mois": 12,
    "lum": 5, "dep": 77, "com": 77317, "agg_": 2, "int": 1, "atm": 0,
    "col": 6, "lat": 48.60, "long": 2.89, "hour": 17, "nb_victim": 2,
    "nb_vehicules": 1,
}


def estimator_stub():
    # This test double is never fitted or saved as a model artifact.
    model = RandomForestClassifier(n_jobs=-1)
    model.feature_names_in_ = np.array(service.FEATURES)
    model.n_features_in_ = 28
    model.classes_ = np.array([0, 1])
    model.predict = Mock(return_value=np.array([1]))
    return model


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.model = estimator_stub()
        loader = patch.object(service, "load_checked_model", return_value=(self.model, "a" * 64))
        loader.start()
        self.addCleanup(loader.stop)
        self.client = TestClient(service.create_app("unused", "a" * 64))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_valid_and_reordered_features(self):
        for features in (EXAMPLE, dict(reversed(list(EXAMPLE.items())))):
            response = self.client.post("/predict", json={"features": features})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {
                "prediction_code": 1, "model_sha256": "a" * 64,
                "contract_version": service.CONTRACT_VERSION,
            })
            frame = self.model.predict.call_args.args[0]
            self.assertEqual(tuple(frame.columns), service.FEATURES)
            self.assertEqual(frame.iloc[0].tolist(), [float(EXAMPLE[k]) for k in service.FEATURES])

    def test_invalid_structure_and_types(self):
        invalid = [[], {}, {"features": []}, {"features": EXAMPLE, "extra": 1}]
        missing = dict(EXAMPLE)
        missing.pop("place")
        invalid.extend([{"features": missing}, {"features": dict(EXAMPLE, unknown=1)}])
        for value in (None, True, "1", [], {}, 1.5, 10**100):
            invalid.append({"features": dict(EXAMPLE, place=value)})
        for payload in invalid:
            with self.subTest(payload=repr(payload)[:60]):
                self.assertEqual(self.client.post("/predict", json=payload).status_code, 422)
        self.model.predict.assert_not_called()

    def test_json_errors_and_duplicates(self):
        valid = json.dumps({"features": EXAMPLE})
        cases = [
            ("{", 400), (b"\xff", 400),
            (valid.replace('"place": 10', '"place": 10, "place": 10'), 422),
            ('{"features": {}, "features": {}}', 422),
            (valid.replace('"place": 10', '"place": NaN'), 400),
            (valid.replace('"place": 10', '"place": 1e400'), 422),
        ]
        for body, code in cases:
            with self.subTest(code=code):
                response = self.client.post("/predict", content=body, headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, code)
        self.model.predict.assert_not_called()

    def test_media_type_and_size(self):
        self.assertEqual(self.client.post("/predict", content="{}").status_code, 415)
        response = self.client.post("/predict", content=" " * (service.MAX_BODY_BYTES + 1),
                                    headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)
        self.model.predict.assert_not_called()

    def test_health(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").json()["model_sha256"], "a" * 64)

    def test_failed_model_is_unavailable(self):
        with patch.object(service, "load_checked_model", side_effect=ValueError("invalid")):
            with TestClient(service.create_app("unused", "b" * 64)) as client:
                self.assertEqual(client.get("/health/live").status_code, 200)
                self.assertEqual(client.get("/health/ready").status_code, 503)
                self.assertEqual(client.post("/predict", json={"features": EXAMPLE}).status_code, 503)


class ModelBindingTests(unittest.TestCase):
    def test_identity_before_deserialization_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test-bytes.bin"
            path.write_bytes(b"non-model test bytes")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch.object(service.joblib, "load") as loader:
                with self.assertRaises(ValueError):
                    service.load_checked_model(str(path), "0" * 64)
                loader.assert_not_called()
                with self.assertRaises(FileNotFoundError):
                    service.load_checked_model(str(path) + ".missing", digest)
                loader.assert_not_called()
                model = estimator_stub()
                loader.return_value = model
                self.assertEqual(service.load_checked_model(str(path), digest)[1], digest)
                for attribute, value in (
                    ("feature_names_in_", np.array(service.FEATURES[::-1])),
                    ("n_features_in_", 27), ("classes_", np.array([1, 2])),
                ):
                    altered = copy.copy(model)
                    setattr(altered, attribute, value)
                    loader.return_value = altered
                    with self.assertRaises(ValueError):
                        service.load_checked_model(str(path), digest)
                loader.return_value = {}
                with self.assertRaises(ValueError):
                    service.load_checked_model(str(path), digest)


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "Actual model/container required")
class LiveArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, cls.digest = service.load_checked_model(os.environ["MODEL_PATH"], os.environ["MODEL_SHA256"])

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request("http://127.0.0.1:8000" + path, data=data,
                                         headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_runtime_and_live_model_prediction(self):
        self.assertEqual(sklearn.__version__, "1.7.2")
        self.assertEqual(self.model.random_state, None)
        status, ready = self.request("/health/ready")
        self.assertEqual(status, 200)
        self.assertEqual(ready["model_sha256"], self.digest)
        expected = int(self.model.predict(service.parse_features(json.dumps({"features": EXAMPLE}).encode()))[0])
        for features in (EXAMPLE, dict(reversed(list(EXAMPLE.items())))):
            status, result = self.request("/predict", {"features": features})
            self.assertEqual(status, 200)
            self.assertEqual(result, {"prediction_code": expected, "model_sha256": self.digest,
                                      "contract_version": service.CONTRACT_VERSION})
        print(json.dumps({"python": platform.python_version(), "sklearn": sklearn.__version__,
                          "model_sha256": self.digest, "example_prediction_code": expected}))

    def test_live_invalid_input(self):
        status, _ = self.request("/predict", {"features": dict(EXAMPLE, place=True)})
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
