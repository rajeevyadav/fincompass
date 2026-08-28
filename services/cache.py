"""FinCompass SQLite cache v2.

The cache is part of model integrity, not just performance: scores carry a
scoring-engine version, so methodology changes invalidate old cached scores
instead of silently mixing engines in the same screener.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import (
    DB_PATH,
    DATA_SCHEMA_VERSION,
    FUNDAMENTALS_CACHE_HOURS,
    PRICE_CACHE_HOURS,
    MACRO_CACHE_HOURS,
    SCORING_ENGINE_VERSION,
    SCREENER_JOB_STALE_MINUTES,
)


def _now() -> datetime:
    # Keep naive UTC for compatibility with v1 rows already stored that way.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            # Convert aware timestamps to naive UTC for comparison with old rows.
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (TypeError, ValueError):
        return None


class Cache:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS fundamentals (
                    ticker TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    source TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scores (
                    ticker TEXT PRIMARY KEY,
                    composite REAL,
                    label TEXT,
                    pillars_json TEXT,
                    name TEXT,
                    sector TEXT,
                    industry TEXT,
                    market_cap REAL,
                    source TEXT,
                    updated_at TEXT NOT NULL,
                    engine_version TEXT,
                    result_json TEXT
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    ticker TEXT,
                    period TEXT,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (ticker, period)
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
            # Safe migration from v1 DBs created before the two score columns.
            cols = self._columns(conn, "scores")
            if "engine_version" not in cols:
                conn.execute("ALTER TABLE scores ADD COLUMN engine_version TEXT")
            if "result_json" not in cols:
                conn.execute("ALTER TABLE scores ADD COLUMN result_json TEXT")

    # ------------------------------------------------------------------
    # Fundamentals
    # ------------------------------------------------------------------
    def get_fundamentals(self, ticker: str, max_age_hours: int = FUNDAMENTALS_CACHE_HOURS) -> Optional[Dict[str, Any]]:
        ticker = ticker.upper()
        with self._get_conn() as conn:
            row = conn.execute("SELECT data_json, updated_at FROM fundamentals WHERE ticker = ?", (ticker,)).fetchone()
            if not row:
                return None
            updated = _parse_dt(row["updated_at"])
            if updated is None or _now() - updated > timedelta(hours=max_age_hours):
                return None
            data = json.loads(row["data_json"])
            if data.get("_data_schema_version") != DATA_SCHEMA_VERSION:
                return None
            return data

    def set_fundamentals(self, ticker: str, data: Dict[str, Any]):
        ticker = ticker.upper()
        data = dict(data)
        data["_data_schema_version"] = DATA_SCHEMA_VERSION
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO fundamentals (ticker, data_json, source, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (ticker, json.dumps(data), data.get("source"), _now().isoformat()),
            )

    def get_all_fundamentals(self, max_age_hours: Optional[int] = FUNDAMENTALS_CACHE_HOURS) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT ticker, data_json, updated_at FROM fundamentals").fetchall()
        cutoff = _now() - timedelta(hours=max_age_hours) if max_age_hours is not None else None
        out: List[Dict[str, Any]] = []
        for row in rows:
            updated = _parse_dt(row["updated_at"])
            if cutoff is not None and (updated is None or updated < cutoff):
                continue
            try:
                d = json.loads(row["data_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if d.get("_data_schema_version") != DATA_SCHEMA_VERSION:
                continue
            d.setdefault("ticker", row["ticker"])
            out.append(d)
        return out

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------
    def _score_row_to_result(self, row: sqlite3.Row) -> Optional[Dict[str, Any]]:
        if row["engine_version"] != SCORING_ENGINE_VERSION:
            return None
        if row["result_json"]:
            try:
                result = json.loads(row["result_json"])
                result.setdefault("ticker", row["ticker"])
                result.setdefault("engine_version", row["engine_version"])
                result.setdefault("updated_at", row["updated_at"])
                return result
            except (TypeError, json.JSONDecodeError):
                pass
        # v2 rows should have result_json, but keep a defensive fallback.
        return {
            "ticker": row["ticker"],
            "composite": row["composite"],
            "label": row["label"],
            "pillars": json.loads(row["pillars_json"] or "{}"),
            "name": row["name"],
            "sector": row["sector"],
            "industry": row["industry"],
            "market_cap": row["market_cap"],
            "source": row["source"],
            "engine_version": row["engine_version"],
            "updated_at": row["updated_at"],
        }

    def get_score(self, ticker: str, max_age_hours: int = FUNDAMENTALS_CACHE_HOURS) -> Optional[Dict[str, Any]]:
        ticker = ticker.upper()
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM scores WHERE ticker = ?", (ticker,)).fetchone()
        if not row:
            return None
        updated = _parse_dt(row["updated_at"])
        if updated is None or _now() - updated > timedelta(hours=max_age_hours):
            return None
        return self._score_row_to_result(row)

    def set_score(self, ticker: str, result: Dict[str, Any]):
        ticker = ticker.upper()
        result = dict(result)
        result["ticker"] = ticker
        result["engine_version"] = SCORING_ENGINE_VERSION
        updated_at = _now().isoformat()
        result["updated_at"] = updated_at
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO scores
                   (ticker, composite, label, pillars_json, name, sector, industry,
                    market_cap, source, updated_at, engine_version, result_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    result["composite"],
                    result["label"],
                    json.dumps(result.get("pillars", {})),
                    result.get("name"),
                    result.get("sector"),
                    result.get("industry"),
                    result.get("market_cap"),
                    result.get("source"),
                    updated_at,
                    SCORING_ENGINE_VERSION,
                    json.dumps(result),
                ),
            )

    def get_all_scores(self, max_age_hours: Optional[int] = FUNDAMENTALS_CACHE_HOURS) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM scores ORDER BY composite DESC").fetchall()
        cutoff = _now() - timedelta(hours=max_age_hours) if max_age_hours is not None else None
        out: List[Dict[str, Any]] = []
        for row in rows:
            if row["engine_version"] != SCORING_ENGINE_VERSION:
                continue
            updated = _parse_dt(row["updated_at"])
            if cutoff is not None and (updated is None or updated < cutoff):
                continue
            result = self._score_row_to_result(row)
            if result:
                out.append(result)
        return out

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------
    def get_price_history(self, ticker: str, period: str, max_age_hours: int = PRICE_CACHE_HOURS):
        ticker = ticker.upper()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT data_json, updated_at FROM price_history WHERE ticker = ? AND period = ?",
                (ticker, period),
            ).fetchone()
        if not row:
            return None
        updated = _parse_dt(row["updated_at"])
        if updated is None or _now() - updated > timedelta(hours=max_age_hours):
            return None
        import io
        import pandas as pd
        # pandas 3.x no longer treats a bare JSON string as data (it's read as a
        # path); wrap the cached JSON in a text buffer.
        df = pd.read_json(io.StringIO(row["data_json"]))
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
        return df

    def set_price_history(self, ticker: str, period: str, df):
        ticker = ticker.upper()
        df_reset = df.reset_index()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO price_history (ticker, period, data_json, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (ticker, period, df_reset.to_json(date_format="iso"), _now().isoformat()),
            )

    # ------------------------------------------------------------------
    # Generic metadata with TTL
    # ------------------------------------------------------------------
    def get_meta_json(self, key: str, max_age_hours: Optional[int] = None) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return None
        updated_s = payload.get("_updated_at")
        if max_age_hours is not None:
            updated = _parse_dt(updated_s)
            if updated is None or _now() - updated > timedelta(hours=max_age_hours):
                return None
        return {k: v for k, v in payload.items() if k != "_updated_at"}

    def set_meta_json(self, key: str, data: Dict[str, Any]):
        payload = {**data, "_updated_at": _now().isoformat()}
        with self._get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(payload)))

    def get_macro(self, max_age_hours: int = MACRO_CACHE_HOURS) -> Optional[Dict[str, Any]]:
        return self.get_meta_json("macro", max_age_hours=max_age_hours)

    def set_macro(self, data: Dict[str, Any]):
        self.set_meta_json("macro", data)

    def get_commodity(self, sector: str, max_age_hours: int = MACRO_CACHE_HOURS) -> Optional[Dict[str, Any]]:
        return self.get_meta_json(f"commodity:{sector}", max_age_hours=max_age_hours)

    def set_commodity(self, sector: str, data: Dict[str, Any]):
        self.set_meta_json(f"commodity:{sector}", data)

    # ------------------------------------------------------------------
    # Background screener refresh coordination (SQLite-shared across workers)
    # ------------------------------------------------------------------
    def claim_screener_refresh(self, total: int, companies_total: Optional[int] = None) -> Tuple[bool, Dict[str, Any]]:
        now = _now()
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM meta WHERE key = 'screener_refresh'").fetchone()
            state: Dict[str, Any] = {}
            if row:
                try:
                    state = json.loads(row["value"])
                except (TypeError, json.JSONDecodeError):
                    state = {}
            if state.get("status") == "running":
                updated = _parse_dt(state.get("updated_at"))
                if updated and now - updated < timedelta(minutes=SCREENER_JOB_STALE_MINUTES):
                    conn.commit()
                    return False, state
            state = {
                "status": "running",
                "phase": "fetch",
                "total": int(total),
                "companies_total": int(companies_total if companies_total is not None else total),
                "completed": 0,
                "failures": 0,
                "started_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "message": "Refreshing fundamentals",
            }
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('screener_refresh', ?)",
                (json.dumps(state),),
            )
            conn.commit()
            return True, state

    def update_screener_refresh(self, **changes) -> Dict[str, Any]:
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM meta WHERE key = 'screener_refresh'").fetchone()
            state: Dict[str, Any] = {}
            if row:
                try:
                    state = json.loads(row["value"])
                except (TypeError, json.JSONDecodeError):
                    state = {}
            state.update(changes)
            state["updated_at"] = _now().isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('screener_refresh', ?)",
                (json.dumps(state),),
            )
            conn.commit()
        return state

    def get_screener_refresh(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'screener_refresh'").fetchone()
        if not row:
            return {"status": "idle", "phase": "idle", "total": 0, "completed": 0, "failures": 0}
        try:
            return json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return {"status": "unknown"}

    # ------------------------------------------------------------------
    # In-app forecast model build coordination (SQLite-shared across workers)
    # ------------------------------------------------------------------
    def claim_model_build(self, total: int, stale_minutes: int = 120) -> Tuple[bool, Dict[str, Any]]:
        now = _now()
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM meta WHERE key = 'model_build'").fetchone()
            state: Dict[str, Any] = {}
            if row:
                try:
                    state = json.loads(row["value"])
                except (TypeError, json.JSONDecodeError):
                    state = {}
            reclaimed: Dict[str, Any] = {}
            if state.get("status") == "running":
                updated = _parse_dt(state.get("updated_at"))
                if updated and now - updated < timedelta(minutes=stale_minutes):
                    conn.commit()
                    return False, state
                reclaimed = {
                    "reclaimed_experiment_id": state.get("experiment_id"),
                    "reclaimed_recipe_id": state.get("recipe_id"),
                    "reclaimed_updated_at": state.get("updated_at"),
                }
            state = {
                "status": "running",
                "phase": "fetch",
                "total": int(total),
                "completed": 0,
                "failures": 0,
                "model_id": None,
                "validation_tier": None,
                "gate_passed": None,
                "started_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "message": "Starting model build",
                **{k: v for k, v in reclaimed.items() if v is not None},
            }
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('model_build', ?)",
                (json.dumps(state),),
            )
            conn.commit()
            return True, state

    def update_model_build(self, **changes) -> Dict[str, Any]:
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT value FROM meta WHERE key = 'model_build'").fetchone()
            state: Dict[str, Any] = {}
            if row:
                try:
                    state = json.loads(row["value"])
                except (TypeError, json.JSONDecodeError):
                    state = {}
            state.update(changes)
            state["updated_at"] = _now().isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('model_build', ?)",
                (json.dumps(state),),
            )
            conn.commit()
        return state

    def get_model_build(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'model_build'").fetchone()
        if not row:
            return {"status": "idle", "phase": "idle", "total": 0, "completed": 0, "failures": 0}
        try:
            return json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            return {"status": "unknown"}

    def clear_old(self, days: int = 7):
        cutoff = (_now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            conn.execute("DELETE FROM fundamentals WHERE updated_at < ?", (cutoff,))
            conn.execute("DELETE FROM scores WHERE updated_at < ?", (cutoff,))
            conn.execute("DELETE FROM price_history WHERE updated_at < ?", (cutoff,))


cache = Cache()
