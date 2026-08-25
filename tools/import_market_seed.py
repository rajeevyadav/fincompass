"""Build/import the distributable FinCompass Model Lab seed database.

Each input file is retained verbatim under datasets/market-seed/raw and its
SHA-256 is recorded before rows are normalized into market_seed.db.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.research_store import ResearchStore  # noqa: E402

DEFAULT_SEED_ROOT = ROOT / "datasets" / "market-seed"
DEFAULT_SEED_DB = DEFAULT_SEED_ROOT / "market_seed.db"
DEFAULT_SEED_RAW = DEFAULT_SEED_ROOT / "raw"


def _read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if isinstance(df.columns, pd.MultiIndex):
        raise ValueError(f"multi-index CSV requires prior per-symbol split: {path}")
    date_col = next((c for c in df.columns if str(c).strip().lower() in {"date", "datetime", "timestamp"}), None)
    if date_col is None:
        raise ValueError(f"CSV has no Date column: {path}")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    return df


def import_symbol_file(
    store: ResearchStore,
    symbol: str,
    path: Path,
    *,
    provider: str,
    source_url: Optional[str] = None,
    license_note: Optional[str] = None,
    price_basis: str = "adjusted",
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    frame = _read_csv(path)
    raw = store.record_raw_file(
        path,
        provider=provider,
        source_url=source_url,
        license_note=license_note,
        row_count=len(frame),
        metadata={"symbol": symbol.upper(), "seed_input": True, **dict(metadata or {})},
        copy_into_store=True,
    )
    merged = store.merge_price_frame(
        symbol,
        frame,
        provider=provider,
        price_basis=price_basis,
        raw_sha256=raw["sha256"],
        revision_reason="seed_import",
    )
    return {"symbol": symbol.upper(), "source_file": path.name, "raw": raw, "merge": merged.to_dict()}


def build_seed(
    entries: Iterable[Tuple[str, Path]],
    *,
    db_path: Path = DEFAULT_SEED_DB,
    raw_dir: Path = DEFAULT_SEED_RAW,
    provider: str = "seed-import",
    price_basis: str = "adjusted",
    source_urls: Optional[Mapping[str, str]] = None,
    license_note: Optional[str] = None,
    reset: bool = False,
) -> Dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    if reset and db_path.exists():
        db_path.unlink()
    store = ResearchStore(db_path, raw_dir=raw_dir, bootstrap_seed=False)
    imported: List[Dict[str, Any]] = []
    for symbol, path in entries:
        imported.append(import_symbol_file(
            store,
            symbol,
            path,
            provider=provider,
            source_url=(source_urls or {}).get(symbol.upper()),
            license_note=license_note,
            price_basis=price_basis,
        ))
    audit = store.audit()
    manifest = {
        "schema_version": "1.0.0-market-seed1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": db_path.name,
        "provider": provider,
        "price_basis": price_basis,
        "license_note": license_note,
        "imports": imported,
        "audit": audit,
    }
    manifest_path = db_path.parent / "SEED_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return manifest


def _parse_entry(value: str) -> Tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("entry must be SYMBOL=/path/to/file.csv")
    symbol, raw = value.split("=", 1)
    path = Path(raw).expanduser().resolve()
    if not symbol.strip() or not path.exists():
        raise argparse.ArgumentTypeError(f"invalid seed entry: {value}")
    return symbol.strip().upper(), path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the FinCompass offline market seed")
    parser.add_argument("--entry", action="append", type=_parse_entry, required=True, help="SYMBOL=/path/to/file.csv")
    parser.add_argument("--db", type=Path, default=DEFAULT_SEED_DB)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_SEED_RAW)
    parser.add_argument("--provider", default="seed-import")
    parser.add_argument("--price-basis", choices=["adjusted", "raw"], default="adjusted")
    parser.add_argument("--license-note", default=None)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    result = build_seed(
        args.entry,
        db_path=args.db,
        raw_dir=args.raw_dir,
        provider=args.provider,
        price_basis=args.price_basis,
        license_note=args.license_note,
        reset=args.reset,
    )
    print(json.dumps({
        "database": str(args.db),
        "symbols_with_data": result["audit"]["symbols_with_data"],
        "rows": result["audit"]["rows"],
    }, indent=2))


if __name__ == "__main__":
    main()
