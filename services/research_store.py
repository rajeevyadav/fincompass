"""Durable offline-first market-data store for FinCompass Model Lab.

The short-lived UI price cache remains separate. This store is the research
system of record: seed data are copied into a writable database on first run,
normal refreshes request only a small overlap after the latest local date, and
historical corrections are retained in a revision ledger before replacement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

import pandas as pd

from config import BASE_DIR, DATA_DIR
from forecasting.recipes import INSTRUMENTS

RESEARCH_SCHEMA_VERSION = "1.0.0-research-store1"
DEFAULT_SEED_DB = BASE_DIR / "datasets" / "market-seed" / "market_seed.db"
DEFAULT_SEED_RAW_DIR = BASE_DIR / "datasets" / "market-seed" / "raw"
DEFAULT_STORE_PATH = DATA_DIR / "research" / "market_research.db"
DEFAULT_RAW_DIR = DATA_DIR / "research" / "raw"

_NUMERIC_COLS = ("open", "high", "low", "close", "adj_close", "volume")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _none_if_nan(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    return value


def _same_number(a: Any, b: Any, *, rel_tol: float = 1e-10, abs_tol: float = 1e-10) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)
    except (TypeError, ValueError):
        return a == b


def _canonical_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", *_NUMERIC_COLS])
    df = frame.copy()
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    lookup = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    date_col = lookup.get("date") or lookup.get("datetime") or lookup.get("timestamp")
    if date_col is None:
        # yfinance occasionally names the reset index after the ticker/time axis.
        first = df.columns[0]
        try:
            pd.to_datetime(df[first].head(3), errors="raise")
            date_col = first
        except Exception as exc:
            raise ValueError("market frame has no recognizable date column") from exc
    rename: Dict[Any, str] = {date_col: "date"}
    aliases = {
        "open": "open", "high": "high", "low": "low", "close": "close",
        "adj_close": "adj_close", "adjclose": "adj_close", "adjusted_close": "adj_close",
        "volume": "volume",
    }
    for normalized, original in lookup.items():
        if normalized in aliases:
            rename[original] = aliases[normalized]
    df = df.rename(columns=rename)
    for col in _NUMERIC_COLS:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_convert(None).dt.normalize()
    df = df.dropna(subset=["date"]).sort_values("date")
    df = df.drop_duplicates(subset=["date"], keep="last")
    return df[["date", *_NUMERIC_COLS]].reset_index(drop=True)


@dataclass(frozen=True)
class MergeResult:
    symbol: str
    inserted: int
    revised: int
    unchanged: int
    skipped: int
    earliest: Optional[str]
    latest: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "inserted": self.inserted,
            "revised": self.revised,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "earliest": self.earliest,
            "latest": self.latest,
        }


class ResearchStore:
    def __init__(
        self,
        path: str | Path = DEFAULT_STORE_PATH,
        *,
        seed_db: str | Path = DEFAULT_SEED_DB,
        raw_dir: str | Path = DEFAULT_RAW_DIR,
        bootstrap_seed: bool = True,
    ) -> None:
        self.path = Path(path)
        self.seed_db = Path(seed_db)
        self.raw_dir = Path(raw_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        bootstrapped = False
        if bootstrap_seed and not self.path.exists() and self.seed_db.exists():
            # SQLite may keep committed pages in a WAL sidecar. A plain file copy
            # can therefore produce a valid-looking but incomplete seed. Use the
            # SQLite backup API so the first-run clone is a transactionally
            # consistent snapshot of the seed database.
            source = sqlite3.connect(self.seed_db)
            target = sqlite3.connect(self.path)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            bootstrapped = True
        self._init_schema()
        if bootstrap_seed and self.seed_db.exists() and self.seed_db.resolve() != self.path.resolve():
            # A revised FinCompass package may introduce a bundled seed after a
            # user already has a writable research DB. Merge only missing seed
            # rows; never replace local rows, revisions, or experiment history.
            if not bootstrapped:
                self._merge_bundled_seed_missing_rows()
            self._copy_bundled_seed_raw_files()
        self.register_instruments(INSTRUMENTS)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _copy_bundled_seed_raw_files(self) -> None:
        seed_raw_dir = self.seed_db.parent / "raw"
        if not seed_raw_dir.exists():
            return
        for source in seed_raw_dir.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(seed_raw_dir)
            target = self.raw_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)

    def _merge_bundled_seed_missing_rows(self) -> None:
        """Add a newly shipped seed to an existing writable store without overwrites.

        This is deliberately append-only. Existing price rows always win,
        existing basis contracts are preserved, and experiment/revision tables
        are never copied from the seed. A seed digest makes repeat startups a
        no-op until a different bundled seed is shipped.
        """
        seed_digest = sha256(self.seed_db.read_bytes()).hexdigest()
        with self._connect() as conn:
            prior = conn.execute(
                "SELECT value FROM store_meta WHERE key='bundled_seed_sha256'"
            ).fetchone()
            if prior and prior["value"] == seed_digest:
                return
            conn.execute("ATTACH DATABASE ? AS bundled_seed", (str(self.seed_db),))
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO instruments
                       (symbol,name,asset_class,region,role,tradable,benchmark,provider_symbol,currency,enabled,metadata_json)
                       SELECT symbol,name,asset_class,region,role,tradable,benchmark,provider_symbol,currency,enabled,metadata_json
                       FROM bundled_seed.instruments"""
                )
                conn.execute(
                    """INSERT OR IGNORE INTO raw_sources
                       (sha256,file_name,source_url,provider,acquired_at,row_count,license_note,metadata_json)
                       SELECT sha256,file_name,source_url,provider,acquired_at,row_count,license_note,metadata_json
                       FROM bundled_seed.raw_sources"""
                )
                conn.execute(
                    """INSERT OR IGNORE INTO symbol_contracts
                       (symbol,price_basis,provider,first_recorded_at,last_verified_at,metadata_json)
                       SELECT symbol,price_basis,provider,first_recorded_at,last_verified_at,metadata_json
                       FROM bundled_seed.symbol_contracts"""
                )
                # Skip seed rows for any symbol whose existing contract uses a
                # different price basis. All other conflicts are date-keyed
                # INSERT OR IGNORE so local observations remain authoritative.
                conn.execute(
                    """INSERT OR IGNORE INTO price_bars
                       (symbol,date,open,high,low,close,adj_close,volume,currency,price_basis,provider,raw_sha256,fetch_id,verified_at,quality_flags)
                       SELECT p.symbol,p.date,p.open,p.high,p.low,p.close,p.adj_close,p.volume,p.currency,p.price_basis,p.provider,p.raw_sha256,NULL,p.verified_at,p.quality_flags
                       FROM bundled_seed.price_bars p
                       WHERE NOT EXISTS (
                           SELECT 1 FROM symbol_contracts c
                           WHERE c.symbol=p.symbol AND c.price_basis<>p.price_basis
                       )"""
                )
                conn.execute(
                    "INSERT OR REPLACE INTO store_meta(key,value) VALUES('bundled_seed_sha256',?)",
                    (seed_digest,),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO store_meta(key,value) VALUES('bundled_seed_merged_at',?)",
                    (_utc_now(),),
                )
                conn.commit()
            finally:
                conn.execute("DETACH DATABASE bundled_seed")

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS instruments (
                    symbol TEXT PRIMARY KEY,
                    name TEXT,
                    asset_class TEXT NOT NULL,
                    region TEXT,
                    role TEXT NOT NULL,
                    tradable INTEGER NOT NULL DEFAULT 1,
                    benchmark TEXT,
                    provider_symbol TEXT,
                    currency TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS fetch_runs (
                    fetch_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS raw_sources (
                    sha256 TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    source_url TEXT,
                    provider TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    row_count INTEGER,
                    license_note TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS symbol_contracts (
                    symbol TEXT PRIMARY KEY,
                    price_basis TEXT NOT NULL,
                    provider TEXT,
                    first_recorded_at TEXT NOT NULL,
                    last_verified_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS price_bars (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    adj_close REAL,
                    volume REAL,
                    currency TEXT,
                    price_basis TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    raw_sha256 TEXT,
                    fetch_id TEXT,
                    verified_at TEXT NOT NULL,
                    quality_flags TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (symbol, date),
                    FOREIGN KEY (symbol) REFERENCES instruments(symbol)
                );
                CREATE INDEX IF NOT EXISTS idx_price_bars_date ON price_bars(date);
                CREATE TABLE IF NOT EXISTS price_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    old_values_json TEXT NOT NULL,
                    new_values_json TEXT NOT NULL,
                    old_provider TEXT,
                    new_provider TEXT,
                    old_raw_sha256 TEXT,
                    new_raw_sha256 TEXT,
                    fetch_id TEXT,
                    reason TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    recipe_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model_id TEXT,
                    validation_tier TEXT,
                    settings_hash TEXT,
                    dataset_hash TEXT,
                    artifact_hash TEXT,
                    failed_gates_json TEXT NOT NULL DEFAULT '[]',
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    lineage_json TEXT NOT NULL DEFAULT '{}',
                    message TEXT
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO store_meta(key, value) VALUES('schema_version', ?)",
                (RESEARCH_SCHEMA_VERSION,),
            )

    def register_instruments(self, instruments: Mapping[str, Mapping[str, Any]]) -> None:
        with self._connect() as conn:
            for raw_symbol, meta in instruments.items():
                symbol = str(raw_symbol).strip().upper()
                if not symbol:
                    continue
                known = {
                    "name", "asset_class", "region", "role", "tradable", "benchmark",
                    "provider_symbol", "currency", "enabled",
                }
                extra = {k: v for k, v in dict(meta).items() if k not in known}
                conn.execute(
                    """INSERT INTO instruments
                       (symbol,name,asset_class,region,role,tradable,benchmark,provider_symbol,currency,enabled,metadata_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(symbol) DO UPDATE SET
                         name=excluded.name,asset_class=excluded.asset_class,region=excluded.region,
                         role=excluded.role,tradable=excluded.tradable,benchmark=excluded.benchmark,
                         provider_symbol=COALESCE(excluded.provider_symbol,instruments.provider_symbol),
                         currency=COALESCE(excluded.currency,instruments.currency),
                         enabled=excluded.enabled,metadata_json=excluded.metadata_json""",
                    (
                        symbol, meta.get("name"), str(meta.get("asset_class") or "unknown"),
                        meta.get("region"), str(meta.get("role") or "context"),
                        1 if meta.get("tradable", True) else 0,
                        str(meta.get("benchmark") or "").upper() or None,
                        meta.get("provider_symbol"), meta.get("currency"),
                        1 if meta.get("enabled", True) else 0,
                        json.dumps(extra, sort_keys=True),
                    ),
                )

    def instruments(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM instruments ORDER BY asset_class, region, symbol").fetchall()
        return [dict(r) for r in rows]

    def coverage(self, symbols: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        params: List[Any] = []
        where = ""
        if symbols:
            normalized = [str(s).upper() for s in symbols]
            where = "WHERE i.symbol IN (%s)" % ",".join("?" for _ in normalized)
            params.extend(normalized)
        query = f"""
            SELECT i.symbol,i.name,i.asset_class,i.region,i.role,i.tradable,i.benchmark,
                   MIN(p.date) AS earliest,MAX(p.date) AS latest,COUNT(p.date) AS rows,
                   MAX(p.verified_at) AS last_verified_at,
                   GROUP_CONCAT(DISTINCT p.provider) AS providers,
                   MAX(c.price_basis) AS price_basis
            FROM instruments i
            LEFT JOIN price_bars p ON p.symbol=i.symbol
            LEFT JOIN symbol_contracts c ON c.symbol=i.symbol
            {where}
            GROUP BY i.symbol
            ORDER BY i.asset_class,i.region,i.symbol
        """
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def latest_date(self, symbol: str) -> Optional[pd.Timestamp]:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(date) AS d FROM price_bars WHERE symbol=?", (symbol.upper(),)).fetchone()
        return pd.Timestamp(row["d"]) if row and row["d"] else None

    def earliest_date(self, symbol: str) -> Optional[pd.Timestamp]:
        with self._connect() as conn:
            row = conn.execute("SELECT MIN(date) AS d FROM price_bars WHERE symbol=?", (symbol.upper(),)).fetchone()
        return pd.Timestamp(row["d"]) if row and row["d"] else None

    def read_price_history(self, symbol: str, start: Any = None, end: Any = None) -> pd.DataFrame:
        clauses = ["symbol=?"]
        params: List[Any] = [symbol.upper()]
        if start is not None:
            clauses.append("date>=?")
            params.append(pd.Timestamp(start).date().isoformat())
        if end is not None:
            clauses.append("date<=?")
            params.append(pd.Timestamp(end).date().isoformat())
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date,open,high,low,close,adj_close,volume FROM price_bars WHERE "
                + " AND ".join(clauses) + " ORDER BY date",
                params,
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Adj Close", "Volume"])
        df = pd.DataFrame([dict(r) for r in rows])
        df["Date"] = pd.to_datetime(df.pop("date"))
        df = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low", "close": "Close",
            "adj_close": "Adj Close", "volume": "Volume",
        }).set_index("Date")
        # Current feature semantics consume Close. For adjusted-basis contracts,
        # Close is intentionally mapped to adjusted close so long-horizon returns
        # do not mix raw and adjusted series.
        with self._connect() as conn:
            contract = conn.execute("SELECT price_basis FROM symbol_contracts WHERE symbol=?", (symbol.upper(),)).fetchone()
        if contract and contract["price_basis"] == "adjusted" and df["Adj Close"].notna().any():
            df["Close"] = df["Adj Close"].where(df["Adj Close"].notna(), df["Close"])
        return df

    def record_raw_file(
        self,
        path: str | Path,
        *,
        provider: str,
        source_url: Optional[str] = None,
        license_note: Optional[str] = None,
        row_count: Optional[int] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        copy_into_store: bool = True,
    ) -> Dict[str, Any]:
        src = Path(path)
        digest = sha256(src.read_bytes()).hexdigest()
        dest = self.raw_dir / f"{digest[:12]}-{src.name}"
        if copy_into_store and src.resolve() != dest.resolve() and not dest.exists():
            shutil.copy2(src, dest)
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO raw_sources
                   (sha256,file_name,source_url,provider,acquired_at,row_count,license_note,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    digest, dest.name if copy_into_store else src.name, source_url, provider,
                    _utc_now(), row_count, license_note, json.dumps(dict(metadata or {}), sort_keys=True),
                ),
            )
        return {"sha256": digest, "file_name": dest.name if copy_into_store else src.name}

    def archive_frame_snapshot(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        fetch_id: str,
        provider: str,
        source_url: Optional[str] = None,
        license_note: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist the provider frame used by a refresh before normalization.

        yfinance and similar libraries expose a DataFrame rather than the raw
        wire payload.  This CSV is therefore the immutable provider-frame
        snapshot used by FinCompass for ingestion, with a SHA-256 registered in
        ``raw_sources``.  Re-running training never needs to re-download it.
        """
        safe_symbol = str(symbol).strip().upper().replace("/", "_").replace("^", "IDX-")
        directory = self.raw_dir / str(fetch_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe_symbol}.csv"
        frame.to_csv(path, index=True, index_label="Date")
        digest = sha256(path.read_bytes()).hexdigest()
        rel_name = str(path.relative_to(self.raw_dir))
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO raw_sources
                   (sha256,file_name,source_url,provider,acquired_at,row_count,license_note,metadata_json)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    digest, rel_name, source_url, provider, _utc_now(), int(len(frame)),
                    license_note, json.dumps(dict(metadata or {}), sort_keys=True),
                ),
            )
        return {"sha256": digest, "file_name": rel_name, "path": str(path)}

    def begin_fetch(self, provider: str, mode: str, metadata: Optional[Mapping[str, Any]] = None) -> str:
        started = _utc_now()
        payload = json.dumps(dict(metadata or {}), sort_keys=True)
        fetch_id = sha256(f"{provider}|{mode}|{started}|{payload}".encode("utf-8")).hexdigest()[:20]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO fetch_runs(fetch_id,provider,mode,started_at,status,metadata_json) VALUES(?,?,?,?,?,?)",
                (fetch_id, provider, mode, started, "running", payload),
            )
        return fetch_id

    def end_fetch(self, fetch_id: str, *, status: str, metadata: Optional[Mapping[str, Any]] = None) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT metadata_json FROM fetch_runs WHERE fetch_id=?", (fetch_id,)).fetchone()
            current = json.loads(row["metadata_json"] or "{}") if row else {}
            current.update(dict(metadata or {}))
            conn.execute(
                "UPDATE fetch_runs SET completed_at=?,status=?,metadata_json=? WHERE fetch_id=?",
                (_utc_now(), status, json.dumps(current, sort_keys=True), fetch_id),
            )

    def merge_price_frame(
        self,
        symbol: str,
        frame: pd.DataFrame,
        *,
        provider: str,
        price_basis: str = "adjusted",
        raw_sha256: Optional[str] = None,
        fetch_id: Optional[str] = None,
        currency: Optional[str] = None,
        allow_revisions: bool = True,
        repair: bool = False,
        revision_reason: str = "overlap_refresh",
    ) -> MergeResult:
        symbol = symbol.strip().upper()
        if price_basis not in {"adjusted", "raw"}:
            raise ValueError("price_basis must be adjusted or raw")
        df = _canonical_frame(frame)
        self.register_instruments({symbol: INSTRUMENTS.get(symbol, {"asset_class": "unknown", "role": "context", "tradable": True})})
        inserted = revised = unchanged = skipped = 0
        now = _utc_now()
        with self._connect() as conn:
            contract = conn.execute("SELECT * FROM symbol_contracts WHERE symbol=?", (symbol,)).fetchone()
            if contract and contract["price_basis"] != price_basis and not repair:
                raise ValueError(
                    f"price basis mismatch for {symbol}: existing={contract['price_basis']} incoming={price_basis}; use explicit repair"
                )
            if contract is None:
                conn.execute(
                    "INSERT INTO symbol_contracts(symbol,price_basis,provider,first_recorded_at,last_verified_at) VALUES(?,?,?,?,?)",
                    (symbol, price_basis, provider, now, now),
                )
            else:
                conn.execute(
                    "UPDATE symbol_contracts SET price_basis=?,provider=?,last_verified_at=? WHERE symbol=?",
                    (price_basis, provider, now, symbol),
                )
            for row in df.to_dict("records"):
                date = pd.Timestamp(row["date"]).date().isoformat()
                values = {k: _none_if_nan(row.get(k)) for k in _NUMERIC_COLS}
                if values["close"] is None and values["adj_close"] is None:
                    skipped += 1
                    continue
                existing = conn.execute("SELECT * FROM price_bars WHERE symbol=? AND date=?", (symbol, date)).fetchone()
                if existing is None:
                    conn.execute(
                        """INSERT INTO price_bars
                           (symbol,date,open,high,low,close,adj_close,volume,currency,price_basis,provider,raw_sha256,fetch_id,verified_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            symbol, date, values["open"], values["high"], values["low"], values["close"],
                            values["adj_close"], values["volume"], currency, price_basis, provider,
                            raw_sha256, fetch_id, now,
                        ),
                    )
                    inserted += 1
                    continue
                changed = any(not _same_number(existing[k], values[k]) for k in _NUMERIC_COLS)
                if not changed:
                    conn.execute(
                        "UPDATE price_bars SET verified_at=?,fetch_id=COALESCE(?,fetch_id) WHERE symbol=? AND date=?",
                        (now, fetch_id, symbol, date),
                    )
                    unchanged += 1
                    continue
                if not allow_revisions and not repair:
                    skipped += 1
                    continue
                old_values = {k: existing[k] for k in _NUMERIC_COLS}
                conn.execute(
                    """INSERT INTO price_revisions
                       (symbol,date,old_values_json,new_values_json,old_provider,new_provider,old_raw_sha256,new_raw_sha256,fetch_id,reason,observed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        symbol, date, json.dumps(old_values, sort_keys=True), json.dumps(values, sort_keys=True),
                        existing["provider"], provider, existing["raw_sha256"], raw_sha256, fetch_id,
                        "explicit_repair" if repair else revision_reason, now,
                    ),
                )
                conn.execute(
                    """UPDATE price_bars SET open=?,high=?,low=?,close=?,adj_close=?,volume=?,currency=?,
                       price_basis=?,provider=?,raw_sha256=?,fetch_id=?,verified_at=? WHERE symbol=? AND date=?""",
                    (
                        values["open"], values["high"], values["low"], values["close"], values["adj_close"],
                        values["volume"], currency, price_basis, provider, raw_sha256, fetch_id, now, symbol, date,
                    ),
                )
                revised += 1
        earliest = self.earliest_date(symbol)
        latest = self.latest_date(symbol)
        return MergeResult(
            symbol=symbol, inserted=inserted, revised=revised, unchanged=unchanged, skipped=skipped,
            earliest=earliest.date().isoformat() if earliest is not None else None,
            latest=latest.date().isoformat() if latest is not None else None,
        )

    def incremental_start(self, symbol: str, *, overlap_calendar_days: int = 10, initial_start: str = "2000-01-01") -> pd.Timestamp:
        latest = self.latest_date(symbol)
        if latest is None:
            return pd.Timestamp(initial_start)
        return (latest - pd.Timedelta(days=max(0, int(overlap_calendar_days)))).normalize()

    def update_incremental(
        self,
        symbols: Iterable[str],
        fetch_range: Callable[[str, pd.Timestamp, pd.Timestamp], Any],
        *,
        provider: str,
        overlap_calendar_days: int = 10,
        end: Any = None,
        price_basis: str = "adjusted",
        progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        end_ts = pd.Timestamp(end or datetime.now(timezone.utc).date()).tz_localize(None).normalize()
        normalized = [str(s).strip().upper() for s in symbols if str(s).strip()]
        total = len(normalized)
        fetch_id = self.begin_fetch(provider, "incremental", {"symbols": normalized, "overlap_calendar_days": overlap_calendar_days})
        results: List[Dict[str, Any]] = []
        errors: Dict[str, str] = {}
        try:
            for _idx, symbol in enumerate(normalized):
                if progress is not None:
                    try:
                        progress(_idx, total, symbol)
                    except Exception:
                        pass
                start = self.incremental_start(symbol, overlap_calendar_days=overlap_calendar_days)
                try:
                    payload = fetch_range(symbol, start, end_ts)
                    source_meta: Dict[str, Any] = {}
                    if isinstance(payload, tuple) and len(payload) == 2:
                        frame, source_meta = payload
                    else:
                        frame = payload
                    if frame is None or getattr(frame, "empty", True):
                        results.append({"symbol": symbol, "start": start.date().isoformat(), "status": "no_data"})
                        continue
                    effective_provider = str(source_meta.get("provider") or provider)
                    raw = self.archive_frame_snapshot(
                        frame,
                        symbol=symbol,
                        fetch_id=fetch_id,
                        provider=effective_provider,
                        source_url=source_meta.get("source_url"),
                        license_note=source_meta.get("license_note"),
                        metadata={
                            "provider_symbol": source_meta.get("provider_symbol"),
                            "requested_start": source_meta.get("requested_start") or start.date().isoformat(),
                            "requested_end": source_meta.get("requested_end") or end_ts.date().isoformat(),
                            "snapshot_kind": "provider_frame_used_for_ingestion",
                        },
                    )
                    incoming_basis = str(source_meta.get("price_basis") or price_basis)
                    try:
                        merge = self.merge_price_frame(
                            symbol, frame, provider=effective_provider,
                            price_basis=incoming_basis,
                            raw_sha256=raw["sha256"], fetch_id=fetch_id,
                            currency=source_meta.get("currency"), allow_revisions=True,
                        )
                        results.append({
                            "status": "ok", "requested_start": start.date().isoformat(),
                            "raw_sha256": raw["sha256"], "raw_file": raw["file_name"], **merge.to_dict(),
                        })
                    except ValueError as basis_exc:
                        if "price basis mismatch" not in str(basis_exc):
                            raise
                        # Documented recovery: the stored series uses a different
                        # price basis than the provider now returns (e.g. a raw seed
                        # vs an adjusted refresh). Re-fetch full history and rebuild
                        # this one symbol on the new basis; other symbols are untouched.
                        full = fetch_range(symbol, end_ts.normalize().replace(year=1990, month=1, day=1), end_ts)
                        fframe, fmeta = (full if isinstance(full, tuple) and len(full) == 2 else (full, {}))
                        if fframe is None or getattr(fframe, "empty", True):
                            results.append({"symbol": symbol, "status": "basis_rebuild_no_data"})
                            continue
                        fprov = str(fmeta.get("provider") or provider)
                        fraw = self.archive_frame_snapshot(
                            fframe, symbol=symbol, fetch_id=fetch_id, provider=fprov,
                            source_url=fmeta.get("source_url"), license_note=fmeta.get("license_note"),
                            metadata={"snapshot_kind": "price_basis_change_rebuild"},
                        )
                        merge = self.repair_symbol(
                            symbol, fframe, provider=fprov,
                            price_basis=str(fmeta.get("price_basis") or incoming_basis),
                            raw_sha256=fraw["sha256"], replace_existing=True,
                        )
                        results.append({
                            "status": "rebuilt_price_basis", "raw_sha256": fraw["sha256"],
                            "raw_file": fraw["file_name"], **merge.to_dict(),
                        })
                except Exception as exc:
                    errors[symbol] = f"{type(exc).__name__}: {exc}"
            self.end_fetch(fetch_id, status="complete" if not errors else "partial", metadata={"results": results, "errors": errors})
        except Exception:
            self.end_fetch(fetch_id, status="failed", metadata={"results": results, "errors": errors})
            raise
        return {"fetch_id": fetch_id, "provider": provider, "results": results, "errors": errors}

    def repair_symbol(
        self,
        symbol: str,
        frame: pd.DataFrame,
        *,
        provider: str,
        price_basis: str,
        raw_sha256: Optional[str] = None,
        replace_existing: bool = False,
    ) -> MergeResult:
        # Repair is deliberately separate from normal refresh. If a provider or
        # price basis changes, callers can explicitly clear and rebuild one
        # symbol while the revision ledger records overwritten overlapping rows.
        symbol = symbol.upper()
        if replace_existing:
            with self._connect() as conn:
                conn.execute("DELETE FROM symbol_contracts WHERE symbol=?", (symbol,))
                conn.execute("DELETE FROM price_bars WHERE symbol=?", (symbol,))
        return self.merge_price_frame(
            symbol, frame, provider=provider, price_basis=price_basis,
            raw_sha256=raw_sha256, repair=True, revision_reason="explicit_repair",
        )

    def revision_count(self, symbol: Optional[str] = None) -> int:
        with self._connect() as conn:
            if symbol:
                return int(conn.execute("SELECT COUNT(*) FROM price_revisions WHERE symbol=?", (symbol.upper(),)).fetchone()[0])
            return int(conn.execute("SELECT COUNT(*) FROM price_revisions").fetchone()[0])

    def register_experiment(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        now = _utc_now()
        recipe_id = str(payload.get("recipe_id") or "unknown")
        lineage = dict(payload.get("lineage") or {})
        seed = json.dumps({"recipe_id": recipe_id, "created_at": now, "lineage": lineage}, sort_keys=True)
        experiment_id = str(payload.get("experiment_id") or sha256(seed.encode("utf-8")).hexdigest()[:20])
        status = str(payload.get("status") or "training")
        failed = list(payload.get("failed_gates") or [])
        metrics = dict(payload.get("metrics") or {})
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO experiments
                   (experiment_id,created_at,updated_at,recipe_id,status,model_id,validation_tier,settings_hash,dataset_hash,artifact_hash,failed_gates_json,metrics_json,lineage_json,message)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(experiment_id) DO UPDATE SET
                     updated_at=excluded.updated_at,status=excluded.status,model_id=excluded.model_id,
                     validation_tier=excluded.validation_tier,settings_hash=excluded.settings_hash,
                     dataset_hash=excluded.dataset_hash,artifact_hash=excluded.artifact_hash,
                     failed_gates_json=excluded.failed_gates_json,metrics_json=excluded.metrics_json,
                     lineage_json=excluded.lineage_json,message=excluded.message""",
                (
                    experiment_id, str(payload.get("created_at") or now), now, recipe_id, status,
                    payload.get("model_id"), payload.get("validation_tier"), payload.get("settings_hash"),
                    payload.get("dataset_hash"), payload.get("artifact_hash"), json.dumps(failed, sort_keys=True),
                    json.dumps(metrics, sort_keys=True), json.dumps(lineage, sort_keys=True), payload.get("message"),
                ),
            )
        return self.get_experiment(experiment_id) or {"experiment_id": experiment_id}

    def mark_experiment_interrupted(self, experiment_id: str, message: str) -> bool:
        """Close a stale in-progress experiment without discarding its evidence.

        This is used when the persisted build slot is reclaimed after an
        interrupted process. Completed, rejected and already-failed experiments
        are deliberately left untouched.
        """
        now = _utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE experiments SET status='interrupted',updated_at=?,message=?
                   WHERE experiment_id=? AND status IN ('training','candidate')""",
                (now, str(message), str(experiment_id)),
            )
        return bool(cur.rowcount)

    def get_experiment(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
        if not row:
            return None
        return self._experiment_row(dict(row))

    def list_experiments(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM experiments ORDER BY created_at DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
        return [self._experiment_row(dict(r)) for r in rows]

    @staticmethod
    def _experiment_row(row: Dict[str, Any]) -> Dict[str, Any]:
        row["failed_gates"] = json.loads(row.pop("failed_gates_json") or "[]")
        row["metrics"] = json.loads(row.pop("metrics_json") or "{}")
        row["lineage"] = json.loads(row.pop("lineage_json") or "{}")
        return row

    def fetch_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT fetch_id,provider,mode,started_at,completed_at,status,metadata_json FROM fetch_runs ORDER BY started_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except Exception:
                item["metadata"] = {}
            out.append(item)
        return out

    def raw_sources(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sha256,file_name,source_url,provider,acquired_at,row_count,license_note,metadata_json FROM raw_sources ORDER BY acquired_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except Exception:
                item["metadata"] = {}
            out.append(item)
        return out

    def audit(self, symbols: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        coverage = self.coverage(symbols)
        populated = [x for x in coverage if int(x.get("rows") or 0) > 0]
        issues: List[Dict[str, Any]] = []
        with self._connect() as conn:
            bad = conn.execute(
                """SELECT symbol,date,open,high,low,close,adj_close,volume FROM price_bars
                   WHERE (close IS NULL AND adj_close IS NULL)
                      OR close < 0 OR adj_close < 0 OR volume < 0
                      OR (high IS NOT NULL AND low IS NOT NULL AND high < low)"""
            ).fetchall()
        for row in bad[:200]:
            issues.append(dict(row))
        return {
            "schema_version": RESEARCH_SCHEMA_VERSION,
            "database": str(self.path),
            "symbols_catalogued": len(coverage),
            "symbols_with_data": len(populated),
            "rows": sum(int(x.get("rows") or 0) for x in coverage),
            "revisions": self.revision_count(),
            "quality_issue_count": len(bad),
            "quality_issues": issues,
            "coverage": coverage,
        }


research_store = ResearchStore()
