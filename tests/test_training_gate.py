"""Training gate + final-state + governance invariants (§6E/§8/§9)."""
import json

import pytest

from services import model_builder as mb


RECIPE = {"recipe_id": "core-us-6m", "settings_hash": "h", "name": "Core US 6M",
          "horizon_trading_days": 126, "benchmark": "^GSPC", "tickers": ["AAPL"],
          "profile": "strict", "feature_contract": "price_relative_v1", "live_eligible_target": True}


def test_start_build_blocked_when_not_ready_never_claims_slot(monkeypatch, tmp_path):
    monkeypatch.setattr(mb, "get_recipe", lambda rid: dict(RECIPE))
    monkeypatch.setattr(mb, "BUILD_OUTPUT_DIR", tmp_path)
    not_ready = {"ready": False, "status": "not_ready",
                 "gates": [{"code": "MISSING_BENCHMARK", "action": "Update ^GSPC.", "explanation": "no benchmark", "symbols": ["^GSPC"]}],
                 "universe": {"requested": ["AAPL"], "usable": [], "excluded": []}}
    monkeypatch.setattr(mb, "evaluate_training_readiness", lambda *a, **k: not_ready)
    monkeypatch.setattr(mb, "_register", lambda *a, **k: {})
    claimed = {"called": False}
    monkeypatch.setattr(mb.cache, "claim_model_build", lambda *a, **k: claimed.__setitem__("called", True) or (True, {}))

    result = mb.start_model_build(recipe_id="core-us-6m")
    assert result["started"] is False and result["status"] == "not_ready"
    assert claimed["called"] is False  # active model + build slot untouched
    # diagnostic.json written for the blocked attempt
    diag = next(tmp_path.glob("*/diagnostic.json"))
    data = json.loads(diag.read_text())
    assert data["final_state"] == "not_ready"
    assert data["readiness_gates"][0]["code"] == "MISSING_BENCHMARK"


def test_worker_exception_registers_failed_with_traceback(monkeypatch, tmp_path):
    monkeypatch.setattr(mb, "get_recipe", lambda rid: dict(RECIPE))
    monkeypatch.setattr(mb.cache, "update_model_build", lambda **k: None)
    seen = {"statuses": []}
    monkeypatch.setattr(mb, "_register", lambda exp, recipe, **k: seen["statuses"].append(k.get("status")) or {})

    def boom(*a, **k):
        raise RuntimeError("synthetic numerical failure")
    monkeypatch.setattr(mb, "_load_local_market_data", boom)

    mb._worker("core-us-6m", "strict", None, tmp_path, "exp-fail")
    assert seen["statuses"][-1] == "failed"
    diag = json.loads((tmp_path / "exp-fail" / "diagnostic.json").read_text())
    assert diag["final_state"] == "failed"
    assert "synthetic numerical failure" in (diag["traceback"] or "")


def test_worker_never_auto_activates_a_model():
    """The trainer must never activate a model implicitly (§: no auto-activation)."""
    src = (mb.__file__)
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    # The worker/build path must not call activation helpers.
    assert "set_active_model" not in text
    assert "clear_active_model" not in text
