from pathlib import Path
import shutil

import pytest

from services.research_store import ResearchStore
from tools.build_builtin_seed import _load_goog, _load_msft


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "datasets" / "market-seed" / "source-originals"

# The market-seed package is a PRIVATE, local-only asset (see PRIVATE-DATA-NOTICE
# and .gitignore) and is intentionally absent from the public repository / CI.
# These tests validate that real seed when it is present locally; they skip on a
# clean clone so public CI stays green without ever shipping the private data.
pytestmark = pytest.mark.skipif(
    not (SOURCE_ROOT.exists() and (ROOT / "datasets" / "market-seed" / "market_seed.db").exists()),
    reason="requires the private market-seed data (local only; absent in public CI)",
)


def test_builtin_source_samples_are_real_dated_market_series():
    goog = _load_goog(SOURCE_ROOT / "matplotlib-goog.npz")
    msft = _load_msft(SOURCE_ROOT / "pmdarima-msft.tar.gz")
    assert len(goog) == 1047
    assert goog.index.min().date().isoformat() == "2004-08-19"
    assert goog.index.max().date().isoformat() == "2008-10-14"
    assert len(msft) == 7983
    assert msft.index.min().date().isoformat() == "1986-03-13"
    assert msft.index.max().date().isoformat() == "2017-11-10"
    assert float(goog["Close"].iloc[0]) > 0
    assert float(msft["Close"].iloc[-1]) > 0


def test_packaged_seed_bootstraps_without_mutating_seed(tmp_path):
    seed_db = ROOT / "datasets" / "market-seed" / "market_seed.db"
    assert seed_db.is_file(), "packaged market_seed.db must be built before release verification"
    digest_before = seed_db.read_bytes()
    user_db = tmp_path / "market_research.db"
    user_raw = tmp_path / "raw"
    store = ResearchStore(user_db, seed_db=seed_db, raw_dir=user_raw, bootstrap_seed=True)
    assert len(store.read_price_history("GOOG")) == 1047
    assert len(store.read_price_history("MSFT")) == 7983
    assert seed_db.read_bytes() == digest_before
    assert len([p for p in user_raw.rglob("*") if p.is_file()]) >= 2
