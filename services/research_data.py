"""Model Lab market-data acquisition, raw retention and refresh coordination."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import pandas as pd

from config import BASE_DIR, DATA_DIR
from forecasting.recipes import default_update_symbols
from services.data_fetcher import fetcher
from services.research_store import ResearchStore, research_store

REFRESH_STATE_PATH = DATA_DIR / "research" / "refresh_state.json"
BUNDLED_SEED_DIR = BASE_DIR / "datasets" / "market-seed"
BUNDLED_SEED_DB = BUNDLED_SEED_DIR / "market_seed.db"
BUNDLED_SEED_RAW = BUNDLED_SEED_DIR / "raw"

# One canonical catalogue-driven refresh universe. The recipe module owns the
# definition so data acquisition cannot silently drift away from Model Lab.
DEFAULT_REFRESH_SYMBOLS = default_update_symbols()

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state() -> Dict[str, Any]:
    if not REFRESH_STATE_PATH.exists():
        return {"status": "idle", "updated_at": None}
    try:
        value = json.loads(REFRESH_STATE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"status": "unknown"}
    except Exception:
        return {"status": "unknown"}


def _write_state(payload: Mapping[str, Any]) -> Dict[str, Any]:
    REFRESH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = dict(payload)
    state["updated_at"] = _now()
    tmp = REFRESH_STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(REFRESH_STATE_PATH)
    return state


def refresh_status() -> Dict[str, Any]:
    state = _read_state()
    if state.get("status") == "running" and (_thread is None or not _thread.is_alive()):
        # A restart/interruption cannot roll back committed SQLite rows. Mark the
        # coordinator state honestly and allow the next refresh to resume from
        # latest local dates.
        state = _write_state({
            **state,
            "status": "interrupted",
            "message": "Previous refresh was interrupted; retained rows are safe. Start refresh again to resume incrementally.",
        })
    return state


def refresh_market_data(
    symbols: Optional[Sequence[str]] = None,
    *,
    store: ResearchStore = research_store,
    overlap_calendar_days: int = 10,
    end: Any = None,
) -> Dict[str, Any]:
    """Refresh only the local tail needed for continuity.

    ``ResearchStore.update_incremental`` creates the fetch ledger, archives the
    exact provider DataFrame used for ingestion, computes its SHA-256, then
    merges/deduplicates it.  Keeping those steps in one transaction boundary
    avoids double snapshots and makes interruption recovery deterministic.
    """
    requested = [str(x).strip().upper() for x in (symbols or DEFAULT_REFRESH_SYMBOLS) if str(x).strip()]

    def fetch_range(symbol: str, start: pd.Timestamp, end_ts: pd.Timestamp):
        return fetcher.get_price_history_range(symbol, start, end_ts)

    return store.update_incremental(
        requested,
        fetch_range,
        provider="fincompass-provider-chain",
        overlap_calendar_days=overlap_calendar_days,
        end=end,
        price_basis="adjusted",
    )

def _refresh_worker(symbols: Optional[Sequence[str]], overlap_calendar_days: int) -> None:
    try:
        result = refresh_market_data(symbols, overlap_calendar_days=overlap_calendar_days)
        errors = result.get("errors") or {}
        inserted = sum(int(x.get("inserted") or 0) for x in result.get("results") or [])
        revised = sum(int(x.get("revised") or 0) for x in result.get("results") or [])
        unchanged = sum(int(x.get("unchanged") or 0) for x in result.get("results") or [])
        _write_state({
            "status": "complete" if not errors else "partial",
            "started_at": _read_state().get("started_at"),
            "fetch_id": result.get("fetch_id"),
            "symbols": list(symbols) if symbols else DEFAULT_REFRESH_SYMBOLS,
            "inserted": inserted,
            "revised": revised,
            "unchanged": unchanged,
            "errors": errors,
            "message": "Incremental refresh completed; raw provider snapshots were retained locally.",
        })
    except Exception as exc:
        _write_state({
            "status": "failed",
            "started_at": _read_state().get("started_at"),
            "message": f"{type(exc).__name__}: {exc}",
        })
    finally:
        try:
            _lock.release()
        except RuntimeError:
            pass


def start_refresh(symbols: Optional[Sequence[str]] = None, *, overlap_calendar_days: int = 10) -> Dict[str, Any]:
    global _thread
    if not _lock.acquire(blocking=False):
        return {**refresh_status(), "started": False}
    requested = [str(x).strip().upper() for x in (symbols or DEFAULT_REFRESH_SYMBOLS) if str(x).strip()]
    _write_state({
        "status": "running",
        "started_at": _now(),
        "symbols": requested,
        "overlap_calendar_days": int(overlap_calendar_days),
        "message": "Refreshing only the local tail/overlap needed for incremental continuity.",
    })
    _thread = threading.Thread(
        target=_refresh_worker,
        args=(requested, int(overlap_calendar_days)),
        name="fincompass-research-refresh",
        daemon=True,
    )
    _thread.start()
    return {**_read_state(), "started": True}


def import_seed_directory(
    source_dir: str | Path,
    *,
    store: ResearchStore,
    provider: str,
    price_basis: str = "adjusted",
) -> Dict[str, Any]:
    """Import `{SYMBOL}.csv` files while retaining each exact source file."""
    source = Path(source_dir)
    if not source.is_dir():
        raise ValueError(f"seed directory not found: {source}")
    results = []
    errors: Dict[str, str] = {}
    fetch_id = store.begin_fetch(provider, "seed_import", {"source_dir": str(source)})
    for path in sorted(source.glob("*.csv")):
        symbol = path.stem.upper().replace("_", "-")
        try:
            frame = pd.read_csv(path)
            date_col = next((c for c in frame.columns if str(c).strip().lower() in {"date", "datetime", "timestamp"}), None)
            if date_col is None:
                raise ValueError("CSV has no Date column")
            frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
            frame = frame.dropna(subset=[date_col]).set_index(date_col)
            raw = store.record_raw_file(
                path,
                provider=provider,
                row_count=len(frame),
                license_note="Imported seed source; upstream terms must be retained with the source package.",
                metadata={"symbol": symbol, "fetch_id": fetch_id, "price_basis": price_basis},
            )
            merged = store.merge_price_frame(
                symbol,
                frame,
                provider=provider,
                price_basis=price_basis,
                raw_sha256=raw["sha256"],
                fetch_id=fetch_id,
            )
            results.append(merged.to_dict())
        except Exception as exc:
            errors[path.name] = f"{type(exc).__name__}: {exc}"
    store.end_fetch(fetch_id, status="complete" if not errors else "partial", metadata={"results": results, "errors": errors})
    return {"fetch_id": fetch_id, "results": results, "errors": errors, "audit": store.audit()}


def build_bundled_seed(store: ResearchStore = research_store) -> Dict[str, Any]:
    """Create a transaction-consistent seed DB plus retained raw source files."""
    BUNDLED_SEED_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLED_SEED_RAW.mkdir(parents=True, exist_ok=True)
    tmp = BUNDLED_SEED_DB.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    src = sqlite3.connect(store.path)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(BUNDLED_SEED_DB)
    for path in store.raw_dir.rglob("*"):
        if path.is_file():
            relative = path.relative_to(store.raw_dir)
            target = BUNDLED_SEED_RAW / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.stat().st_size != path.stat().st_size:
                shutil.copy2(path, target)
    audit = store.audit()
    manifest = {
        "created_at": _now(),
        "database": BUNDLED_SEED_DB.name,
        "database_bytes": BUNDLED_SEED_DB.stat().st_size,
        "raw_files": len([p for p in BUNDLED_SEED_RAW.rglob("*") if p.is_file()]),
        "audit": {k: audit[k] for k in ["schema_version", "symbols_catalogued", "symbols_with_data", "rows", "revisions", "quality_issue_count"]},
    }
    (BUNDLED_SEED_DIR / "seed_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
