"""The /api/v2/analytics/{ticker}/overview endpoint surfaces the deterministic
analytics kernel: performance, risk, and (for equities) financial ratios + a
scenario DCF. Regression guard for the 500 caused by missing summary functions.
"""
import numpy as np
import pandas as pd
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import services.forecast_service as fs  # noqa: E402
import services.fundamentals as F  # noqa: E402
from api import app  # noqa: E402


def _prices(_symbol):
    idx = pd.bdate_range("2019-01-02", "2026-08-01")
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.011, len(idx))))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close}, index=idx)


_STATEMENTS = {
    "income": {"Total Revenue": 400e9, "Operating Income": 120e9, "Pretax Income": 118e9,
               "Tax Provision": 18e9, "Net Income": 100e9, "Reconciled Depreciation": 11e9,
               "Diluted Average Shares": 16e9, "EBIT": 120e9},
    "balance": {"Total Assets": 350e9, "Current Assets": 135e9, "Cash And Cash Equivalents": 60e9,
                "Current Liabilities": 145e9, "Total Debt": 110e9, "Total Equity": 70e9, "Inventory": 6e9},
    "cashflow": {"Operating Cash Flow": 115e9, "Capital Expenditure": -11e9},
    "currency": "USD",
}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(fs, "_get_price_history", _prices)
    monkeypatch.setattr(F, "_fetch_yfinance_statements", lambda t: dict(_STATEMENTS))
    return TestClient(app)


def test_overview_returns_performance_and_risk(client):
    r = client.get("/api/v2/analytics/AAPL/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    for k in ("annualized_return", "annualized_volatility", "sharpe", "max_drawdown"):
        assert k in body["performance"]
    for k in ("historical_var", "conditional_var", "ewma_volatility"):
        assert k in body["risk"]


def test_overview_surfaces_ratios_and_dcf_for_equity(client):
    body = client.get("/api/v2/analytics/AAPL/overview").json()
    f = body["fundamentals"]
    assert f["available"] is True
    assert len(f["ratios"]) >= 8
    dcf = f["dcf"]
    assert dcf["valid"] is True
    assert dcf["value_per_share"] and dcf["value_per_share"] > 0
    # a scenario range, and the governance disclaimer, are always present
    assert dcf["range_low"] <= dcf["value_per_share"] <= dcf["range_high"]
    assert "not a" in dcf["disclaimer"].lower()


def test_overview_json_is_finite_safe(client):
    # NaN would break JSON; summaries must emit null instead
    import json
    raw = client.get("/api/v2/analytics/AAPL/overview").text
    assert "NaN" not in raw
    json.loads(raw)  # must parse
