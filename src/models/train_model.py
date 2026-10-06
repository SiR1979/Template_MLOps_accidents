"""Train the reference Random Forest using explicit artifact paths."""

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn import ensemble


def train_model(data_directory, model_path):
    """Train the unchanged reference estimator and create a new model file."""
    data_directory = Path(data_directory)
    model_path = Path(model_path)

    if model_path.exists() or model_path.is_symlink():
        raise FileExistsError(f"Model output already exists: {model_path}")

    X_train = pd.read_csv(data_directory / "X_train.csv")
    y_frame = pd.read_csv(data_directory / "y_train.csv")

    if X_train.empty or y_frame.shape[1] != 1:
        raise ValueError("Training features or target structure are invalid.")
    if len(X_train) != len(y_frame):
        raise ValueError("Training feature and target row counts differ.")

    y_train = np.ravel(y_frame)
    rf_classifier = ensemble.RandomForestClassifier(n_jobs=-1)
    rf_classifier.fit(X_train, y_train)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("xb") as model_file:
        joblib.dump(rf_classifier, model_file)

    return model_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_directory", type=Path)
    parser.add_argument("model_path", type=Path)
    args = parser.parse_args()
    saved_path = train_model(args.data_directory, args.model_path)
    print(f"Model trained and saved: {saved_path}")


if __name__ == "__main__":
    main()
