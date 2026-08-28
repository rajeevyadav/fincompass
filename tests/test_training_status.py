"""§6E: data-not-ready must be a distinct 'not_ready' status, never a software
'failed'. Verifies the trainer registers not_ready when required local data are
absent, without running actual training."""
from services import model_builder as mb


_RECIPE = {
    "recipe_id": "core-us-6m", "settings_hash": "h", "name": "Core US 6M",
    "horizon_trading_days": 126, "benchmark": "^GSPC", "tickers": ["AAPL"],
    "profile": "strict", "feature_contract": "price_relative_v1", "live_eligible_target": True,
}


def _capture(monkeypatch, prices, benchmark, missing):
    seen = {"statuses": []}
    monkeypatch.setattr(mb, "get_recipe", lambda rid: dict(_RECIPE))
    monkeypatch.setattr(mb, "_load_local_market_data", lambda symbols, bench: (prices, benchmark, missing))
    def fake_register(exp, recipe, **k):
        seen["statuses"].append(k.get("status"))
        return {}
    monkeypatch.setattr(mb, "_register", fake_register)
    monkeypatch.setattr(mb.cache, "update_model_build", lambda **k: seen.__setitem__("cache", k.get("status")))
    return seen


def test_missing_benchmark_registers_not_ready(monkeypatch, tmp_path):
    seen = _capture(monkeypatch, {}, None, ["AAPL"])
    mb._worker("core-us-6m", "strict", None, tmp_path, "exp-nb")
    assert seen["statuses"][-1] == "not_ready"
    assert seen["cache"] == "not_ready"


def test_missing_targets_registers_not_ready(monkeypatch, tmp_path):
    import pandas as pd
    bench = pd.DataFrame({"Close": range(1, 30)}, index=pd.date_range("2020-01-01", periods=29))
    seen = _capture(monkeypatch, {}, bench, ["AAPL"])
    mb._worker("core-us-6m", "strict", None, tmp_path, "exp-nt")
    assert seen["statuses"][-1] == "not_ready"
