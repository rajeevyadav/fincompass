"""Calculator endpoints surface the option / bond / portfolio engines.

These take explicit user inputs (no market data) and return model identities,
guarding against the engines being built but unreachable.
"""
import math

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api import app  # noqa: E402

client = TestClient(app)


def test_option_endpoint_matches_reference_values():
    r = client.post("/api/v2/analytics/options",
                    json={"option_type": "call", "spot": 100, "strike": 100,
                          "rate": 0.05, "vol": 0.20, "expiry": 1})
    assert r.status_code == 200
    res = r.json()["results"]
    assert res["price"] == pytest.approx(10.4506, abs=1e-3)
    assert res["delta"] == pytest.approx(0.6368, abs=1e-3)
    assert res["vega"] > 0


def test_bond_endpoint_par_and_duration():
    r = client.post("/api/v2/analytics/bond",
                    json={"face": 1000, "coupon_rate": 0.05, "ytm": 0.05, "years": 10, "freq": 2})
    res = r.json()["results"]
    assert res["price"] == pytest.approx(1000.0)          # coupon == yield -> par
    assert 0 < res["modified_duration"] < 10              # less than maturity
    assert res["convexity"] > 0


def test_portfolio_endpoint_risk_contributions_sum_to_one():
    r = client.post("/api/v2/analytics/portfolio",
                    json={"weights": [0.5, 0.5], "cov": [[0.04, 0.0], [0.0, 0.09]]})
    res = r.json()["results"]
    assert res["volatility"] == pytest.approx(math.sqrt(0.0325))
    assert sum(res["risk_contributions"]["percent"]) == pytest.approx(1.0)


def test_option_invalid_inputs_are_null_not_error():
    r = client.post("/api/v2/analytics/options",
                    json={"option_type": "call", "spot": 0, "strike": 100,
                          "rate": 0.05, "vol": 0.2, "expiry": 1})
    assert r.status_code == 200
    assert r.json()["results"]["price"] is None           # NaN serialized as null
