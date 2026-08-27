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


def test_explicit_range_preserves_international_symbol_and_declares_basis(monkeypatch):
    import pandas as pd

    calls = {}

    class RangeTicker:
        def __init__(self, ticker):
            calls["ticker"] = ticker
        def history(self, **kwargs):
            calls["kwargs"] = kwargs
            idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
            return pd.DataFrame({
                "Open": [10.0, 10.5], "High": [11.0, 11.0], "Low": [9.5, 10.0],
                "Close": [10.5, 10.8], "Adj Close": [10.2, 10.6], "Volume": [100, 110],
            }, index=idx)

    class RangeYF:
        Ticker = RangeTicker

    monkeypatch.setattr(dfmod, "yf", RangeYF)
    fetcher = DataFetcher()
    frame, meta = fetcher.get_price_history_range("XIU.TO", "2024-01-02", "2024-01-03")
    assert calls["ticker"] == "XIU.TO"  # exchange suffix must not become XIU-TO
    assert calls["kwargs"]["start"] == "2024-01-02"
    assert calls["kwargs"]["end"] == "2024-01-04"  # yfinance end is exclusive
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    assert meta["provider"] == "yfinance"
    assert meta["price_basis"] == "adjusted"


def test_stooq_range_key_is_used_but_never_persisted_in_provenance(monkeypatch):
    import pandas as pd

    monkeypatch.setattr(dfmod, "yf", None)
    monkeypatch.setattr(dfmod, "STOOQ_API_KEY", "secret-stooq")
    calls = {}

    class Response:
        def raise_for_status(self):
            return None
        text = "Date,Open,High,Low,Close,Volume\n2024-01-02,10,11,9,10.5,100\n"

    class Session:
        headers = {}
        def get(self, url, timeout=None):
            calls["url"] = url
            return Response()

    fetcher = DataFetcher()
    fetcher.session = Session()
    frame, meta = fetcher.get_price_history_range("AAPL", "2024-01-02", "2024-01-03")
    assert not frame.empty
    assert "apikey=secret-stooq" in calls["url"]
    assert "apikey=" not in meta["source_url"]
    assert meta["provider"] == "stooq"
    assert fetcher.health_snapshot()["stooq"]["status"] == "ok"
