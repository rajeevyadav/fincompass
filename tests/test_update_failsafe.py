"""An optional model update that cannot run must preserve the current model and
its Live eligibility, and say so in plain language — never strand the user."""
from __future__ import annotations

import glob
import json
from pathlib import Path

from fastapi.testclient import TestClient

from api import app

APP_JS = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
client = TestClient(app)


def _a_regime_model_id():
    for p in glob.glob("models/bayesian-regime-*.json"):
        if not p.endswith("-SUMMARY.json"):
            return json.load(open(p, encoding="utf-8"))["model_id"]
    return None


def test_update_of_non_retrainable_model_keeps_current():
    mid = _a_regime_model_id()
    assert mid, "expected a bundled non-retrainable (regime) model"
    r = client.post(f"/api/v4/models/{mid}/update")
    assert r.status_code == 200
    body = r.json()
    assert body["keep_current"] is True
    assert body["available"] is False
    assert body["retrain_supported"] is False
    assert "kept the current model" in body["message"].lower() or "current model" in body["message"].lower()


def test_update_of_unknown_model_is_a_clean_404():
    r = client.post("/api/v4/models/does-not-exist/update")
    assert r.status_code == 404


def test_guided_failure_wording_reassures_and_preserves():
    # The Guided flow must reassure that the forecast survives a failed update.
    assert "kept the current model" in APP_JS.lower()
    assert "your forecast remains available" in APP_JS.lower()
