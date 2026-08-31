"""The analytics calculators must disclose their data sources and assumptions:
option premium basis / rate / dividend / IV / expiry convention, the Treasury-is-
not-the-required-yield warning for bonds, and the portfolio risk decomposition."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api import app

APP_JS = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")

client = TestClient(app)


def test_bond_treasury_warning_present():
    assert "not automatically the right yield" in APP_JS
    assert "credit spread" in APP_JS
    assert "bondAnalyticsHtml" in APP_JS


def test_option_assumptions_disclosure_present():
    for token in ("optionAssumptionsHtml", "Dividend yield", "Actual/365.25",
                  "present value before expiry", "Risk-free rate"):
        assert token in APP_JS, token


def test_portfolio_decomposition_present():
    for token in ("Marginal", "Component", "Risk decomposition", "weights_normalized"):
        assert token in APP_JS, token


def test_portfolio_api_exposes_marginal_and_component():
    r = client.post("/api/v2/analytics/portfolio",
                    json={"weights": [0.5, 0.5], "cov": [[0.04, 0.006], [0.006, 0.09]]}).json()
    rc = r["results"]["risk_contributions"]
    assert {"marginal", "component", "percent"} <= set(rc)
    assert "weights_normalized" in r["results"]


def test_bond_api_exposes_duration_and_convexity():
    r = client.post("/api/v2/analytics/bond",
                    json={"face": 1000, "coupon_rate": 0.05, "ytm": 0.05, "years": 10, "freq": 2}).json()
    res = r["results"]
    for k in ("price", "current_yield", "macaulay_duration", "modified_duration", "convexity", "dv01"):
        assert k in res, k
