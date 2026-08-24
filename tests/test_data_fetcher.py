import services.data_fetcher as dfmod
from services.data_fetcher import DataFetcher


class FakeTicker:
    def __init__(self, _ticker):
        self.info = {
            "longName": "Fixture Corp",
            "sector": "TECHNOLOGY",
            "debtToEquity": 151.0,
            "returnOnEquity": 0.20,
            "returnOnInvestedCapital": 0.15,
            "earningsGrowth": 0.12,
            "totalRevenue": 1000,
            "freeCashflow": 150,
        }


class FakeYF:
    Ticker = FakeTicker


def test_yfinance_debt_to_equity_percent_points_are_normalized(monkeypatch):
    monkeypatch.setattr(dfmod, "yf", FakeYF)
    fetcher = DataFetcher()
    data = fetcher._fetch_yfinance_fundamentals("TEST")
    assert data["debt_to_equity"] == 1.51
    assert data["roic"] == 0.15
    assert data["earnings_growth"] == 0.12
    assert data["fcf_margin"] == 0.15
    assert fetcher.health_snapshot()["yfinance"]["status"] == "ok"


class FakeResponse:
    status_code = 200
    def json(self):
        return {"Note": "API call frequency limit reached"}


class FakeSession:
    def get(self, url, params=None, timeout=None):
        assert "apikey=" not in url.lower()
        assert params and params.get("apikey") == "secret"
        return FakeResponse()


def test_alpha_vantage_http_200_throttle_is_detected_without_key_in_url():
    fetcher = DataFetcher()
    fetcher.session = FakeSession()
    data = fetcher._get_json(
        "https://www.alphavantage.co/query",
        params={"function": "OVERVIEW", "apikey": "secret"},
        provider="alpha_vantage",
    )
    assert data is None
    assert fetcher.health_snapshot()["alpha_vantage"]["status"] == "rate_limited"
