"""Import an evidenced historical run through a local MLflow artifact proxy.

Model files are opaque bytes. This module never loads a model or trains one.
"""

import argparse
import hashlib
import http.client
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit


EXPERIMENT = "car_accident_reference"
HISTORICAL_RUN = "/app/data/runs/validation_20261003T193310Z_56c49087/reference_run"
EXPECTED = {
    "validation_report.json": "d1d3200d428701c96f715f99fcd4912c92bb4e528023f7fe7ff5475aedfdcf79",
    "reference_run/run_status.json": "bfd69f4edf47b66ac5b8b15196f1d545182d70b10e8d92988dcc77b09438040e",
    "reference_run/model/trained_model.joblib": "5e8775b69782640c0ee244bfa7c427928ece0f01be877688102313a8bc7a1a2b",
}
ARTIFACT_NAMES = {
    "validation_report.json": "reference/validation_report.json",
    "reference_run/run_status.json": "reference/run_status.json",
    "reference_run/model/trained_model.joblib": "reference/trained_model.joblib",
}
METRICS = {"test_rows", "feature_count", "accuracy", "balanced_accuracy", "macro_f1", "example_prediction_code"}


class ImportFailure(RuntimeError):
    """An import cannot be completed without changing its evidence contract."""


def require(condition, message):
    if not condition:
        raise ImportFailure(message)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_json(content):
    def unique_pairs(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "Duplicate JSON key.")
            value[key] = item
        return value

    def reject_constant(_value):
        raise ImportFailure("Non-finite JSON constant.")

    return json.loads(content, object_pairs_hook=unique_pairs, parse_constant=reject_constant)


def milliseconds(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.utcoffset() is not None, "Historical timestamp lacks a timezone.")
    return int(parsed.timestamp() * 1000)


def validate_sources(root, expected):
    root = Path(root)
    require(set(expected) == set(EXPECTED), "Unexpected source selection.")
    paths = {}
    for relative, digest in expected.items():
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "Invalid expected hash.")
        path = root / relative
        require(path.is_file() and not path.is_symlink(), "Required reference file missing or linked.")
        require(sha256_file(path) == digest, f"Reference bytes differ: {relative}")
        paths[relative] = path
    require(paths["validation_report.json"].stat().st_size <= 1024 * 1024, "Report is too large.")
    require(paths["reference_run/run_status.json"].stat().st_size <= 1024 * 1024, "Status is too large.")
    report = decode_json(paths["validation_report.json"].read_bytes())
    status = decode_json(paths["reference_run/run_status.json"].read_bytes())
    require(report["validation_status"] == "passed" and status["status"] == "completed", "Reference run is not completed and validated.")
    require(report["run_directory"] == status["run_directory"] == HISTORICAL_RUN, "Historical run selection differs.")
    require(status["model_path"] == HISTORICAL_RUN + "/model/trained_model.joblib", "Historical model path differs.")
    require(report["model_sha256"] == expected["reference_run/model/trained_model.joblib"], "Report/model identity differs.")
    require(status["random_state"] is None, "Historical forest seed differs.")
    require(report["approved_for_delivery"] is False and status["approved_for_delivery"] is False, "Historical delivery flag differs.")
    require(report["quality_thresholds_enforced"] is False, "Historical evaluation gate differs.")
    start = milliseconds(status["started_at_utc"])
    end = milliseconds(status["finished_at_utc"])
    checked = milliseconds(report["checked_at_utc"])
    require(start <= end <= checked, "Historical timestamp order differs.")
    metrics = report["metrics"]
    require(set(metrics) == METRICS, "Unexpected metric schema.")
    for name, value in metrics.items():
        require(type(value) in (int, float) and math.isfinite(value), f"Invalid metric: {name}")
    require(metrics["feature_count"] == 28 and metrics["test_rows"] > 0, "Historical feature or row count differs.")
    require(metrics["example_prediction_code"] in (0, 1), "Historical class code differs.")
    require(all(0 <= metrics[name] <= 1 for name in ("accuracy", "balanced_accuracy", "macro_f1")), "Metric outside its range.")
    for field in ("executed_source_sha256", "raw_sha256"):
        require(isinstance(report[field], dict) and report[field], "Missing historical hash observations.")
        require(all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in report[field].values()), "Invalid historical hash observation.")
    require(isinstance(report["python_version"], str) and isinstance(report["resolved_requirements"], list), "Missing historical runtime observations.")
    return paths, report, status, start, end, checked


