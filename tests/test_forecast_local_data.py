import pandas as pd

import services.forecast_service as fs


def _frame():
    return pd.DataFrame({'Close': [100.0, 101.0], 'Volume': [1000.0, 1100.0]}, index=pd.to_datetime(['2024-01-02', '2024-01-03']))


def test_forecast_price_loader_prefers_durable_local_research_store(monkeypatch):
    local = _frame()
    monkeypatch.setattr(fs.research_store, 'read_price_history', lambda symbol: local)

    def network_must_not_run(*args, **kwargs):
        raise AssertionError('network/cache fallback should not run when local research data exist')

    monkeypatch.setattr(fs, 'get_price_history_cached', network_must_not_run)
    got = fs._get_price_history('SPY')
    pd.testing.assert_frame_equal(got, local)


def test_forecast_price_loader_falls_back_only_when_local_symbol_absent(monkeypatch):
    remote = _frame()
    monkeypatch.setattr(fs.research_store, 'read_price_history', lambda symbol: pd.DataFrame())
    calls = []
    monkeypatch.setattr(fs, 'get_price_history_cached', lambda symbol, period: calls.append((symbol, period)) or remote)
    got = fs._get_price_history('NEW')
    assert calls == [('NEW', 'max')]
    pd.testing.assert_frame_equal(got, remote)
