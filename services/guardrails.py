"""FinCompass production guardrails v3.

Read-only research API controls:
- request correlation IDs,
- shared rate limiting (SQLite by default; optional Redis for multi-host),
- minimal audit log,
- strict ticker validation,
- security headers + Content Security Policy.
"""
from __future__ import annotations

import json
import logging
import re
from hashlib import sha256
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Callable, Deque, Dict, Optional, Tuple

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from config import AUDIT_IP_MODE, AUDIT_LOG_MAX_BYTES, DATA_DIR, DB_PATH, RATE_LIMIT_BACKEND, REDIS_URL

logger = logging.getLogger("FinCompass.Guardrails")

RATE_LIMITS = {
    "analyze": (30, 60),
    "screener": (10, 60),
    "status": (60, 60),
    "refresh": (2, 60),
    "compare": (20, 60),
    "history": (40, 60),
    "forecast": (15, 60),
    "realtime": (30, 60),
    "adaptive": (4, 60),
    "ingest": (20, 60),
    "export": (10, 60),
    "default": (60, 60),
}

AUDIT_LOG_PATH = DATA_DIR / "audit.jsonl"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")


def validate_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if not t or not TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail="Invalid ticker format")
    return t


def _endpoint_group(path: str) -> str:
    if "/screener/refresh" in path:
        return "refresh"
    if "/screener/status" in path:
        return "status"
    if "/export" in path:
        return "export"
    if "/analyze" in path:
        return "analyze"
    if "/screener" in path:
        return "screener"
    if "/compare" in path:
        return "compare"
    if "/history" in path:
        return "history"
    if "/events/ingest" in path:
        return "ingest"
    if "/adaptive/" in path:
        return "adaptive"
    if "/realtime/" in path:
        return "realtime"
    # Status/progress endpoints are cheap and are polled (e.g. the in-app model
    # build polls its status every few seconds); keep them in the generous
    # "status" bucket rather than the tighter per-feature limits.
    if path.endswith("/status"):
        return "status"
    if "/forecast" in path:
        return "forecast"
    return "default"


class MemoryRateLimiter:
    """Process-local fallback used only when explicitly configured."""
    def __init__(self, sweep_every: int = 500):
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._sweep_every = sweep_every
        self._calls_since_sweep = 0

    def check(self, key: str, limit: int, window_sec: int) -> Tuple[bool, int]:
        now = time.time()
        q = self._hits[key]
        while q and q[0] <= now - window_sec:
            q.popleft()
        if len(q) >= limit:
            retry = int(window_sec - (now - q[0])) + 1
            return False, max(retry, 1)
        q.append(now)
        self._calls_since_sweep += 1
        if self._calls_since_sweep >= self._sweep_every:
            self._calls_since_sweep = 0
            cutoff = now - max(w for _, w in RATE_LIMITS.values())
            for dead in [k for k, values in self._hits.items() if not values or values[-1] <= cutoff]:
                self._hits.pop(dead, None)
        return True, 0


class SQLiteRateLimiter:
    """Atomic sliding-window limiter shared by all workers using one SQLite DB."""
    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)
        with sqlite3.connect(self.db_path, timeout=15) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS rate_limit_hits (key TEXT NOT NULL, ts REAL NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rate_limit_hits_key_ts ON rate_limit_hits(key, ts)"
            )

    def check(self, key: str, limit: int, window_sec: int) -> Tuple[bool, int]:
        now = time.time()
        cutoff = now - window_sec
        try:
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                conn.execute("PRAGMA busy_timeout=5000")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM rate_limit_hits WHERE key = ? AND ts <= ?", (key, cutoff))
                count = conn.execute("SELECT COUNT(*) FROM rate_limit_hits WHERE key = ?", (key,)).fetchone()[0]
                if count >= limit:
                    oldest = conn.execute("SELECT MIN(ts) FROM rate_limit_hits WHERE key = ?", (key,)).fetchone()[0]
                    conn.commit()
                    retry = int(window_sec - (now - float(oldest))) + 1 if oldest is not None else 1
                    return False, max(retry, 1)
                conn.execute("INSERT INTO rate_limit_hits(key, ts) VALUES (?, ?)", (key, now))
                # Opportunistic global cleanup keeps the table bounded without a scheduler.
                conn.execute("DELETE FROM rate_limit_hits WHERE ts <= ?", (now - 3600,))
                conn.commit()
            return True, 0
        except Exception as exc:
            # Availability wins over an internal limiter failure; log loudly.
            logger.warning("SQLite rate limiter unavailable; allowing request: %s", exc)
            return True, 0


