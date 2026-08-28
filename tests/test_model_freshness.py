"""Model freshness policy (Phase 5)."""
from services.model_freshness import assess_model_freshness


def _m(cutoff):
    return {"applicability_domain": {"training_period_end": cutoff, "target_horizon_months": 12}}


def test_current_when_recent():
    r = assess_model_freshness(_m("2026-06-30"), "2026-07-31", 12)
    assert r["status"] == "current"


def test_update_recommended_mid_range():
    r = assess_model_freshness(_m("2025-01-31"), "2026-08-31", 12)
    assert r["status"] == "update_recommended"
    assert r["model_data_lag_months"] > 12


def test_stale_when_far_behind():
    r = assess_model_freshness(_m("2022-01-31"), "2026-08-31", 12)
    assert r["status"] == "stale"
    assert r["new_matured_targets_available"] > 0


def test_unknown_without_cutoff_or_current():
    assert assess_model_freshness({"applicability_domain": {}}, "2026-08-31", 12)["status"] == "unknown"
    assert assess_model_freshness(_m("2022-01-31"), None, 12)["status"] == "unknown"
