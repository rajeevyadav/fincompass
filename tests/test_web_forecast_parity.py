"""End-to-end parity for the browser Forecast: the JS feature pipeline + inference
(web/forecast.js) must match the Python kernel on the same daily price series.
This is the real correctness gate for the monthly-relative feature port."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import glob
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from forecasting.features import build_monthly_relative_features

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
MODELS = sorted(glob.glob(str(ROOT / "web" / "models" / "forecast-*.json")))
pytestmark = pytest.mark.skipif(NODE is None or not MODELS, reason="Node and exported models required")


def _series():
    """A deterministic daily stock + benchmark series, ~2 years of business days."""
    dates = pd.bdate_range("2022-01-03", periods=520)
    t = np.arange(len(dates))
    stock = 100 * (1 + 0.0004 * t) * (1 + 0.12 * np.sin(t / 21.0))
    bench = 100 * (1 + 0.0003 * t) * (1 + 0.08 * np.sin(t / 25.0 + 0.7))
    sdf = pd.DataFrame({"Close": stock}, index=dates)
    bdf = pd.DataFrame({"Close": bench}, index=dates)
    bars = lambda df: [{"date": d.strftime("%Y-%m-%d"), "close": float(c)} for d, c in zip(df.index, df["Close"])]
    return sdf, bdf, bars(sdf), bars(bdf)


def _py_forecast(model_id, feat_row):
    import joblib
    for mp in glob.glob(str(ROOT / "models" / "bayesian-reference-*.json")):
        if mp.endswith("-SUMMARY.json"):
            continue
        m = json.loads(Path(mp).read_text(encoding="utf-8"))
        if m.get("model_id") == model_id:
            model = joblib.load(Path(mp).parent / m["model_file"])
            return model.predict_with_uncertainty(feat_row)[0]
    return None


def _js(model_path, sbars, bbars, tmp_path):
    # Pass data via files; inlining 500+ bars into node -e overruns the Windows
    # command-line length limit.
    bars_file = tmp_path / "bars.json"
    bars_file.write_text(json.dumps({"s": sbars, "b": bbars}), encoding="utf-8")
    driver = tmp_path / "driver.js"
    driver.write_text(
        f"const FC=require({json.dumps(str(ROOT / 'web' / 'forecast.js'))});\n"
        f"const js=require({json.dumps(model_path)});\n"
        f"const d=require({json.dumps(str(bars_file))});\n"
        "const built=FC.buildFeatures(d.s,d.b);\n"
        "const fc=FC.forecast(js,built.features);\n"
        "process.stdout.write(JSON.stringify({features:built.features,fc}));\n",
        encoding="utf-8")
    out = subprocess.check_output([NODE, str(driver)], cwd=str(ROOT))
    return json.loads(out.decode("utf-8"))


@pytest.mark.parametrize("model_path", MODELS)
def test_forecast_features_and_probability_match_python(model_path, tmp_path):
    js = json.loads(Path(model_path).read_text(encoding="utf-8"))
    sdf, bdf, sbars, bbars = _series()

    # Python features (the same monthly-relative pipeline the desktop uses).
    feats = build_monthly_relative_features(sdf, bdf)
    row = feats.tail(1)[js["feature_names"]]
    py_row = {k: float(row.iloc[0][k]) for k in js["feature_names"]}

    result = _js(model_path, sbars, bbars, tmp_path)
    js_feat = result["features"]

    # 1) Feature parity — the riskiest port. Tight tolerance.
    for name in js["feature_names"]:
        a, b = float(js_feat[name]), py_row[name]
        if math.isnan(b):
            assert math.isnan(a) or a is None, f"{name}: py NaN, js {a}"
        else:
            assert abs(a - b) < 1e-6, f"{name}: js {a} vs py {b}"

    # 2) Forecast parity — same shipped draws, so point + interval match closely.
    py = _py_forecast(js["model_id"], row)
    assert abs(result["fc"]["probability_outperform"] - float(py["probability_outperform"])) < 2e-3
    ci_py, ci_js = py["uncertainty_interval"], result["fc"]["uncertainty_interval"]
    assert abs(ci_js[0] - float(ci_py[0])) < 3e-3 and abs(ci_js[1] - float(ci_py[1])) < 3e-3
