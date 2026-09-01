"""The exported browser model JSON must reproduce the Python Forecast model's
probability exactly. If this holds, the JavaScript port (web/forecast.js) is a
faithful forecast, not an approximation."""
from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODELS = sorted(p for p in glob.glob(str(ROOT / "web" / "models" / "forecast-*.json")))
pytestmark = pytest.mark.skipif(not MODELS, reason="run tools/export_browser_model.py first")


def _load_py_model(model_id):
    import joblib
    for mp in glob.glob(str(ROOT / "models" / "bayesian-reference-*.json")):
        if mp.endswith("-SUMMARY.json"):
            continue
        m = json.loads(Path(mp).read_text(encoding="utf-8"))
        if m.get("model_id") == model_id:
            return joblib.load(Path(mp).parent / m["model_file"])
    return None


def _clip(p):
    return min(max(float(p), 1e-6), 1 - 1e-6)


def _calibrate(cal, p):
    p = _clip(p)
    if cal["method"] == "sigmoid":
        x = np.log(p / (1 - p))
        return _clip(1.0 / (1.0 + np.exp(-(cal["a"] * x + cal["b"]))))
    return _clip(float(np.interp(p, cal["x"], cal["y"])))


def _reimpl_point(js, X):
    med, mean, scale = np.array(js["medians"]), np.array(js["means"]), np.array(js["scales"])
    coef = np.array(js["coef"])
    X = np.where(np.isfinite(X), X, med)
    Xs = (X - mean) / scale
    Xa = np.concatenate([[1.0], Xs])
    raw = 1.0 / (1.0 + np.exp(-(Xa @ coef)))
    return _calibrate(js["calibrator"], raw)


@pytest.mark.parametrize("model_json_path", MODELS)
def test_export_reproduces_python_deterministic_probability(model_json_path):
    js = json.loads(Path(model_json_path).read_text(encoding="utf-8"))
    model = _load_py_model(js["model_id"])
    assert model is not None, f"python model missing for {js['model_id']}"
    rng = np.random.default_rng(7)
    feats = js["feature_names"]
    for _ in range(25):
        # Plausible standardized-scale raw features around the training means.
        X = np.array(js["means"]) + rng.normal(0, 1, len(feats)) * np.array(js["scales"])
        frame = pd.DataFrame([X], columns=feats)
        py = float(model.predict_proba(frame)[0])          # deterministic sigmoid(Xa·coef) + calibrator
        mine = float(_reimpl_point(js, X))
        assert abs(py - mine) < 1e-9, f"{js['model_id']}: {py} vs {mine}"


def _forecast_from_shipped_draws(js, X):
    """Exactly what web/forecast.js does: decode the shipped posterior draws,
    standardize X, average sigmoid over the draws, take the credible band, and
    calibrate. No RNG — the draws are the model's own, so this reproduces the
    desktop value bit-for-bit (to Float32 precision)."""
    import base64
    med, mean, scale = np.array(js["medians"]), np.array(js["means"]), np.array(js["scales"])
    n = len(js["coef"])
    beta = np.frombuffer(base64.b64decode(js["beta_draws_b64"]), dtype="<f4").reshape(js["draws"], n).astype(float)
    Xs = (np.where(np.isfinite(X), X, med) - mean) / scale
    Xa = np.concatenate([[1.0], Xs])
    p = 1.0 / (1.0 + np.exp(-(Xa @ beta.T)))
    tail = (1 - js["credible_level"]) / 2
    lo = _calibrate(js["calibrator"], np.quantile(p, tail))
    hi = _calibrate(js["calibrator"], np.quantile(p, 1 - tail))
    return _calibrate(js["calibrator"], p.mean()), min(lo, hi), max(lo, hi)


@pytest.mark.parametrize("model_json_path", MODELS)
def test_shipped_draws_reproduce_the_model_exactly(model_json_path):
    # The browser uses the model's own precomputed posterior draws, so its point
    # probability and interval match the desktop to Float32 precision, not just
    # Monte-Carlo tolerance.
    js = json.loads(Path(model_json_path).read_text(encoding="utf-8"))
    model = _load_py_model(js["model_id"])
    feats = js["feature_names"]
    rng = np.random.default_rng(11)
    for _ in range(20):
        X = np.array(js["means"]) + rng.normal(0, 1, len(feats)) * np.array(js["scales"])
        frame = pd.DataFrame([X], columns=feats)
        got = model.predict_with_uncertainty(frame)[0]
        pt, lo, hi = _forecast_from_shipped_draws(js, X)
        assert abs(pt - float(got["probability_outperform"])) < 5e-4, f"point {pt} vs {got['probability_outperform']}"
        ci = got["uncertainty_interval"]
        assert abs(lo - float(ci[0])) < 5e-4 and abs(hi - float(ci[1])) < 5e-4
