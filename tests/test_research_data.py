from pathlib import Path

import pandas as pd

import services.research_data as rd
from services.research_store import ResearchStore


def _bars(start: str, closes):
    dates = pd.date_range(start, periods=len(closes), freq="D")
    vals = [float(x) for x in closes]
    return pd.DataFrame(
        {
            "Open": vals,
            "High": [x + 1.0 for x in vals],
            "Low": [x - 1.0 for x in vals],
            "Close": vals,
            "Adj Close": vals,
            "Volume": [1000 + i for i in range(len(vals))],
        },
        index=dates,
    )


def test_refresh_is_incremental_deduped_and_retains_each_provider_snapshot(tmp_path, monkeypatch):
    store = ResearchStore(tmp_path / "research.db", raw_dir=tmp_path / "raw", bootstrap_seed=False)
    calls = []

    def fake_range(symbol, start, end):
        calls.append((symbol, pd.Timestamp(start), pd.Timestamp(end)))
        if len(calls) == 1:
            frame = _bars("2024-01-02", [100, 101])
        else:
            frame = _bars("2024-01-02", [100, 101, 102, 103])
        frame = frame[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]
        return frame, {
            "provider": "fixture-provider",
            "provider_symbol": symbol,
            "price_basis": "adjusted",
            "source_url": f"https://example.invalid/{symbol}",
            "requested_start": pd.Timestamp(start).date().isoformat(),
            "requested_end": pd.Timestamp(end).date().isoformat(),
        }

    monkeypatch.setattr(rd.fetcher, "get_price_history_range", fake_range)

    first = rd.refresh_market_data(["SPY"], store=store, overlap_calendar_days=2, end="2024-01-03")
    assert first["errors"] == {}
    assert first["results"][0]["inserted"] == 2
    assert len(store.read_price_history("SPY")) == 2

    second = rd.refresh_market_data(["SPY"], store=store, overlap_calendar_days=2, end="2024-01-05")
    assert second["errors"] == {}
    # Latest local observation was Jan 3; refresh asks only for the two-calendar-day overlap.
    assert calls[1][1] == pd.Timestamp("2024-01-01")
    assert second["results"][0]["inserted"] == 2
    assert second["results"][0]["unchanged"] == 2
    assert second["results"][0]["revised"] == 0
    assert len(store.read_price_history("SPY")) == 4

    raw = store.raw_sources(10)
    assert len(raw) == 2
    assert all(item["provider"] == "fixture-provider" for item in raw)
    for item in raw:
        assert (store.raw_dir / item["file_name"]).is_file()
        assert len(item["sha256"]) == 64


def test_refresh_state_marks_orphaned_running_job_interrupted(tmp_path, monkeypatch):
    state_path = tmp_path / "refresh_state.json"
    monkeypatch.setattr(rd, "REFRESH_STATE_PATH", state_path)
    monkeypatch.setattr(rd, "_thread", None)
    rd._write_state({"status": "running", "started_at": "2026-08-24T12:00:00+00:00"})
    state = rd.refresh_status()
    assert state["status"] == "interrupted"
    assert "retained rows are safe" in state["message"].lower()


def test_bundled_seed_copies_database_and_nested_raw_snapshots(tmp_path, monkeypatch):
    store = ResearchStore(tmp_path / "runtime.db", raw_dir=tmp_path / "runtime-raw", bootstrap_seed=False)

    def fake_range(symbol, start, end):
        return _bars("2024-01-02", [100, 101]), {
            "provider": "fixture-provider",
            "provider_symbol": symbol,
            "price_basis": "adjusted",
            "source_url": f"https://example.invalid/{symbol}",
        }

    monkeypatch.setattr(rd.fetcher, "get_price_history_range", fake_range)
    rd.refresh_market_data(["SPY"], store=store, end="2024-01-03")

    bundle = tmp_path / "bundle"
    monkeypatch.setattr(rd, "BUNDLED_SEED_DIR", bundle)
    monkeypatch.setattr(rd, "BUNDLED_SEED_DB", bundle / "market_seed.db")
    monkeypatch.setattr(rd, "BUNDLED_SEED_RAW", bundle / "raw")
    manifest = rd.build_bundled_seed(store)

    assert manifest["audit"]["rows"] == 2
    assert manifest["raw_files"] == 1
    assert (bundle / "market_seed.db").is_file()
    assert any(p.is_file() for p in (bundle / "raw").rglob("*.csv"))

    user_store = ResearchStore(
        tmp_path / "user" / "market_research.db",
        seed_db=bundle / "market_seed.db",
        raw_dir=tmp_path / "user" / "raw",
    )
    assert len(user_store.read_price_history("SPY")) == 2
    assert any(p.is_file() for p in user_store.raw_dir.rglob("*.csv"))
