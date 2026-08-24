from datetime import date

import services.macro_fetcher as mf


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


def test_commodity_context_requests_explicit_five_year_window(monkeypatch):
    monkeypatch.setattr(mf, "FRED_API_KEY", "test")
    seen = {}
    observations = [{"date": f"2026-01-{(i % 28)+1:02d}", "value": str(90 + (i % 21))} for i in range(300)]

    def fake_get(url, params, timeout):
        seen.update(params)
        return FakeResponse({"observations": observations})

    monkeypatch.setattr(mf.requests, "get", fake_get)
    out = mf.get_commodity_context("Energy")
    assert "observation_start" in seen
    assert "limit" not in seen
    assert out["observations"] == 300
    assert out["trend_definition"] == "5y median"
    assert out["trailing_median"] > 0


class RateLimitResponse:
    status_code = 429
    def json(self):
        return {}


def test_fred_health_reports_rate_limit(monkeypatch):
    monkeypatch.setattr(mf, "FRED_API_KEY", "test")
    monkeypatch.setattr(mf.requests, "get", lambda *a, **k: RateLimitResponse())
    assert mf._fetch_latest("T10Y2Y") is None
    health = mf.get_health_snapshot()
    assert health["configured"] is True
    assert health["status"] == "rate_limited"
