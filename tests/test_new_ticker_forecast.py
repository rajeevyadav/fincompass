"""A valid, in-domain new ticker reaches Forecast without a blocking data or
model-maintenance step (DIRECTIVE-008 blocks 3/10). Local store coverage is only
advisory (needed for richer Live), never a prerequisite for a one-shot forecast.
"""
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import services.forecast_plan as fp  # noqa: E402
from api import app  # noqa: E402

client = TestClient(app)


def test_new_us_ticker_recommends_forecast_not_maintenance(monkeypatch):
    # Force "no local data yet" for any symbol — a brand-new ticker.
    monkeypatch.setattr(fp, "_ready", lambda symbol: False)
    for ticker in ("COST", "NKE", "V"):
        plan = client.get(f"/api/v4/forecast-plan/{ticker}?horizon_months=12").json()
        assert plan["recommended_action"] == "forecast", ticker
        assert plan["can_forecast_now"] is True
        # the data refresh is offered, but only as optional (for Live), not blocking
        assert plan["data_update_available"] is True
        assert plan["model_update_required"] is False


def test_out_of_domain_ticker_still_unsupported(monkeypatch):
    monkeypatch.setattr(fp, "_ready", lambda symbol: False)
    plan = client.get("/api/v4/forecast-plan/BTC-USD?horizon_months=12").json()
    assert plan["recommended_action"] == "unsupported"
    assert plan["can_forecast_now"] is False


def test_forecast_endpoint_produces_a_probability_for_new_ticker():
    # The forecast itself is producible on demand (pooled model + fetched history).
    f = client.get("/api/v4/forecast/COST?horizon_months=12").json()
    assert f["available"] is True
    p = (f.get("probability") or {}).get("probability_outperform")
    assert p is not None and 0.0 < float(p) < 1.0
