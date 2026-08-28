"""Unit tests for the forecast applicability preflight (services/preflight.py).

Deterministic: model loading and price history are monkeypatched so no network,
model artifact, or corpus is required.
"""
import pandas as pd
import pytest

from services import preflight


class _FakeModel:
    def __init__(self, features, settings=None):
        self.feature_names = features
        self.settings = settings or {"benchmark": "^GSPC"}


# US-large-cap applicability domain matching the bundled model, so a US-equity
# ticker (AAPL) is scientifically supported and the data/compute flags decide.
_US_DOMAIN = {
    "asset_classes": ["equity"], "regions": ["US"], "benchmark_family": "US_LARGE_CAP",
    "supports_etf": False, "supports_crypto": False, "supports_bonds": False,
    "supports_commodity_proxies": False,
}


def _manifest(target=None, domain=_US_DOMAIN):
    m = {"model_id": "m1", "validation_tier": "validated_research",
         "target": target or {"benchmark": "^GSPC"}}
    if domain is not None:
        m["applicability_domain"] = domain
    return m


def _frame(rows=5):
    idx = pd.date_range("2020-01-01", periods=rows, freq="D")
    return pd.DataFrame({"Close": range(1, rows + 1)}, index=idx)


def _patch(monkeypatch, model, manifest, histories):
    monkeypatch.setattr(preflight, "load_model", lambda **k: (model, manifest))
    monkeypatch.setattr(preflight, "_get_price_history", lambda sym: histories.get(sym.upper()))


def test_no_eligible_model_is_unsupported(monkeypatch):
    monkeypatch.setattr(preflight, "load_model", lambda **k: (None, None))
    res = preflight.forecast_preflight("AAPL")
    assert res["status"] == "unsupported"
    assert res["reasons"][0]["code"] == "NO_ELIGIBLE_MODEL"


def test_missing_benchmark_is_needs_data(monkeypatch):
    model = _FakeModel(["feat_a"])
    _patch(monkeypatch, model, _manifest(), {"AAPL": _frame(), "^GSPC": pd.DataFrame()})
    res = preflight.forecast_preflight("AAPL")
    assert res["status"] == "needs_data"
    assert res["scientifically_supported"] is True and res["data_ready"] is False
    assert any(r["code"] == "BENCHMARK_UNAVAILABLE" for r in res["reasons"])
    assert res["benchmark"] == "^GSPC"


def test_missing_stock_history_is_needs_data(monkeypatch):
    model = _FakeModel(["feat_a"])
    _patch(monkeypatch, model, _manifest(), {"AAPL": pd.DataFrame(), "^GSPC": _frame()})
    res = preflight.forecast_preflight("AAPL")
    assert res["status"] == "needs_data"
    assert any(r["code"] == "INSUFFICIENT_HISTORY" for r in res["reasons"])


def test_ready_when_features_build_and_present(monkeypatch):
    model = _FakeModel(["feat_a", "feat_b"])
    _patch(monkeypatch, model, _manifest(), {"AAPL": _frame(40), "^GSPC": _frame(40)})
    monkeypatch.setattr(preflight, "build_price_features",
                        lambda s, b: pd.DataFrame({"feat_a": [0.1], "feat_b": [0.2]}))
    res = preflight.forecast_preflight("AAPL")
    assert res["status"] == "ready"
    assert res["reasons"] == []
    assert res["data_ready"] and res["computationally_compatible"] and res["scientifically_supported"]


def test_missing_features_is_unsupported(monkeypatch):
    model = _FakeModel(["feat_a", "feat_missing"])
    _patch(monkeypatch, model, _manifest(), {"AAPL": _frame(40), "^GSPC": _frame(40)})
    monkeypatch.setattr(preflight, "build_price_features", lambda s, b: pd.DataFrame({"feat_a": [0.1]}))
    res = preflight.forecast_preflight("AAPL")
    assert res["status"] == "unsupported"
    assert res["computationally_compatible"] is False
    assert any(r["code"] == "FEATURES_UNAVAILABLE" for r in res["reasons"])


def test_out_of_domain_instrument_is_scientifically_unsupported(monkeypatch):
    # A Canadian equity (XIU.TO classifies via suffix) must not be forecast by a
    # US-large-cap model even if price history is present.
    model = _FakeModel(["feat_a"])
    _patch(monkeypatch, model, _manifest(), {"XIU.TO": _frame(40), "^GSPC": _frame(40)})
    res = preflight.forecast_preflight("XIU.TO")
    assert res["status"] == "unsupported"
    assert res["scientifically_supported"] is False
    codes = {r["code"] for r in res["reasons"]}
    assert codes & {"UNSUPPORTED_REGION", "BENCHMARK_MISMATCH"}


def test_unclassifiable_symbol_is_unsupported(monkeypatch):
    model = _FakeModel(["feat_a"])
    _patch(monkeypatch, model, _manifest(), {"ZZZZ": _frame(40), "^GSPC": _frame(40)})
    res = preflight.forecast_preflight("ZZZZ")
    assert res["scientifically_supported"] is False
    assert any(r["code"] == "INSTRUMENT_CLASSIFICATION_UNAVAILABLE" for r in res["reasons"])


def test_model_without_domain_is_unknown_domain(monkeypatch):
    model = _FakeModel(["feat_a"])
    _patch(monkeypatch, model, _manifest(domain=None), {"AAPL": _frame(40), "^GSPC": _frame(40)})
    res = preflight.forecast_preflight("AAPL")
    assert res["scientifically_supported"] is False
    assert any(r["code"] == "MODEL_DOMAIN_UNKNOWN" for r in res["reasons"])
