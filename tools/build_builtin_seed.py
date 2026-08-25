"""Build the distributable offline Model Lab bootstrap market seed.

The repository does not redistribute a bulk vendor market-data dump.  Instead it
ships two small real historical series that are already distributed as sample
data by installed scientific Python packages.  They exist solely to prove that
a fresh FinCompass checkout can exercise the complete local Model Lab pipeline
without a network connection.

The original source bytes are retained and SHA-256 bound in the seed database.
GOOG and MSFT are deliberately marked research-only through the recipe contract;
this seed is not evidence of current market skill and is never sufficient for a
live-eligible model by itself.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tarfile
from typing import Any, Dict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = ROOT / "datasets" / "market-seed"
SOURCE_ROOT = SEED_ROOT / "source-originals"
LICENSE_ROOT = SEED_ROOT / "licenses"
SEED_DB = SEED_ROOT / "market_seed.db"
SEED_RAW = SEED_ROOT / "raw"
SEED_MANIFEST = SEED_ROOT / "SEED_MANIFEST.json"
SEED_MANIFEST_SHA = SEED_ROOT / "SEED_MANIFEST.sha256"

# Imported after ROOT is known so this tool also works when called directly.
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_store import ResearchStore  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_goog(path: Path) -> pd.DataFrame:
    with np.load(path, allow_pickle=False) as payload:
        if "price_data" not in payload:
            raise ValueError("matplotlib GOOG sample has no price_data array")
        rows = payload["price_data"]
    required = {"date", "open", "high", "low", "close", "volume", "adj_close"}
    if not required.issubset(set(rows.dtype.names or ())):
        raise ValueError("matplotlib GOOG sample schema changed")
    frame = pd.DataFrame({
        "Date": pd.to_datetime(rows["date"]),
        "Open": rows["open"],
        "High": rows["high"],
        "Low": rows["low"],
        "Close": rows["close"],
        "Adj Close": rows["adj_close"],
        "Volume": rows["volume"],
    }).set_index("Date")
    return frame.sort_index()


def _load_msft(path: Path) -> pd.DataFrame:
    with tarfile.open(path, "r:gz") as archive:
        members = [m for m in archive.getmembers() if m.isfile() and Path(m.name).name.lower() == "msft.csv"]
        if len(members) != 1:
            raise ValueError("pmdarima MSFT archive must contain exactly one msft.csv")
        extracted = archive.extractfile(members[0])
        if extracted is None:
            raise ValueError("could not read pmdarima MSFT sample")
        raw = extracted.read()
    frame = pd.read_csv(io.BytesIO(raw))
    if "Date" not in frame.columns:
        raise ValueError("pmdarima MSFT sample has no Date column")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
    return frame.set_index("Date").sort_index()


def _source_record(path: Path, *, provider: str, source_url: str, license_file: Path, notes: str) -> Dict[str, Any]:
    return {
        "file": str(path.relative_to(SEED_ROOT)),
        "sha256": _sha(path),
        "provider": provider,
        "source_url": source_url,
        "license_file": str(license_file.relative_to(SEED_ROOT)),
        "license_sha256": _sha(license_file),
        "notes": notes,
    }


def build_builtin_seed(*, reset: bool = True) -> Dict[str, Any]:
    goog_path = SOURCE_ROOT / "matplotlib-goog.npz"
    msft_path = SOURCE_ROOT / "pmdarima-msft.tar.gz"
    mpl_license = LICENSE_ROOT / "MATPLOTLIB-LICENSE.txt"
    pmd_metadata = LICENSE_ROOT / "PMDARIMA-PACKAGE-METADATA.txt"
    for required in (goog_path, msft_path, mpl_license, pmd_metadata):
        if not required.is_file():
            raise FileNotFoundError(f"required bundled seed source missing: {required}")

    if reset:
        for path in (SEED_DB, SEED_DB.with_name(SEED_DB.name + "-wal"), SEED_DB.with_name(SEED_DB.name + "-shm"), SEED_MANIFEST, SEED_MANIFEST_SHA):
            if path.exists():
                path.unlink()
        if SEED_RAW.exists():
            shutil.rmtree(SEED_RAW)
    SEED_RAW.mkdir(parents=True, exist_ok=True)

    store = ResearchStore(SEED_DB, raw_dir=SEED_RAW, bootstrap_seed=False)
    fetch_id = store.begin_fetch(
        "bundled-scientific-samples",
        "seed_build",
        {"purpose": "offline Model Lab acceptance bootstrap", "live_eligible": False},
    )
    imports: list[Dict[str, Any]] = []
    try:
        goog = _load_goog(goog_path)
        goog_raw = store.record_raw_file(
            goog_path,
            provider="matplotlib-sample-data",
            source_url="https://github.com/matplotlib/matplotlib/tree/main/lib/matplotlib/mpl-data/sample_data",
            license_note="Distributed as Matplotlib sample data; Matplotlib license retained under datasets/market-seed/licenses.",
            row_count=len(goog),
            metadata={
                "symbol": "GOOG",
                "seed_input": True,
                "purpose": "offline acceptance only",
                "original_format": "numpy npz structured array",
            },
        )
        goog_merge = store.merge_price_frame(
            "GOOG",
            goog,
            provider="matplotlib-sample-data",
            price_basis="adjusted",
            raw_sha256=goog_raw["sha256"],
            fetch_id=fetch_id,
            allow_revisions=False,
            revision_reason="builtin_seed",
        )
        imports.append({"symbol": "GOOG", "raw": goog_raw, "merge": goog_merge.to_dict()})

        msft = _load_msft(msft_path)
        msft_raw = store.record_raw_file(
            msft_path,
            provider="pmdarima-sample-data",
            source_url="https://alkaline-ml.com/pmdarima/modules/generated/pmdarima.datasets.load_msft.html",
            license_note=(
                "Distributed with the pmdarima package (package metadata declares MIT). "
                "pmdarima documents the series as sourced from the Kaggle price-volume US stocks/ETFs dataset."
            ),
            row_count=len(msft),
            metadata={
                "symbol": "MSFT",
                "seed_input": True,
                "purpose": "offline acceptance only",
                "original_format": "tar.gz containing msft.csv",
                "upstream_attribution": "Kaggle price-volume data for US stocks and ETFs, as documented by pmdarima",
            },
        )
        msft_merge = store.merge_price_frame(
            "MSFT",
            msft,
            provider="pmdarima-sample-data",
            price_basis="raw",
            raw_sha256=msft_raw["sha256"],
            fetch_id=fetch_id,
            allow_revisions=False,
            revision_reason="builtin_seed",
        )
        imports.append({"symbol": "MSFT", "raw": msft_raw, "merge": msft_merge.to_dict()})
        store.end_fetch(fetch_id, status="complete", metadata={"imports": imports})
    except Exception as exc:
        store.end_fetch(fetch_id, status="failed", metadata={"error": f"{type(exc).__name__}: {exc}"})
        raise

    audit = store.audit(["GOOG", "MSFT"])
    audit["database"] = SEED_DB.name

    # Ship one stable SQLite file, not a main DB whose committed pages may still
    # live in a WAL sidecar. The writable user copy re-enables WAL automatically.
    conn = sqlite3.connect(SEED_DB, timeout=30)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or str(result[0]).lower() != "ok":
            raise RuntimeError(f"seed SQLite integrity_check failed: {result}")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    for sidecar in (SEED_DB.with_name(SEED_DB.name + "-wal"), SEED_DB.with_name(SEED_DB.name + "-shm")):
        if sidecar.exists() and sidecar.stat().st_size == 0:
            sidecar.unlink()
    manifest: Dict[str, Any] = {
        "schema_version": "market-seed-bootstrap1",
        "created_at": _utc_now(),
        "purpose": "offline Model Lab acceptance bootstrap; not a live-market model dataset",
        "live_eligible": False,
        "database": SEED_DB.name,
        "database_sha256": _sha(SEED_DB),
        "sources": [
            _source_record(
                goog_path,
                provider="matplotlib-sample-data",
                source_url="https://github.com/matplotlib/matplotlib/tree/main/lib/matplotlib/mpl-data/sample_data",
                license_file=mpl_license,
                notes="GOOG daily OHLCV/adjusted-close sample, 2004-08-19 through 2008-10-14.",
            ),
            _source_record(
                msft_path,
                provider="pmdarima-sample-data",
                source_url="https://alkaline-ml.com/pmdarima/modules/generated/pmdarima.datasets.load_msft.html",
                license_file=pmd_metadata,
                notes="MSFT daily OHLCV sample distributed by pmdarima; raw close basis retained.",
            ),
        ],
        "imports": imports,
        "audit": audit,
        "bootstrap_recipe": "bootstrap-real-1m",
        "limitations": [
            "The bootstrap corpus is intentionally small and historical.",
            "It exists to verify offline training, validation, persistence and restart behavior.",
            "It must not be represented as evidence of current or cross-asset market skill.",
            "Live-eligible recipes require operator-acquired local market history and independent validation gates.",
        ],
    }
    SEED_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    SEED_MANIFEST_SHA.write_text(f"{_sha(SEED_MANIFEST)}  {SEED_MANIFEST.name}\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the bundled FinCompass offline bootstrap market seed")
    parser.add_argument("--no-reset", action="store_true", help="merge into an existing seed instead of rebuilding it")
    args = parser.parse_args()
    manifest = build_builtin_seed(reset=not args.no_reset)
    print(json.dumps({
        "database": str(SEED_DB),
        "database_sha256": manifest["database_sha256"],
        "symbols_with_data": manifest["audit"]["symbols_with_data"],
        "rows": manifest["audit"]["rows"],
        "bootstrap_recipe": manifest["bootstrap_recipe"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