class LocalClient:
    """Use direct local HTTP, without credentials, proxies, or redirects."""

    def __init__(self, uri):
        parsed = urlsplit(uri)
        require(parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "mlflow"), "A local HTTP tracking URI is required.")
        require(parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment and parsed.path in ("", "/"), "Unexpected tracking URI components.")
        self.host = parsed.hostname
        self.port = parsed.port or 5000

    def connection(self):
        return http.client.HTTPConnection(self.host, self.port, timeout=60)

    def request(self, method, route, payload=None):
        data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        connection = self.connection()
        try:
            connection.request(method, route, body=data, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            require(response.status == 200, f"MLflow {method} returned HTTP {response.status}.")
            content = response.read(1024 * 1024 + 1)
            require(len(content) <= 1024 * 1024, "MLflow JSON response is too large.")
            return decode_json(content) if content else {}
        finally:
            connection.close()

    def post(self, route, payload):
        return self.request("POST", "/api/2.0/mlflow/" + route, payload)

    def run(self, run_id):
        return self.request("GET", "/api/2.0/mlflow/runs/get?" + urlencode({"run_id": run_id}))["run"]

    @staticmethod
    def artifact_route(run, name):
        parsed = urlsplit(run["info"]["artifact_uri"])
        require(parsed.scheme == "mlflow-artifacts" and not parsed.netloc and not parsed.query and not parsed.fragment, "Artifacts must use this server's local proxy.")
        parts = parsed.path.strip("/").split("/") + name.split("/")
        require(all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) and part not in (".", "..") for part in parts), "Unsafe artifact path.")
        return "/api/2.0/mlflow-artifacts/artifacts/" + "/".join(quote(part, safe="") for part in parts)

    def upload(self, run, name, path, expected_hash):
        connection = self.connection()
        digest = hashlib.sha256()
        size = Path(path).stat().st_size
        count = 0
        try:
            connection.putrequest("PUT", self.artifact_route(run, name))
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Content-Length", str(size))
            connection.endheaders()
            with Path(path).open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    count += len(chunk)
                    connection.send(chunk)
            response = connection.getresponse()
            require(response.status == 200, f"Artifact upload returned HTTP {response.status}.")
            response.read(65536)
            require(count == size and digest.hexdigest() == expected_hash, "Source changed during upload.")
        finally:
            connection.close()

    def download_hash(self, run, name, expected_size):
        connection = self.connection()
        digest = hashlib.sha256()
        count = 0
        try:
            connection.request("GET", self.artifact_route(run, name))
            response = connection.getresponse()
            require(response.status == 200, f"Artifact download returned HTTP {response.status}.")
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                require(count <= expected_size, "Stored artifact is larger than its source.")
                digest.update(chunk)
            require(count == expected_size, "Stored artifact size differs.")
            return digest.hexdigest()
        finally:
            connection.close()


def tags_dict(run):
    return {item["key"]: item["value"] for item in run.get("data", {}).get("tags", [])}


