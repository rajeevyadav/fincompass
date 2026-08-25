from pathlib import Path

import pandas as pd
import pytest

from forecasting.recipes import get_recipe, list_recipes
from services.research_store import ResearchStore


def _frame(dates, closes, *, adj=None):
    idx = pd.to_datetime(dates)
    close = list(closes)
    return pd.DataFrame({
        "Open": close,
        "High": [x + 1 for x in close],
        "Low": [x - 1 for x in close],
        "Close": close,
        "Adj Close": list(adj) if adj is not None else close,
        "Volume": [1000 + i for i in range(len(close))],
    }, index=idx)


def test_merge_is_deterministic_and_deduplicates(tmp_path):
    store = ResearchStore(tmp_path / "research.db", bootstrap_seed=False, raw_dir=tmp_path / "raw")
    f = _frame(["2024-01-02", "2024-01-03"], [100.0, 101.0])
    first = store.merge_price_frame("SPY", f, provider="test", price_basis="adjusted")
    second = store.merge_price_frame("SPY", f, provider="test", price_basis="adjusted")
    assert first.inserted == 2
    assert second.inserted == 0 and second.unchanged == 2
    assert len(store.read_price_history("SPY")) == 2


def test_overlap_revision_is_recorded_before_value_changes(tmp_path):
    store = ResearchStore(tmp_path / "research.db", bootstrap_seed=False, raw_dir=tmp_path / "raw")
    store.merge_price_frame("SPY", _frame(["2024-01-02"], [100.0]), provider="p1")
    result = store.merge_price_frame("SPY", _frame(["2024-01-02"], [100.5]), provider="p1")
    assert result.revised == 1
    assert store.revision_count("SPY") == 1
    assert float(store.read_price_history("SPY").iloc[0]["Close"]) == 100.5


def test_price_basis_cannot_silently_change(tmp_path):
    store = ResearchStore(tmp_path / "research.db", bootstrap_seed=False, raw_dir=tmp_path / "raw")
    f = _frame(["2024-01-02"], [100.0])
    store.merge_price_frame("SPY", f, provider="p1", price_basis="adjusted")
    with pytest.raises(ValueError, match="price basis mismatch"):
        store.merge_price_frame("SPY", f, provider="p2", price_basis="raw")


def test_incremental_update_requests_only_overlap_not_full_history(tmp_path):
    store = ResearchStore(tmp_path / "research.db", bootstrap_seed=False, raw_dir=tmp_path / "raw")
    initial_dates = pd.bdate_range("2024-01-02", periods=8)
    store.merge_price_frame("SPY", _frame(initial_dates, range(100, 108)), provider="seed")
    calls = []

    def fetch(symbol, start, end):
        calls.append((symbol, start, end))
        dates = pd.bdate_range(start, end)
        return _frame(dates, [200 + i for i in range(len(dates))])

    latest = store.latest_date("SPY")
    store.update_incremental(["SPY"], fetch, provider="test", overlap_calendar_days=3, end=latest + pd.Timedelta(days=2))
    assert len(calls) == 1
    assert calls[0][1] == latest - pd.Timedelta(days=3)
    assert calls[0][1] > pd.Timestamp("2024-01-02")


def test_recipe_hash_is_stable_and_cross_asset_catalogued():
    a = get_recipe("core-us-6m")
    b = get_recipe("core-us-6m")
    assert a["settings_hash"] == b["settings_hash"]
    ids = {r["recipe_id"] for r in list_recipes()}
    assert {"core-us-6m", "nasdaq-growth-6m", "global-proxy-6m", "cross-asset-regime-6m"} <= ids


def test_incremental_update_archives_provider_frame_and_links_hash(tmp_path):
    store = ResearchStore(tmp_path / "research.db", bootstrap_seed=False, raw_dir=tmp_path / "raw")
    frame = _frame(pd.bdate_range("2024-01-02", periods=3), [100, 101, 102])

    def fetch(symbol, start, end):
        return frame, {"provider": "fixture-provider", "price_basis": "adjusted", "source_url": "https://example.invalid/data"}

    result = store.update_incremental(["SPY"], fetch, provider="fallback", end="2024-01-10")
    row = result["results"][0]
    assert row["status"] == "ok"
    assert len(row["raw_sha256"]) == 64
    raw_path = tmp_path / "raw" / row["raw_file"]
    assert raw_path.exists()
    with store._connect() as conn:
        linked = conn.execute("SELECT DISTINCT raw_sha256 FROM price_bars WHERE symbol='SPY'").fetchall()
    assert [r[0] for r in linked] == [row["raw_sha256"]]


def test_first_run_bootstraps_writable_store_from_seed(tmp_path):
    seed = ResearchStore(tmp_path / "seed.db", bootstrap_seed=False, raw_dir=tmp_path / "seed-raw")
    seed.merge_price_frame("SPY", _frame(["2024-01-02"], [100.0]), provider="seed")
    writable_path = tmp_path / "user" / "research.db"
    writable = ResearchStore(writable_path, seed_db=tmp_path / "seed.db", raw_dir=tmp_path / "user-raw", bootstrap_seed=True)
    assert writable_path.exists()
    assert len(writable.read_price_history("SPY")) == 1


def test_interrupted_experiment_closes_only_in_progress_state(tmp_path):
    store = ResearchStore(tmp_path / "research.db", bootstrap_seed=False, raw_dir=tmp_path / "raw")
    store.register_experiment({"experiment_id": "exp-running", "recipe_id": "r", "status": "training", "message": "working"})
    store.register_experiment({"experiment_id": "exp-done", "recipe_id": "r", "status": "validated", "message": "done"})
    assert store.mark_experiment_interrupted("exp-running", "interrupted") is True
    assert store.get_experiment("exp-running")["status"] == "interrupted"
    assert store.get_experiment("exp-running")["message"] == "interrupted"
    assert store.mark_experiment_interrupted("exp-done", "should not change") is False
    assert store.get_experiment("exp-done")["status"] == "validated"
