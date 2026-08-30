"""Model-update endpoint dispatches by the explicit training contract and never
loses the current forecast (DIRECTIVE-008 blocks 4/5/8).

Uses the ACTUAL bundled model IDs so the manifests' declared contracts are
exercised end to end.
"""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api import app  # noqa: E402
from forecasting.registry import list_model_manifests  # noqa: E402

client = TestClient(app)


def _by_profile(prefix):
    for m in list_model_manifests():
        if str(m.get("profile_name") or "").startswith(prefix):
            return m
    return None


def test_bundled_enhanced_12m_declares_retrainable_contract():
    m = _by_profile("bundled-monthly-12m")
    assert m is not None
    c = m.get("training_contract") or {}
    assert c.get("retrain_supported") is True
    assert c.get("recipe_id") == "core-us-12m"
    assert c.get("trainer_family") == "enhanced_ensemble"


def test_bayesian_baseline_update_is_safe_not_an_error():
    # D8-02 / D8-08: a model with no runtime retrainer must NOT 422; it must
    # return a user-safe result that keeps the current model/forecast.
    m = _by_profile("bayesian-reference")
    assert m is not None
    r = client.post(f"/api/v4/models/{m['model_id']}/update")
    assert r.status_code == 200
    body = r.json()
    assert body["retrain_supported"] is False
    assert body["keep_current"] is True
    assert "forecast remains available" in body["message"].lower()


def test_bayesian_manifests_declare_not_retrainable():
    for m in list_model_manifests():
        prof = str(m.get("profile_name") or "")
        if prof.startswith("bayesian-"):
            c = m.get("training_contract") or {}
            assert c.get("retrain_supported") is False
            assert c.get("recipe_id") is None
            assert c.get("trainer_family") in {"bayesian_reference", "bayesian_regime"}


def test_unknown_model_id_is_404():
    r = client.post("/api/v4/models/deadbeefdeadbeef/update")
    assert r.status_code == 404