def import_reference(root, uri, import_git_head, import_worktree_state, import_image_id, *, expected=None, experiment=EXPERIMENT):
    """Import once; verify a finished sequential repeat without writing to it."""
    expected = dict(EXPECTED if expected is None else expected)
    paths, report, status, start, end, checked = validate_sources(root, expected)
    require(re.fullmatch(r"[0-9a-f]{40}", import_git_head) is not None, "Invalid import baseline revision.")
    require(import_worktree_state == "dirty", "This installer records newly written, uncommitted tracking code.")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", import_image_id) is not None, "Invalid import image identity.")
    require(re.fullmatch(r"[A-Za-z0-9_-]+", experiment) is not None, "Invalid experiment name.")
    client = LocalClient(uri)
    import_id = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    experiments = client.post("experiments/search", {"filter": f"name = '{experiment}'", "view_type": 3, "max_results": 2}).get("experiments", [])
    require(len(experiments) <= 1, "Experiment name is ambiguous.")
    if experiments:
        require(experiments[0]["lifecycle_stage"] == "active", "Existing experiment is deleted; it was preserved.")
        experiment_id = experiments[0]["experiment_id"]
    else:
        experiment_id = client.post("experiments/create", {"name": experiment})["experiment_id"]
    filter_string = f"tags.reference_import_id = '{import_id}'"
    runs = client.post("runs/search", {"experiment_ids": [experiment_id], "filter": filter_string, "run_view_type": 3, "max_results": 2}).get("runs", [])
    require(len(runs) <= 1, "Duplicate import identity; existing runs were preserved.")
    required_tags = {
        "reference_import_id": import_id,
        "reference_model_sha256": report["model_sha256"],
        "reference_report_sha256": expected["validation_report.json"],
        "reference_status_sha256": expected["reference_run/run_status.json"],
        "original_training_git_revision": "unknown",
        "original_training_image_id": "unknown",
        "approved_for_delivery": "false",
        "quality_thresholds_enforced": "false",
        "tracking_scope": "historical_reference_import",
        "original_started_at_utc": status["started_at_utc"],
        "original_finished_at_utc": status["finished_at_utc"],
        "original_validation_checked_at_utc": report["checked_at_utc"],
    }
    params = {"forest_n_jobs": "-1", "forest_random_state": "None", "split_random_state": "42", "feature_count": "28", "target_mapping": "[1,2,3,4] -> [1,1,1,0]"}

    def verify(run):
        info = run["info"]
        require(info["lifecycle_stage"] == "active" and info["status"] == "FINISHED", "Existing import is incomplete or deleted; it was preserved.")
        require(info["start_time"] == start and info["end_time"] == end, "Stored historical timestamps differ.")
        stored_tags = tags_dict(run)
        require(all(stored_tags.get(key) == value for key, value in required_tags.items()), "Stored provenance tags differ.")
        stored_params = {item["key"]: item["value"] for item in run["data"].get("params", [])}
        require(all(stored_params.get(key) == value for key, value in params.items()), "Stored reference parameters differ.")
        stored_metrics = {item["key"]: item["value"] for item in run["data"].get("metrics", [])}
        require(stored_metrics == report["metrics"], "Stored reference metrics differ.")
        for relative, path in paths.items():
            require(client.download_hash(run, ARTIFACT_NAMES[relative], path.stat().st_size) == expected[relative], "Stored reference artifact hash differs.")
        require(re.fullmatch(r"[0-9a-f]{64}", stored_tags.get("import_provenance_sha256", "")) is not None, "Missing import provenance identity.")
        require(client.download_hash(run, "reference/import_provenance.json", int(stored_tags["import_provenance_bytes"])) == stored_tags["import_provenance_sha256"], "Stored import provenance differs.")

    if runs:
        verify(runs[0])
        return {"result": "existing_verified", "run_id": runs[0]["info"]["run_id"], "experiment_id": experiment_id, "model_sha256": report["model_sha256"]}

    import_time = datetime.now(timezone.utc).isoformat()
    provenance = {
        "scope": "historical_reference_import",
        "imported_at_utc": import_time,
        "reference_file_sha256": expected,
        "historical_run_directory": HISTORICAL_RUN,
        "original_training_git_revision": "unknown",
        "original_training_image_id": "unknown",
        "original_source_hashes_and_runtime": "See the unchanged validation_report.json; these are historical observations.",
        "import_baseline_git_head": import_git_head,
        "import_worktree_state": import_worktree_state,
        "import_container_image_id": import_image_id,
        "importer_source_sha256": sha256_file(__file__),
        "approved_for_delivery": False,
        "limitations": ["No retraining occurred.", "Severity-based row selection limits prediction before intervention.", "Class-code domain labels remain unconfirmed.", "The validation metrics are observations, not enforced quality thresholds."],
    }
    provenance_bytes = (json.dumps(provenance, indent=2, allow_nan=False) + "\n").encode()
    provenance_hash = hashlib.sha256(provenance_bytes).hexdigest()
    all_tags = required_tags | {
        "imported_at_utc": import_time,
        "import_baseline_git_head": import_git_head,
        "import_worktree_state": import_worktree_state,
        "import_container_image_id": import_image_id,
        "importer_source_sha256": provenance["importer_source_sha256"],
        "import_provenance_sha256": provenance_hash,
        "import_provenance_bytes": str(len(provenance_bytes)),
    }
    run = client.post("runs/create", {"experiment_id": experiment_id, "run_name": "2021-reference-20261003", "start_time": start, "tags": [{"key": key, "value": value} for key, value in all_tags.items()]})["run"]
    run_id = run["info"]["run_id"]
    try:
        client.post("runs/log-batch", {"run_id": run_id, "params": [{"key": key, "value": value} for key, value in params.items()], "metrics": [{"key": key, "value": value, "timestamp": checked, "step": 0} for key, value in report["metrics"].items()]})
        for relative, path in paths.items():
            client.upload(run, ARTIFACT_NAMES[relative], path, expected[relative])
        # The temporary file contains new import metadata, never rewritten history.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="reference-import-") as directory:
            provenance_path = Path(directory) / "import_provenance.json"
            provenance_path.write_bytes(provenance_bytes)
            client.upload(run, "reference/import_provenance.json", provenance_path, provenance_hash)
        client.post("runs/update", {"run_id": run_id, "status": "FINISHED", "end_time": end})
        verify(client.run(run_id))
    except Exception:
        try:
            client.post("runs/update", {"run_id": run_id, "status": "FAILED", "end_time": end})
        except Exception:
            pass
        raise
    return {"result": "imported_verified", "run_id": run_id, "experiment_id": experiment_id, "model_sha256": report["model_sha256"]}


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", default="/imports")
    parser.add_argument("--tracking-uri", default="http://mlflow:5000")
    parser.add_argument("--import-git-head", required=True)
    parser.add_argument("--import-worktree-state", choices=["dirty"], default="dirty")
    parser.add_argument("--import-image-id", required=True)
    return parser


def main():
    args = argument_parser().parse_args()
    try:
        result = import_reference(args.reference_root, args.tracking_uri, args.import_git_head, args.import_worktree_state, args.import_image_id)
        print(json.dumps(result, sort_keys=True))
    except (ImportFailure, OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as error:
        raise SystemExit(f"Reference import stopped ({type(error).__name__}). Preserve tracking storage and inspect the failed phase.") from None


if __name__ == "__main__":
    main()
