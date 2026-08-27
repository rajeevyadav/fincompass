from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, Optional

from realtime.config import RealtimeSettings


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def age_seconds(source_time: Optional[str], now: Optional[datetime]=None) -> Optional[float]:
    dt=_parse_ts(source_time)
    if not dt: return None
    now=now or datetime.now(timezone.utc)
    return max(0.0,(now-dt).total_seconds())


def exp_decay(age_sec: Optional[float], half_life_hours: float) -> float:
    if age_sec is None: return 0.0
    half=max(half_life_hours*3600.0,1.0)
    return float(math.exp(-math.log(2.0)*age_sec/half))


def provider_verified_recently(check: Optional[Dict[str,Any]], max_staleness_seconds: int, now: Optional[datetime]=None) -> bool:
    if not check or not check.get("last_success_at"): return False
    a=age_seconds(check.get("last_success_at"),now)
    return a is not None and a<=max_staleness_seconds


def build_adaptive_features(
    market: Optional[Dict[str,Any]],
    sec: Optional[Dict[str,Any]],
    macro: Optional[Dict[str,Any]],
    market_check: Optional[Dict[str,Any]],
    sec_check: Optional[Dict[str,Any]],
    macro_check: Optional[Dict[str,Any]],
    settings: RealtimeSettings,
    now: Optional[datetime]=None,
) -> Dict[str,float]:
    now=now or datetime.now(timezone.utc)
    m=(market or {}).get("payload",market or {})
    s=(sec or {}).get("payload",sec or {})
    c=(macro or {}).get("payload",macro or {})
    market_ok=provider_verified_recently(market_check,settings.max_market_staleness_seconds,now)
    sec_ok=provider_verified_recently(sec_check,settings.max_sec_staleness_seconds,now)
    macro_ok=provider_verified_recently(macro_check,settings.max_macro_staleness_seconds,now)
    sec_decay=exp_decay(age_seconds((sec or {}).get("source_time") or s.get("source_time"),now),settings.event_half_life_hours) if sec_ok else 0.0
    macro_decay=exp_decay(age_seconds((macro or {}).get("source_time") or c.get("source_time"),now),settings.event_half_life_hours*4.0) if macro_ok else 0.0
    form=str(s.get("form") or "").upper()
    def f(obj,key):
        try:
            v=float(obj.get(key,0.0) or 0.0)
            return v if math.isfinite(v) else 0.0
        except Exception: return 0.0
    return {
        "market_return_1d":f(m,"market_return_1d") if market_ok else 0.0,
        "benchmark_relative_return_1d":f(m,"benchmark_relative_return_1d") if market_ok else 0.0,
        "return_z_20":f(m,"return_z_20") if market_ok else 0.0,
        "relative_return_z_20":f(m,"relative_return_z_20") if market_ok else 0.0,
        "volume_z_20":f(m,"volume_z_20") if market_ok else 0.0,
        "intraday_range_pct":f(m,"intraday_range_pct") if market_ok else 0.0,
        "sec_filing_freshness":sec_decay,
        "sec_is_8k_6k":sec_decay if form in {"8-K","8-K/A","6-K","6-K/A"} else 0.0,
        "sec_is_10q":sec_decay if form in {"10-Q","10-Q/A"} else 0.0,
        "sec_is_10k_family":sec_decay if form in {"10-K","10-K/A","20-F","20-F/A","40-F","40-F/A"} else 0.0,
        "yield_curve_change":f(c,"yield_curve_change")*macro_decay,
        "hy_spread_change":f(c,"hy_spread_change")*macro_decay,
        "macro_freshness":macro_decay,
    }
