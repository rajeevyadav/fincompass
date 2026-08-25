from pathlib import Path

import pandas as pd

from services.research_store import ResearchStore
from tools.import_market_seed import build_seed


def test_seed_builder_retains_source_and_builds_bootstrappable_db(tmp_path):
    csv_path = tmp_path / "SPY-source.csv"
    pd.DataFrame({
        "Date": ["2024-01-02", "2024-01-03"],
        "Open": [100.0, 101.0], "High": [101.0, 102.0], "Low": [99.0, 100.0],
        "Close": [100.5, 101.5], "Adj Close": [100.0, 101.0], "Volume": [1000, 1100],
    }).to_csv(csv_path, index=False)
    root = tmp_path / "seed"
    manifest = build_seed(
        [("SPY", csv_path)],
        db_path=root / "market_seed.db",
        raw_dir=root / "raw",
        provider="fixture-source",
        price_basis="adjusted",
        source_urls={"SPY": "https://example.invalid/SPY.csv"},
        license_note="fixture only",
        reset=True,
    )
    assert manifest["audit"]["rows"] == 2
    assert (root / "SEED_MANIFEST.json").exists()
    raw_files = [p for p in (root / "raw").iterdir() if p.is_file()]
    assert len(raw_files) == 1

    user_store = ResearchStore(tmp_path / "user.db", seed_db=root / "market_seed.db", raw_dir=tmp_path / "user-raw")
    assert len(user_store.read_price_history("SPY")) == 2
