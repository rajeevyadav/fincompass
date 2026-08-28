"""Delta historical-data update lifecycle.

Proves: an incremental update fetches only the tail for an up-to-date symbol,
preserves existing history, adds new observations without duplicates, and — when
the stored price basis differs from the provider (e.g. a raw seed vs an adjusted
refresh) — recovers by rebuilding that one symbol on the new basis instead of
erroring out (the bug behind "update never updates").
"""
import pandas as pd
import pytest

from services.research_store import ResearchStore


def _frame(start, end, base=100.0, adj=False):
    idx = pd.bdate_range(start, end)
    px = [base + i for i in range(len(idx))]
    data = {"Open": px, "High": px, "Low": px, "Close": px, "Volume": [1000] * len(idx)}
    if adj:
        data["Adj Close"] = px
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def store(tmp_path):
    return ResearchStore(tmp_path / "rs.db", seed_db=tmp_path / "none.db",
                         raw_dir=tmp_path / "raw", bootstrap_seed=False)


def test_incremental_update_fetches_only_tail_and_preserves_history(store):
    store.register_instruments({"TESTCO": {"name": "Test Co", "asset_class": "equity", "region": "US"}})
    # existing adjusted history through 2020-06-30
    store.merge_price_frame("TESTCO", _frame("2015-01-01", "2020-06-30", adj=True),
                            provider="seed", price_basis="adjusted")
    before = store.latest_date("TESTCO")

    calls = {}
    def fetch_range(symbol, start, end):
        calls["start"] = pd.Timestamp(start)
        return _frame(start, end, base=500.0, adj=True), {"provider": "prov", "price_basis": "adjusted"}

    res = store.update_incremental(["TESTCO"], fetch_range, provider="prov", overlap_calendar_days=10)
    assert res["errors"] == {}
    # only the tail (latest - overlap) was requested, never a full re-download
    assert calls["start"] > pd.Timestamp("2020-01-01")
    after = store.latest_date("TESTCO")
    assert after > before  # new observations appended


def test_basis_mismatch_rebuilds_instead_of_erroring(store):
    store.register_instruments({"RAWCO": {"name": "Raw Co", "asset_class": "equity", "region": "US"}})
    # seed stored as RAW basis, ending 2017
    store.merge_price_frame("RAWCO", _frame("2010-01-01", "2017-11-10", adj=False),
                            provider="seed", price_basis="raw")
    before = store.latest_date("RAWCO")

    def fetch_range(symbol, start, end):
        # provider returns ADJUSTED, full history available to 2026
        return _frame("2010-01-01", "2026-08-28", adj=True), {"provider": "prov", "price_basis": "adjusted"}

    res = store.update_incremental(["RAWCO"], fetch_range, provider="prov", overlap_calendar_days=10)
    assert res["errors"] == {}, res["errors"]
    statuses = [r.get("status") for r in res["results"]]
    assert "rebuilt_price_basis" in statuses
    after = store.latest_date("RAWCO")
    assert after > before  # the symbol advanced instead of erroring
