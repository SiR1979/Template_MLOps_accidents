"""Serve one explicitly selected reference model for local demonstrations."""

import hashlib
import json
import logging
import math
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from sklearn.ensemble import RandomForestClassifier
from starlette.concurrency import run_in_threadpool

CONTRACT_VERSION = "prepared-features-v1"
FEATURES = (
    "place", "catu", "sexe", "secu1", "year_acc", "victim_age", "catv",
    "obsm", "motor", "catr", "circ", "surf", "situ", "vma", "jour", "mois",
    "lum", "dep", "com", "agg_", "int", "atm", "col", "lat", "long", "hour",
    "nb_victim", "nb_vehicules",
)
MAX_BODY_BYTES = 16384
FLOAT32_MAX = float(np.finfo(np.float32).max)
LOGGER = logging.getLogger(__name__)


class DuplicateKey(ValueError):
    """Signal duplicate JSON object keys."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey("Duplicate JSON key.")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("Nonstandard JSON number.")


def parse_features(body):
    try:
        payload = json.loads(
            body.decode("utf-8"), object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except DuplicateKey:
        raise HTTPException(422, "Duplicate JSON keys are not allowed.") from None
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(400, "Invalid UTF-8 JSON.") from None
    if type(payload) is not dict or set(payload) != {"features"}:
        raise HTTPException(422, "Exactly one top-level features object is required.")
    features = payload["features"]
    if type(features) is not dict or set(features) != set(FEATURES):
        raise HTTPException(422, "Exactly the 28 documented features are required.")
    ordered = []
    for name in FEATURES:
        value = features[name]
        if type(value) not in (int, float):
            raise HTTPException(422, f"A JSON number is required for {name}.")
        try:
            value = float(value)
        except (OverflowError, ValueError):
            raise HTTPException(422, f"Numeric value is not supported for {name}.") from None
        if not math.isfinite(value) or abs(value) > FLOAT32_MAX:
            raise HTTPException(422, f"Finite float32-compatible value required for {name}.")
        if name not in ("lat", "long") and not value.is_integer():
            raise HTTPException(422, f"An integral value is required for {name}.")
        ordered.append(value)
    return pd.DataFrame([ordered], columns=FEATURES)


def load_checked_model(path, expected_hash):
    if not path or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash or ""):
        raise ValueError("Explicit model path and SHA-256 are required.")
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected_hash.lower():
            raise ValueError("Model identity mismatch.")
        stream.seek(0)
        model = joblib.load(stream)
    if not isinstance(model, RandomForestClassifier):
        raise ValueError("Unexpected estimator type.")
    if tuple(model.feature_names_in_) != FEATURES or model.n_features_in_ != 28:
        raise ValueError("Model feature contract mismatch.")
    if list(model.classes_) != [0, 1]:
        raise ValueError("Unexpected model class codes.")
    return model, digest


def create_app(model_path=None, model_sha256=None):
    path = model_path if model_path is not None else os.getenv("MODEL_PATH", "")
    expected = model_sha256 if model_sha256 is not None else os.getenv("MODEL_SHA256", "")

    @asynccontextmanager
    async def lifespan(app):
        app.state.model = None
        app.state.model_sha256 = None
        app.state.lock = Lock()
        try:
            app.state.model, app.state.model_sha256 = load_checked_model(path, expected)
        except Exception as error:
            # Do not log input records, credential values or filesystem details.
            LOGGER.error("Model initialization rejected (%s).", type(error).__name__)
        yield
        app.state.model = None

    app = FastAPI(title="Road Accident Local API", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        if app.state.model is None:
            raise HTTPException(503, "Model unavailable.")
        return {"status": "ready", "model_sha256": app.state.model_sha256,
                "contract_version": CONTRACT_VERSION}

    def predict(frame):
        with app.state.lock:
            prediction = app.state.model.predict(frame)
        if len(prediction) != 1 or prediction[0] not in (0, 1):
            raise RuntimeError("Unexpected prediction result.")
        return int(prediction[0])

    @app.post("/predict")
    async def predict_endpoint(request: Request):
        if app.state.model is None:
            raise HTTPException(503, "Model unavailable.")
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise HTTPException(415, "Content-Type application/json is required.")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413, "Request body exceeds 16384 bytes.")
        frame = parse_features(bytes(body))
        try:
            code = await run_in_threadpool(predict, frame)
        except Exception as error:
            LOGGER.error("Prediction failed (%s).", type(error).__name__)
            raise HTTPException(500, "Prediction failed.") from None
        return {"prediction_code": code, "model_sha256": app.state.model_sha256,
                "contract_version": CONTRACT_VERSION}

    return app


app = create_app()
