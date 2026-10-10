"""Verify technical pipeline checks with isolated files and unfitted test doubles."""

import ast
import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

import run_pipeline as pipeline


ARTIFACT_BYTES = b"Opaque test artifact; never deserialize or serve these bytes."


def model_double():
    model = RandomForestClassifier(n_jobs=-1)
    model.feature_names_in_ = np.array(pipeline.FEATURES)
    model.n_features_in_ = 28
    model.classes_ = np.array([0, 1])
    model.fit = Mock(side_effect=AssertionError("Real training is forbidden in this suite."))
    model.predict = Mock(side_effect=AssertionError("Inference is not technical validation."))
    model.score = Mock(side_effect=AssertionError("Evaluation must remain separate."))
    return model


class TechnicalPipelineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pipeline-technical-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        for name in pipeline.RAW_FILENAMES:
            (self.raw / name).write_bytes(b"Opaque input fixture; preprocessing is mocked.\n")
        self.run = self.root / "new_run"
        self.reset_frames()
        self.model = model_double()
        self.process = self.start_patch("process_data", side_effect=self.prepare)
        self.train = self.start_patch("train_model", side_effect=self.produce_artifact)
        loader = patch.object(pipeline.joblib, "load", return_value=self.model)
        self.loader = loader.start()
        self.addCleanup(loader.stop)
        for method in ("fit", "predict", "score"):
            guard = patch.object(RandomForestClassifier, method,
                                 side_effect=AssertionError(f"Unexpected {method} call."))
            guard.start()
            self.addCleanup(guard.stop)

    def start_patch(self, name, **kwargs):
        replacement = patch.object(pipeline, name, **kwargs)
        result = replacement.start()
        self.addCleanup(replacement.stop)
        return result

    def reset_frames(self):
        self.frames = {}
        for partition in ("train", "test"):
            self.frames[f"X_{partition}"] = pd.DataFrame(
                np.ones((2, 28)), columns=pipeline.FEATURES,
            )
            self.frames[f"y_{partition}"] = pd.DataFrame({"grav": [0, 1]})

    def prepare(self, *arguments):
        directory = arguments[-1]
        directory.mkdir()
        for name, frame in self.frames.items():
            frame.to_csv(directory / f"{name}.csv", index=False)

    def produce_artifact(self, directory, destination):
        self.assertEqual(directory, destination.parent.parent / "preprocessed")
        destination.parent.mkdir()
        with destination.open("xb") as stream:
            stream.write(ARTIFACT_BYTES)
        return destination

    def read_status(self, run=None):
        return json.loads(((run or self.run) / "run_status.json").read_text())

    def assert_failed(self, run=None):
        status = self.read_status(run)
        self.assertEqual(status["status"], "failed")
        self.assertIs(status["approved_for_delivery"], False)
        self.assertIn("error_type", status)
        self.assertFalse(((run or self.run) / "validation_report.json").exists())

    def test_success_records_technical_identity_without_evaluation(self):
        self.assertEqual(pipeline.run_pipeline(self.raw, self.run), self.run)
        status = self.read_status()
        report_path = self.run / "validation_report.json"
        report = json.loads(report_path.read_text())
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["validation_report_path"], str(report_path))
        self.assertIs(status["approved_for_delivery"], False)
        self.assertIs(status["random_state"], None)
        self.assertEqual(report["scope"], "technical_data_and_model_validation")
        self.assertEqual(report["validation_status"], "passed")
        self.assertEqual(report["run_id"], self.run.name)
        self.assertEqual(report["run_directory"], str(self.run))
        self.assertEqual(report["model_path"], str(self.run / "model/trained_model.joblib"))
        self.assertEqual(report["model_sha256"], hashlib.sha256(ARTIFACT_BYTES).hexdigest())
        self.assertIs(report["approved_for_delivery"], False)
        self.assertNotIn("metrics", report)
        self.assertNotIn("quality_thresholds", report)
        self.assertNotIn("original_training_git_revision", report)
        for partition in ("train", "test"):
            observed = report["data_validation"]["partitions"][partition]
            self.assertEqual(observed["row_count"], 2)
            self.assertEqual(observed["feature_count"], 28)
            self.assertEqual(set(observed["checks"].values()), {"passed"})
        self.assertEqual(set(report["model_validation"]["checks"].values()), {"passed"})
        timestamps = [status["started_at_utc"],
                      report["data_validation"]["checked_at_utc"],
                      report["model_validation"]["checked_at_utc"],
                      report["checked_at_utc"], status["finished_at_utc"]]
        parsed = [datetime.fromisoformat(value) for value in timestamps]
        self.assertTrue(all(value.utcoffset().total_seconds() == 0 for value in parsed))
        self.assertEqual(parsed, sorted(parsed))
        self.process.assert_called_once()
        self.train.assert_called_once()
        self.loader.assert_called_once()
        self.model.fit.assert_not_called()
        self.model.predict.assert_not_called()
        self.model.score.assert_not_called()

    def test_feature_contract_matches_api_without_importing_api(self):
        source = Path(__file__).parent / "api/service.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        constants = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in ("FEATURES", "CONTRACT_VERSION")
        }
        self.assertEqual(pipeline.FEATURES, constants["FEATURES"])
        self.assertEqual(pipeline.CONTRACT_VERSION, constants["CONTRACT_VERSION"])

    def test_invalid_prepared_partitions_stop_before_training(self):
        cases = ("empty_features", "empty_target", "row_mismatch", "missing_feature",
                 "extra_feature", "reordered_features", "text_feature", "nan_feature",
                 "infinite_feature", "invalid_target", "missing_target", "text_target",
                 "multiple_targets")
        for partition in ("train", "test"):
            for case in cases:
                with self.subTest(partition=partition, case=case):
                    self.reset_frames()
                    features = self.frames[f"X_{partition}"]
                    targets = self.frames[f"y_{partition}"]
                    if case == "empty_features":
                        features = features.iloc[:0]
                    elif case == "empty_target":
                        targets = targets.iloc[:0]
                    elif case == "row_mismatch":
                        targets = targets.iloc[:1]
                    elif case == "missing_feature":
                        features = features.drop(columns=pipeline.FEATURES[-1])
                    elif case == "extra_feature":
                        features = features.assign(unexpected=1)
                    elif case == "reordered_features":
                        features = features[list(reversed(pipeline.FEATURES))]
                    elif case == "text_feature":
                        features[pipeline.FEATURES[0]] = ["invalid", "invalid"]
                    elif case == "nan_feature":
                        features.iloc[0, 0] = np.nan
                    elif case == "infinite_feature":
                        features.iloc[0, 0] = np.inf
                    elif case == "invalid_target":
                        targets.iloc[0, 0] = 2
                    elif case == "missing_target":
                        targets = pd.DataFrame({"grav": [np.nan, 1]})
                    elif case == "text_target":
                        targets = pd.DataFrame({"grav": ["zero", "one"]})
                    elif case == "multiple_targets":
                        targets = targets.assign(unexpected=0)
                    self.frames[f"X_{partition}"] = features
                    self.frames[f"y_{partition}"] = targets
                    run = self.root / f"{partition}_{case}"
                    self.train.reset_mock()
                    self.loader.reset_mock()
                    with self.assertRaises(ValueError):
                        pipeline.run_pipeline(self.raw, run)
                    self.assert_failed(run)
                    self.train.assert_not_called()
                    self.loader.assert_not_called()

    def test_invalid_model_contracts_stop_completion(self):
        cases = ("type", "feature_order", "feature_count", "missing_features",
                 "single_class", "wrong_codes", "class_order")
        for case in cases:
            with self.subTest(case=case):
                model = model_double()
                if case == "type":
                    model = object()
                elif case == "feature_order":
                    model.feature_names_in_ = np.array(list(reversed(pipeline.FEATURES)))
                elif case == "feature_count":
                    model.n_features_in_ = 27
                elif case == "missing_features":
                    del model.feature_names_in_
                elif case == "single_class":
                    model.classes_ = np.array([0])
                elif case == "wrong_codes":
                    model.classes_ = np.array([0, 2])
                elif case == "class_order":
                    model.classes_ = np.array([1, 0])
                self.loader.return_value = model
                self.train.reset_mock()
                self.loader.reset_mock()
                run = self.root / f"model_{case}"
                with self.assertRaises(ValueError):
                    pipeline.run_pipeline(self.raw, run)
                self.assert_failed(run)
                self.train.assert_called_once()
                self.loader.assert_called_once()

    def test_preprocessing_failure_preserves_error_handling(self):
        self.process.side_effect = ValueError("Test preprocessing failure.")
        with self.assertRaises(ValueError):
            pipeline.run_pipeline(self.raw, self.run)
        self.assert_failed()
        self.train.assert_not_called()
        self.loader.assert_not_called()

    def test_training_failure_preserves_error_handling(self):
        self.train.side_effect = RuntimeError("Test training failure.")
        with self.assertRaises(RuntimeError):
            pipeline.run_pipeline(self.raw, self.run)
        self.assert_failed()
        self.loader.assert_not_called()

    def test_model_loading_failure_preserves_produced_bytes(self):
        self.loader.side_effect = ValueError("Test model loading failure.")
        with self.assertRaises(ValueError):
            pipeline.run_pipeline(self.raw, self.run)
        self.assert_failed()
        self.assertEqual((self.run / "model/trained_model.joblib").read_bytes(), ARTIFACT_BYTES)

    def test_report_write_failure_prevents_completion(self):
        original_open = Path.open

        def fail_report(path, *args, **kwargs):
            if path == self.run / "validation_report.json" and args and args[0] == "x":
                raise OSError("Test technical report write failure.")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", fail_report), self.assertRaises(OSError):
            pipeline.run_pipeline(self.raw, self.run)
        self.assert_failed()

    def test_existing_report_is_never_overwritten(self):
        def produce_with_existing_report(directory, destination):
            result = self.produce_artifact(directory, destination)
            (self.run / "validation_report.json").write_bytes(b"Preserved existing report.")
            return result

        self.train.side_effect = produce_with_existing_report
        with self.assertRaises(FileExistsError):
            pipeline.run_pipeline(self.raw, self.run)
        self.assertEqual(self.read_status()["status"], "failed")
        self.assertEqual((self.run / "validation_report.json").read_bytes(), b"Preserved existing report.")

    def test_existing_run_is_never_overwritten(self):
        self.run.mkdir()
        sentinel = self.run / "run_status.json"
        sentinel.write_bytes(b"Preserved existing status.")
        with self.assertRaises(FileExistsError):
            pipeline.run_pipeline(self.raw, self.run)
        self.assertEqual(sentinel.read_bytes(), b"Preserved existing status.")
        self.process.assert_not_called()
        self.train.assert_not_called()
        self.loader.assert_not_called()

    def test_cli_success_and_failure_exit_codes_are_preserved(self):
        arguments = ["run_pipeline.py", "--raw-dir", str(self.raw), "--run-dir", str(self.run)]
        with patch("sys.argv", arguments), patch.object(pipeline, "run_pipeline", return_value=self.run), patch("builtins.print"):
            self.assertEqual(pipeline.main(), 0)
        with patch("sys.argv", arguments), patch.object(pipeline, "run_pipeline", side_effect=ValueError("Test failure.")), self.assertLogs(level="ERROR"):
            self.assertEqual(pipeline.main(), 1)


if __name__ == "__main__":
    unittest.main()
