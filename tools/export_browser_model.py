#!/usr/bin/env python3
"""Export bundled Bayesian-reference forecast models to compact browser JSON.

The Guided Forecast model is a Bayesian logistic classifier (a coefficient
vector + covariance) followed by a probability calibrator. That is fully
portable: this writes the standardization vectors, coefficients, covariance and
calibrator parameters to web/models/forecast-<horizon>m.json so the browser can
reproduce the exact point probability with a few lines of arithmetic — no Python
runtime, no model pickle, no version coupling.

Run from the repo root:  python tools/export_browser_model.py
"""
from __future__ import annotations

import base64
import glob
import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so joblib can unpickle forecasting.* classes

import joblib  # noqa: E402
OUT_DIR = ROOT / "web" / "models"


def _calibrator_payload(cal) -> Dict[str, Any]:
    method = getattr(cal, "method", "sigmoid")
    model = cal.model
    if method == "isotonic":
        # A monotone step function; interpolate x->y in the browser.
        return {"method": "isotonic",
                "x": [float(v) for v in getattr(model, "X_thresholds_", [])],
                "y": [float(v) for v in getattr(model, "y_thresholds_", [])]}
    # sigmoid (Platt): calibrated = sigmoid(a * logit(p) + b)
    return {"method": "sigmoid",
            "a": float(model.coef_.ravel()[0]),
            "b": float(model.intercept_.ravel()[0])}


def export_one(manifest_path: Path) -> Dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model_file = manifest.get("model_file")
    model = joblib.load(manifest_path.parent / model_file)
    bayes = model.bayes
    domain = manifest.get("applicability_domain") or {}
    target = manifest.get("target") or {}
    settings = manifest.get("settings") or {}
    # The displayed probability is the mean over posterior coefficient draws; the
    # interval is their credible band. Those draws are fully determined by
    # (coef, covariance, seed, count), so we precompute the exact set the model
    # uses and ship it — the browser then reproduces the desktop value with pure
    # matrix math, no random number generator to match. Same call as the model's
    # posterior_probability_interval (numpy default method, check_valid ignored).
    seed = int(settings.get("random_seed", getattr(bayes, "random_seed", 37001)) or 37001)
    draws = int(settings.get("posterior_draws", 1200) or 1200)
    level = float(settings.get("prediction_credible_level", 0.90) or 0.90)
    rng = np.random.default_rng(seed)
    beta = rng.multivariate_normal(np.asarray(bayes.coef_, float),
                                   np.asarray(bayes.covariance_, float),
                                   size=draws, check_valid="ignore").astype("<f4")
    payload = {
        "model_id": manifest.get("model_id"),
        "validation_tier": manifest.get("validation_tier"),
        "horizon_months": target.get("horizon_months") or domain.get("target_horizon_months"),
        "benchmark": target.get("benchmark"),
        "benchmark_family": domain.get("benchmark_family"),
        "excess_return_threshold": target.get("excess_return_threshold", 0.0),
        "event": target.get("event"),
        "feature_contract": (manifest.get("dataset_provenance") or {}).get("feature_contract"),
        "feature_names": list(model.feature_names),
        "training_period_end": domain.get("training_period_end"),
        # Bayesian logistic: fill NaNs with medians, standardize, then sigmoid(Xa·coef).
        "medians": [float(v) for v in bayes.medians_],
        "means": [float(v) for v in bayes.means_],
        "scales": [float(v) for v in bayes.scales_],
        "coef": [float(v) for v in bayes.coef_],           # [intercept, β1..βn]
        # Precomputed posterior draws (draws x n+1), Float32, base64. The browser
        # reproduces the exact desktop point + interval from these.
        "beta_draws_b64": base64.b64encode(beta.tobytes()).decode("ascii"),
        "draws": draws,
        "credible_level": level,
        "calibrator": _calibrator_payload(model.calibrator),
        "disclaimer": ("Bayesian reference probability: mathematically valid and calibrated where "
                       "supported, but stronger out-of-sample skill is not established. Not advice."),
    }
    return payload


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for mp in sorted(glob.glob(str(ROOT / "models" / "bayesian-reference-*.json"))):
        if mp.endswith("-SUMMARY.json"):
            continue
        payload = export_one(Path(mp))
        h = payload["horizon_months"]
        out = OUT_DIR / f"forecast-{h}m.json"
        out.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        index.append({"horizon_months": h, "file": out.name, "model_id": payload["model_id"],
                      "validation_tier": payload["validation_tier"]})
        print(f"wrote {out.relative_to(ROOT)} ({len(payload['feature_names'])} features)")
    index.sort(key=lambda r: r["horizon_months"])
    (OUT_DIR / "index.json").write_text(json.dumps({"models": index}) + "\n", encoding="utf-8")
    print(f"wrote {(OUT_DIR / 'index.json').relative_to(ROOT)} ({len(index)} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
