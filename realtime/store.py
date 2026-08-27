from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from config import DB_PATH


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class RealtimeStore:
    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS realtime_events (
                    event_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    ticker TEXT,
                    benchmark TEXT,
                    source_time TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    context_only INTEGER NOT NULL DEFAULT 0,
                    external_payload INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_realtime_events_scope_time ON realtime_events(scope_key, source_time DESC);
                CREATE INDEX IF NOT EXISTS idx_realtime_events_ticker_time ON realtime_events(ticker, source_time DESC);

                CREATE TABLE IF NOT EXISTS provider_checks (
                    source TEXT NOT NULL,
                    scope_key TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL,
                    last_success_at TEXT,
                    status TEXT NOT NULL,
                    message TEXT,
                    PRIMARY KEY(source, scope_key)
                );

                CREATE TABLE IF NOT EXISTS pending_labels (
                    label_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    benchmark TEXT NOT NULL,
                    base_model_id TEXT NOT NULL,
                    settings_fingerprint TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    observation_ts TEXT NOT NULL,
                    observation_date TEXT NOT NULL,
                    earliest_maturity TEXT NOT NULL,
                    anchor_probability REAL NOT NULL,
                    candidate_probability REAL NOT NULL,
                    features_json TEXT NOT NULL,
                    stock_entry_price REAL NOT NULL,
                    benchmark_entry_price REAL NOT NULL,
                    horizon_trading_days INTEGER NOT NULL,
                    excess_return_threshold REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    realized_label INTEGER,
                    resolved_at TEXT,
                    UNIQUE(ticker, base_model_id, settings_fingerprint, observation_date)
                );
                CREATE INDEX IF NOT EXISTS idx_pending_maturity ON pending_labels(status, earliest_maturity);

                CREATE TABLE IF NOT EXISTS adaptive_states (
                    state_key TEXT PRIMARY KEY,
                    base_model_id TEXT NOT NULL,
                    settings_fingerprint TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS adaptive_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    state_key TEXT NOT NULL,
                    observation_date TEXT NOT NULL,
                    anchor_probability REAL NOT NULL,
                    adaptive_probability REAL NOT NULL,
                    label INTEGER NOT NULL,
                    brier_anchor REAL NOT NULL,
                    brier_adaptive REAL NOT NULL,
                    log_anchor REAL NOT NULL,
                    log_adaptive REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_adaptive_perf_state_date ON adaptive_performance(state_key, observation_date DESC);

                CREATE TABLE IF NOT EXISTS live_snapshots (
                    snapshot_key TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    benchmark TEXT NOT NULL,
                    base_model_id TEXT NOT NULL,
                    settings_fingerprint TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def add_event(self, event: Dict[str, Any]) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO realtime_events
                (event_id,source,scope_key,event_type,ticker,benchmark,source_time,received_at,payload_json,context_only,external_payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["event_id"], event["source"], event["scope_key"], event["event_type"],
                    event.get("ticker"), event.get("benchmark"), event["source_time"], event.get("received_at") or _utcnow(),
                    json.dumps(event.get("payload") or {}, sort_keys=True), int(bool(event.get("context_only"))), int(bool(event.get("external_payload"))),
                ),
            )
            return cur.rowcount > 0

    def list_events(self, ticker: Optional[str] = None, limit: int = 50, public: bool = True) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        sql = "SELECT * FROM realtime_events"
        args: List[Any] = []
        if ticker:
            sql += " WHERE ticker = ?"
            args.append(ticker.upper())
        sql += " ORDER BY source_time DESC, received_at DESC LIMIT ?"
        args.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            payload = json.loads(item.pop("payload_json") or "{}")
            if public and item.get("external_payload"):
                payload = {"redacted": True, "note": "Operator-supplied external payload is not exposed by the public API."}
            item["payload"] = payload
            item["context_only"] = bool(item["context_only"])
            item["external_payload"] = bool(item["external_payload"])
            out.append(item)
        return out

    def latest_event(self, source: str, scope_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM realtime_events WHERE source=? AND scope_key=? ORDER BY source_time DESC, received_at DESC LIMIT 1",
                (source, scope_key),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item

    def record_provider_check(self, source: str, scope_key: str, success: bool, message: str = "", checked_at: Optional[str] = None):
        checked_at = checked_at or _utcnow()
        with self._connect() as conn:
            old = conn.execute("SELECT last_success_at FROM provider_checks WHERE source=? AND scope_key=?", (source, scope_key)).fetchone()
            last_success = checked_at if success else (old[0] if old else None)
            conn.execute(
                """INSERT INTO provider_checks(source,scope_key,last_checked_at,last_success_at,status,message)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(source,scope_key) DO UPDATE SET
                last_checked_at=excluded.last_checked_at,last_success_at=excluded.last_success_at,status=excluded.status,message=excluded.message""",
                (source, scope_key, checked_at, last_success, "ok" if success else "degraded", message[:500]),
            )

    def provider_check(self, source: str, scope_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM provider_checks WHERE source=? AND scope_key=?", (source, scope_key)).fetchone()
        return dict(row) if row else None

    def provider_health_aggregate(self) -> Dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT source, COUNT(*) scopes,
                SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) ok_scopes,
                MAX(last_checked_at) last_checked_at,
                MAX(last_success_at) last_success_at
                FROM provider_checks GROUP BY source"""
            ).fetchall()
        return {r["source"]: {"scopes": r["scopes"], "ok_scopes": r["ok_scopes"], "last_checked_at": r["last_checked_at"], "last_success_at": r["last_success_at"]} for r in rows}

    def upsert_pending_label(self, row: Dict[str, Any]) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO pending_labels
                (label_id,ticker,benchmark,base_model_id,settings_fingerprint,settings_json,observation_ts,observation_date,earliest_maturity,
                 anchor_probability,candidate_probability,features_json,stock_entry_price,benchmark_entry_price,horizon_trading_days,excess_return_threshold,status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["label_id"], row["ticker"], row["benchmark"], row["base_model_id"], row["settings_fingerprint"],
                    json.dumps(row["settings"], sort_keys=True), row["observation_ts"], row["observation_date"], row["earliest_maturity"],
                    row["anchor_probability"], row["candidate_probability"], json.dumps(row["features"], sort_keys=True),
                    row["stock_entry_price"], row["benchmark_entry_price"], row["horizon_trading_days"], row["excess_return_threshold"], row.get("status", "pending"),
                ),
            )
            return cur.rowcount > 0

    def matured_pending(self, as_of_date: str, limit: int = 500) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_labels WHERE status='pending' AND earliest_maturity<=? ORDER BY earliest_maturity, observation_ts LIMIT ?",
                (as_of_date, max(1, min(limit, 5000))),
            ).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d["settings"]=json.loads(d.pop("settings_json")); d["features"]=json.loads(d.pop("features_json")); out.append(d)
        return out

    def resolve_pending(self, label_id: str, label: int, resolved_at: Optional[str] = None):
        with self._connect() as conn:
            conn.execute("UPDATE pending_labels SET status='resolved', realized_label=?, resolved_at=? WHERE label_id=?", (int(label), resolved_at or _utcnow(), label_id))

    def get_state(self, state_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM adaptive_states WHERE state_key=?", (state_key,)).fetchone()
        if not row: return None
        d=dict(row); d["settings"]=json.loads(d.pop("settings_json")); d["state"]=json.loads(d.pop("state_json")); return d

    def save_state(self, state_key: str, base_model_id: str, settings_fingerprint: str, settings: Dict[str, Any], state: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO adaptive_states(state_key,base_model_id,settings_fingerprint,settings_json,state_json,updated_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(state_key) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at""",
                (state_key, base_model_id, settings_fingerprint, json.dumps(settings, sort_keys=True), json.dumps(state, sort_keys=True), _utcnow()),
            )

    def add_performance(self, state_key: str, observation_date: str, anchor_probability: float, adaptive_probability: float, label: int):
        import math
        y=float(label); pa=min(max(float(anchor_probability),1e-9),1-1e-9); pp=min(max(float(adaptive_probability),1e-9),1-1e-9)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO adaptive_performance(state_key,observation_date,anchor_probability,adaptive_probability,label,brier_anchor,brier_adaptive,log_anchor,log_adaptive,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (state_key, observation_date, pa, pp, int(label), (pa-y)**2, (pp-y)**2, -(y*math.log(pa)+(1-y)*math.log(1-pa)), -(y*math.log(pp)+(1-y)*math.log(1-pp)), _utcnow()),
            )

    def performance_recent_dates(self, state_key: str, n_dates: int) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            dates=[r[0] for r in conn.execute("SELECT DISTINCT observation_date FROM adaptive_performance WHERE state_key=? ORDER BY observation_date DESC LIMIT ?", (state_key,n_dates)).fetchall()]
            if not dates: return []
            placeholders=",".join("?" for _ in dates)
            rows=conn.execute(f"SELECT * FROM adaptive_performance WHERE state_key=? AND observation_date IN ({placeholders}) ORDER BY observation_date,id", [state_key,*dates]).fetchall()
        return [dict(r) for r in rows]

    def save_snapshot(self, snapshot_key: str, snapshot: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO live_snapshots(snapshot_key,ticker,benchmark,base_model_id,settings_fingerprint,snapshot_json,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(snapshot_key) DO UPDATE SET snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at""",
                (snapshot_key,snapshot["ticker"],snapshot["benchmark"],snapshot["base_model_id"],snapshot["settings_fingerprint"],json.dumps(snapshot,sort_keys=True),_utcnow()),
            )

    def latest_snapshot(self, snapshot_key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row=conn.execute("SELECT snapshot_json FROM live_snapshots WHERE snapshot_key=?",(snapshot_key,)).fetchone()
        return json.loads(row[0]) if row else None

    def counts(self) -> Dict[str,int]:
        names=["realtime_events","pending_labels","adaptive_states","adaptive_performance","live_snapshots"]
        with self._connect() as conn:
            return {n:int(conn.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0]) for n in names}


store = RealtimeStore()
