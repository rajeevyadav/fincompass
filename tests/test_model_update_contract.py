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
    # The regime family has no runtime trainer, so its update must stay a safe,
    # keep-current no-op rather than an error.
    m = _by_profile("bayesian-regime")
    assert m is not None
    r = client.post(f"/api/v4/models/{m['model_id']}/update")
    assert r.status_code == 200
    body = r.json()
    assert body["retrain_supported"] is False
    assert body["keep_current"] is True
    assert "forecast remains available" in body["message"].lower()


def test_bayesian_reference_is_retrainable_via_a_real_recipe():
    # The reference family now has a runtime trainer, so its contract points to a
    # registered recipe and its update dispatches a build.
    from forecasting.recipes import RECIPES
    for m in list_model_manifests():
        if str(m.get("profile_name") or "").startswith("bayesian-reference"):
            c = m.get("training_contract") or {}
            assert c.get("retrain_supported") is True
            assert c.get("trainer_family") == "bayesian_reference"
            assert c.get("recipe_id") in RECIPES


def test_regime_manifests_declare_not_retrainable():
    for m in list_model_manifests():
        if str(m.get("profile_name") or "").startswith("bayesian-regime"):
            c = m.get("training_contract") or {}
            assert c.get("retrain_supported") is False
            assert c.get("recipe_id") is None
            assert c.get("trainer_family") == "bayesian_regime"


def test_unknown_model_id_is_404():
    r = client.post("/api/v4/models/deadbeefdeadbeef/update")
    assert r.status_code == 404


def test_runtime_recipes_cover_all_shipped_horizons():
    # Block 7: every shipped horizon has a working runtime retrain recipe, both an
    # enhanced ensemble and a Bayesian reference variant.
    from forecasting.recipes import RECIPES
    for months in (6, 12, 24, 36):
        assert f"core-us-{months}m" in RECIPES
        assert f"bayesian-reference-us-{months}m" in RECIPES
        assert RECIPES[f"bayesian-reference-us-{months}m"]["trainer_family"] == "bayesian_reference"
