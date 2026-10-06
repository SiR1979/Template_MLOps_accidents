"""Run reference preprocessing and training in a new, isolated directory.

The inherited target mapping and severity-based row selection are preserved.
The estimator has no random seed; repeated fits may produce different results.
A completed run is a training result, not approval for model delivery.
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from data.make_dataset import RAW_FILENAMES, process_data
from models.train_model import train_model


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run_pipeline(raw_directory, run_directory):
    raw_directory = Path(raw_directory).resolve(strict=True)
    run_directory = Path(run_directory).resolve()
    raw_paths = [raw_directory / name for name in RAW_FILENAMES]

    for path in raw_paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Required input is missing or empty: {path}")

    if run_directory == raw_directory or raw_directory in run_directory.parents:
        raise ValueError("The run directory must be outside the raw directory.")

    # Claim a new directory; never resume or overwrite an existing run.
    run_directory.mkdir(parents=True, exist_ok=False)
    status_path = run_directory / "run_status.json"
    record = {
        "status": "running",
        "started_at_utc": utc_now(),
        "raw_directory": str(raw_directory),
        "run_directory": str(run_directory),
        "random_state": None,
        "approved_for_delivery": False,
    }

    def write_status():
        status_path.write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )

    try:
        write_status()
        processed_directory = run_directory / "preprocessed"
        process_data(*raw_paths, processed_directory)
        model_path = train_model(
            processed_directory,
            run_directory / "model" / "trained_model.joblib",
        )
        record.update(
            status="completed",
            finished_at_utc=utc_now(),
            model_path=str(model_path),
        )
        write_status()
    except Exception as error:
        record.update(
            status="failed",
            finished_at_utc=utc_now(),
            error_type=type(error).__name__,
            error=str(error),
        )
        try:
            write_status()
        except OSError:
            logging.exception("Could not persist the failed run status.")
        raise

    return run_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()

    try:
        result = run_pipeline(args.raw_dir, args.run_dir)
    except Exception:
        logging.exception("Reference pipeline failed.")
        return 1

    print(f"Reference pipeline completed: {result}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    raise SystemExit(main())
