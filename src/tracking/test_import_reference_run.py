"""One integration phase: import, sequential repeat, and artifact integrity.

The optional preparation fixture is opaque test bytes, not a trained model.
The default mode verifies the selected, hash-bound historical Windows files.
"""

import hashlib
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from .import_reference_run import (
    EXPECTED, EXPERIMENT, HISTORICAL_RUN, ImportFailure, LocalClient,
    argument_parser, import_reference, milliseconds, require, sha256_file,
)


def fixture(directory):
    """Build transport evidence without fitting or loading any estimator."""
    root = Path(directory)
    model = root / "reference_run/model/trained_model.joblib"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"OPAQUE-TRANSFER-FIXTURE\x00" * 100001)
    status = {
        "status": "completed", "started_at_utc": "2026-10-03T19:33:12.381422+00:00",
        "finished_at_utc": "2026-10-03T19:33:18.640003+00:00",
        "run_directory": HISTORICAL_RUN, "model_path": HISTORICAL_RUN + "/model/trained_model.joblib",
        "random_state": None, "approved_for_delivery": False,
    }
    report = {
        "validation_status": "passed", "checked_at_utc": "2026-10-03T19:33:32.426452+00:00",
        "run_directory": HISTORICAL_RUN, "model_sha256": sha256_file(model),
        "metrics": {"test_rows": 16410, "feature_count": 28, "accuracy": 0.7775746496039001,
                    "balanced_accuracy": 0.7350421970573099, "macro_f1": 0.7434617953573757,
                    "example_prediction_code": 1},
        "executed_source_sha256": {"preparation-fixture": "a" * 64},
        "raw_sha256": {"preparation-fixture": "b" * 64},
        "python_version": "preparation-fixture", "resolved_requirements": ["opaque-transfer-fixture"],
        "approved_for_delivery": False, "quality_thresholds_enforced": False,
    }
    (root / "reference_run/run_status.json").write_text(json.dumps(status), encoding="utf-8")
    (root / "validation_report.json").write_text(json.dumps(report), encoding="utf-8")
    return {relative: sha256_file(root / relative) for relative in EXPECTED}


def integration(root, args, expected, experiment):
    root = Path(root)
    # Invalid destinations and changed input bytes fail before any metadata write.
    for uri in ("http://example.org:5000", "http://user:secret@localhost:5000", "http://127.0.0.1:5000/remote"):
        try:
            LocalClient(uri)
        except ImportFailure:
            pass
        else:
            raise ImportFailure("Invalid tracking destination was accepted.")
    wrong_hashes = expected | {"validation_report.json": "0" * 64}
    with patch("src.tracking.import_reference_run.LocalClient", side_effect=AssertionError("Unexpected tracking write")):
        try:
            import_reference(root, args.tracking_uri, args.import_git_head, args.import_worktree_state, args.import_image_id, expected=wrong_hashes, experiment=experiment)
        except ImportFailure:
            pass
        else:
            raise ImportFailure("Changed reference bytes were accepted.")
    first = import_reference(root, args.tracking_uri, args.import_git_head, args.import_worktree_state, args.import_image_id, expected=expected, experiment=experiment)
    second = import_reference(root, args.tracking_uri, args.import_git_head, args.import_worktree_state, args.import_image_id, expected=expected, experiment=experiment)
    require(first["result"] == "imported_verified" and second["result"] == "existing_verified" and first["run_id"] == second["run_id"], "Sequential repeat created or changed a run.")
    report = json.loads((root / "validation_report.json").read_bytes())
    client = LocalClient(args.tracking_uri)
    for name, value in report["metrics"].items():
        history = client.request("GET", "/api/2.0/mlflow/metrics/get-history?" + urlencode({"run_id": first["run_id"], "metric_key": name}))["metrics"]
        require(len(history) == 1 and history[0]["value"] == value and history[0]["timestamp"] == milliseconds(report["checked_at_utc"]), "Metric history or original observation timestamp differs.")
    for relative, digest in expected.items():
        require(sha256_file(root / relative) == digest, "An original reference file changed.")
    first["sequential_repeat"] = "same_run_verified"
    first["artifact_round_trip"] = "all_hashes_match"
    first["historical_metric_timestamps"] = "verified"
    return first


def main():
    parser = argument_parser()
    parser.add_argument("--preparation-fixture", action="store_true")
    args = parser.parse_args()
    if args.preparation_fixture:
        with tempfile.TemporaryDirectory(prefix="tracking-transport-fixture-") as directory:
            expected = fixture(directory)
            result = integration(directory, args, expected, EXPERIMENT + "_preparation_" + uuid.uuid4().hex)
        result["test_scope"] = "opaque_preparation_fixture_not_reference_model"
        print("TRACKING PREPARATION VALIDATION PASSED")
    else:
        result = integration(args.reference_root, args, EXPECTED, EXPERIMENT)
        result["test_scope"] = "selected_historical_reference_files"
        print("TRACKING FUNCTIONAL VALIDATION PASSED")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
