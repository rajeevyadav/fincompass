"""Forecast plan orchestrator — Guided scenarios A-G (Phase 5).

The orchestrator's collaborators are monkeypatched so each recommended_action
branch is exercised deterministically without network/model/corpus.
"""
import pytest

from services import forecast_plan as fp

US_EQUITY = {"available": True, "symbol": "AAPL", "asset_class": "equity",
             "security_type": "US equity", "region": "US"}
US_BENCH = {"supported": True, "benchmark_symbol": "^GSPC", "benchmark_name": "S&P 500",
            "benchmark_family": "US_LARGE_CAP"}
MODEL = {"model_id": "m1", "validation_tier": "validated_research", "horizon_months": 12,
         "applicability_domain": {"training_period_end": "2022-06-30", "target_horizon_months": 12}}


def _base(monkeypatch, classification=US_EQUITY, benchmark=US_BENCH):
    monkeypatch.setattr(fp, "classify_instrument", lambda *a, **k: classification)
    monkeypatch.setattr(fp, "resolve_benchmark", lambda c: benchmark)
    monkeypatch.setattr(fp, "assess_model_freshness", lambda *a, **k: {"status": "stale"})
    monkeypatch.setattr(fp.research_store, "latest_date", lambda s: None)


def test_scenario_A_eligible_and_data_ready_recommends_forecast(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(fp, "find_models", lambda *a, **k: {"eligible": [MODEL], "alternatives": [], "unsupported": []})
    monkeypatch.setattr(fp, "forecast_preflight", lambda *a, **k: {"status": "ready", "data_ready": True,
                        "computationally_compatible": True, "scientifically_supported": True, "reasons": []})
    p = fp.build_forecast_plan("AAPL", 12)
    assert p["recommended_action"] == "forecast"
    assert p["model_freshness"]["status"] == "stale"  # freshness surfaced even when usable


def test_scenario_B_eligible_but_needs_data(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(fp, "find_models", lambda *a, **k: {"eligible": [MODEL], "alternatives": [], "unsupported": []})
    monkeypatch.setattr(fp, "forecast_preflight", lambda *a, **k: {"status": "needs_data", "data_ready": False,
                        "computationally_compatible": False, "scientifically_supported": True,
                        "reasons": [{"code": "INSUFFICIENT_HISTORY", "message_data": {}}]})
    p = fp.build_forecast_plan("AAPL", 12)
    assert p["recommended_action"] == "update_data"


def test_scenario_C_no_model_but_trainable(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(fp, "find_models", lambda *a, **k: {"eligible": [], "alternatives": [], "unsupported": []})
    monkeypatch.setattr(fp, "list_recipes", lambda: [{"recipe_id": "core-us-6m", "name": "Core US 6M",
                        "horizon_trading_days": 126, "benchmark": "SPY"}])
    monkeypatch.setattr(fp, "benchmark_family_of", lambda s: "US_LARGE_CAP")
    monkeypatch.setattr(fp, "evaluate_training_readiness", lambda rid: {"ready": True, "gates": []})
    p = fp.build_forecast_plan("AAPL", 6)
    assert p["recommended_action"] == "train"
    assert p["models"]["trainable"]


def test_scenario_C2_trainable_but_needs_data(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(fp, "find_models", lambda *a, **k: {"eligible": [], "alternatives": [], "unsupported": []})
    monkeypatch.setattr(fp, "list_recipes", lambda: [{"recipe_id": "core-us-6m", "name": "Core US 6M",
                        "horizon_trading_days": 126, "benchmark": "SPY"}])
    monkeypatch.setattr(fp, "benchmark_family_of", lambda s: "US_LARGE_CAP")
    monkeypatch.setattr(fp, "evaluate_training_readiness", lambda rid: {"ready": False,
                        "gates": [{"code": "MISSING_BENCHMARK"}, {"code": "INSUFFICIENT_HISTORY_FOR_HORIZON"}]})
    p = fp.build_forecast_plan("AAPL", 6)
    assert p["recommended_action"] == "update_data"


def test_scenario_E_scientifically_insufficient_is_unsupported(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(fp, "find_models", lambda *a, **k: {"eligible": [], "alternatives": [], "unsupported": []})
    monkeypatch.setattr(fp, "list_recipes", lambda: [{"recipe_id": "core-us-36m", "name": "Core US 36M",
                        "horizon_trading_days": 756, "benchmark": "SPY"}])
    monkeypatch.setattr(fp, "benchmark_family_of", lambda s: "US_LARGE_CAP")
    # a non-data gate (not in _DATA_FIXABLE) means more data won't help
    monkeypatch.setattr(fp, "evaluate_training_readiness", lambda rid: {"ready": False,
                        "gates": [{"code": "FEATURE_CONTRACT_INCOMPATIBLE"}]})
    p = fp.build_forecast_plan("AAPL", 36)
    assert p["recommended_action"] == "unsupported"


def test_scenario_F_unsupported_asset_no_benchmark(monkeypatch):
    crypto = {"available": True, "symbol": "BTC-USD", "asset_class": "crypto",
              "security_type": "crypto", "region": None}
    _base(monkeypatch, classification=crypto,
          benchmark={"supported": False, "benchmark_symbol": None, "reason": "BENCHMARK_POLICY_UNRESOLVED"})
    p = fp.build_forecast_plan("BTC-USD", 12)
    assert p["recommended_action"] == "unsupported"
    assert "benchmark policy" in p["message"].lower()


def test_unclassifiable_instrument_is_unsupported(monkeypatch):
    _base(monkeypatch, classification={"available": False, "symbol": "ZZZZ",
          "asset_class": "unknown", "region": None})
    p = fp.build_forecast_plan("ZZZZ", 12)
    assert p["recommended_action"] == "unsupported"