class RedisRateLimiter:
    """Atomic Redis sorted-set sliding window for multi-host deployments."""
    _SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local cutoff = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local member = ARGV[5]
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  if oldest[2] then return {0, oldest[2]} else return {0, now} end
end
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, ttl)
return {1, 0}
"""

    def __init__(self, url: str):
        import redis  # optional dependency; see requirements-scale.txt
        self.client = redis.Redis.from_url(url, decode_responses=True)
        self.script = self.client.register_script(self._SCRIPT)

    def check(self, key: str, limit: int, window_sec: int) -> Tuple[bool, int]:
        now = time.time()
        try:
            allowed, oldest = self.script(
                keys=[f"fincompass:ratelimit:{key}"],
                args=[now, now - window_sec, limit, window_sec + 5, f"{now}:{uuid.uuid4()}"],
            )
            if int(allowed) == 1:
                return True, 0
            retry = int(window_sec - (now - float(oldest))) + 1
            return False, max(retry, 1)
        except Exception as exc:
            logger.warning("Redis rate limiter unavailable; allowing request: %s", exc)
            return True, 0


def _build_rate_limiter():
    backend = RATE_LIMIT_BACKEND
    if backend == "redis":
        if not REDIS_URL:
            logger.warning("RATE_LIMIT_BACKEND=redis but REDIS_URL is empty; falling back to SQLite")
            return SQLiteRateLimiter()
        try:
            return RedisRateLimiter(REDIS_URL)
        except Exception as exc:
            logger.warning("Redis limiter initialization failed (%s); falling back to SQLite", exc)
            return SQLiteRateLimiter()
    if backend == "memory":
        return MemoryRateLimiter()
    if backend != "sqlite":
        logger.warning("Unknown RATE_LIMIT_BACKEND=%s; using SQLite", backend)
    return SQLiteRateLimiter()


_rate_limiter = _build_rate_limiter()


def effective_rate_limit_backend() -> str:
    if isinstance(_rate_limiter, RedisRateLimiter):
        return "redis"
    if isinstance(_rate_limiter, SQLiteRateLimiter):
        return "sqlite"
    return "memory"


def _audit_client_id(client_ip: str) -> Optional[str]:
    mode = AUDIT_IP_MODE
    if mode == "none":
        return None
    if mode == "raw":
        return client_ip
    # Daily rotation limits long-term linkage while preserving enough signal
    # to identify same-day rate-limit/abuse patterns.
    day = datetime.now(timezone.utc).date().isoformat()
    return sha256(f"{day}:{client_ip}".encode("utf-8")).hexdigest()[:16]


def _rotate_audit_if_needed() -> None:
    try:
        if AUDIT_LOG_PATH.exists() and AUDIT_LOG_PATH.stat().st_size >= AUDIT_LOG_MAX_BYTES:
            rotated = AUDIT_LOG_PATH.with_suffix(".jsonl.1")
            if rotated.exists():
                rotated.unlink()
            AUDIT_LOG_PATH.replace(rotated)
    except OSError as exc:
        logger.warning("audit rotation failed: %s", exc)


def audit_log(
    request_id: str,
    method: str,
    path: str,
    status: int,
    client_ip: str,
    extra: Optional[dict] = None,
) -> None:
    try:
        DATA_DIR.mkdir(exist_ok=True)
        client_id = _audit_client_id(client_ip)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "method": method,
            "path": path,
            "status": status,
        }
        if client_id is not None:
            record["client_id"] = client_id
            record["client_id_mode"] = AUDIT_IP_MODE
        if extra:
            record.update(extra)
        _rotate_audit_if_needed()
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("audit_log failed: %s", exc)


def _csp_for(path: str) -> str:
    # FastAPI's generated docs currently use jsDelivr assets. The application
    # itself is fully local and gets the stricter self-only policy.
    if path in {"/docs", "/redoc"}:
        return (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
    return (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )




def _apply_security_headers(response: Response, request: Request, path: str) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = _csp_for(path)
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

class GuardrailMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Modern browsers identify cross-site navigations/fetches. FinCompass
        # has no reason to accept drive-by browser calls from unrelated sites;
        # server-to-server API clients normally omit this browser header. This
        # also protects expensive force/refresh paths on localhost deployments.
        if path.startswith("/api/") and request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            response = Response(
                content='{"detail":"Cross-site browser API requests are not allowed."}',
                status_code=403,
                media_type="application/json",
                headers={"X-Request-ID": request_id},
            )
            _apply_security_headers(response, request, path)
            audit_log(request_id, request.method, path, 403, client_ip, {"reason": "cross_site"})
            return response

        if path.startswith("/api/"):
            group = _endpoint_group(path)
            limit, window = RATE_LIMITS.get(group, RATE_LIMITS["default"])
            allowed, retry_after = _rate_limiter.check(f"{client_ip}:{group}", limit, window)
            if not allowed:
                audit_log(request_id, request.method, path, 429, client_ip, {"reason": "rate_limit"})
                response = Response(
                    content='{"detail":"Rate limit exceeded. Try again shortly."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"X-Request-ID": request_id, "Retry-After": str(retry_after)},
                )
                _apply_security_headers(response, request, path)
                return response

        try:
            response = await call_next(request)
        except Exception:
            audit_log(request_id, request.method, path, 500, client_ip)
            raise

        response.headers["X-Request-ID"] = request_id
        _apply_security_headers(response, request, path)

        audit_log(request_id, request.method, path, response.status_code, client_ip)
        return response
