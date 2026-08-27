"""Price-history cache resilience: serve stored data when a fresh fetch fails."""
import pandas as pd

import services.analyzer as analyzer


def _sample_df():
    idx = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])
    df = pd.DataFrame({"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3],
                       "Close": [1, 2, 3], "Volume": [10, 20, 30]}, index=idx)
    df.index.name = "Date"
    return df


def test_stale_cache_served_when_fetch_fails(monkeypatch):
    df = _sample_df()

    # Fresh cache check (default TTL) misses; the stale check (huge max_age) hits.
    def fake_cache_get(ticker, period, max_age_hours=analyzer.cache.get_price_history.__defaults__[0]):
        return df if max_age_hours >= 10 ** 8 else None

    monkeypatch.setattr(analyzer.cache, "get_price_history", fake_cache_get)
    monkeypatch.setattr(analyzer.fetcher, "get_price_history", lambda t, p: None)

    out = analyzer.get_price_history_cached("XYZ", "10y")
    assert out is df  # degraded gracefully to stored data instead of None


def test_fresh_fetch_used_and_cached(monkeypatch):
    df = _sample_df()
    saved = {}
    monkeypatch.setattr(analyzer.cache, "get_price_history", lambda t, p, max_age_hours=24: None)
    monkeypatch.setattr(analyzer.fetcher, "get_price_history", lambda t, p: df)
    monkeypatch.setattr(analyzer.cache, "set_price_history", lambda t, p, d: saved.update({"df": d}))

    out = analyzer.get_price_history_cached("XYZ", "10y")
    assert out is df
    assert saved.get("df") is df  # a successful fetch is persisted for reuse


def test_none_when_no_data_anywhere(monkeypatch):
    monkeypatch.setattr(analyzer.cache, "get_price_history", lambda t, p, max_age_hours=24: None)
    monkeypatch.setattr(analyzer.fetcher, "get_price_history", lambda t, p: None)
    assert analyzer.get_price_history_cached("XYZ", "10y") is None
