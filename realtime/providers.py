from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import requests
try:
    import yfinance as yf
except ImportError:
    yf = None

from forecasting.sec_fundamentals import SecClient
from services.macro_fetcher import FRED_BASE
from config import FRED_API_KEY, FRED_SERIES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_id(source: str, scope_key: str, source_time: str, payload: Dict[str,Any]) -> str:
    raw=json.dumps([source,scope_key,source_time,payload],sort_keys=True,separators=(",",":"),default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty: return pd.DataFrame()
    out=df.copy()
    if isinstance(out.columns,pd.MultiIndex):
        out.columns=[c[0] if isinstance(c,tuple) else c for c in out.columns]
    return out


def _zscore_last(values: pd.Series, window: int=20) -> float:
    x=pd.to_numeric(values,errors="coerce").dropna().tail(window)
    if len(x)<5: return 0.0
    sd=float(x.std(ddof=0))
    return float((x.iloc[-1]-x.mean())/sd) if sd>1e-12 else 0.0


def fetch_market_event(ticker: str, benchmark: str="SPY") -> Dict[str,Any]:
    if yf is None:
        raise RuntimeError("yfinance is not installed")
    ticker=ticker.upper(); benchmark=benchmark.upper(); scope=f"{ticker}|{benchmark}"
    stock=_normalize_history(yf.Ticker(ticker).history(period="1mo",interval="1h",auto_adjust=True))
    bench=_normalize_history(yf.Ticker(benchmark).history(period="1mo",interval="1h",auto_adjust=True))
    if stock.empty or bench.empty: raise RuntimeError("market intraday history unavailable")
    latest=float(stock["Close"].dropna().iloc[-1]); b_latest=float(bench["Close"].dropna().iloc[-1])
    # Previous session close -> latest, preserving overnight gaps.
    s_daily=_normalize_history(yf.Ticker(ticker).history(period="10d",interval="1d",auto_adjust=True))
    b_daily=_normalize_history(yf.Ticker(benchmark).history(period="10d",interval="1d",auto_adjust=True))
    if len(s_daily)>=2: prev=float(s_daily["Close"].dropna().iloc[-2])
    else: prev=float(stock["Close"].dropna().iloc[0])
    if len(b_daily)>=2: b_prev=float(b_daily["Close"].dropna().iloc[-2])
    else: b_prev=float(bench["Close"].dropna().iloc[0])
    ret=latest/prev-1.0 if prev else 0.0; bret=b_latest/b_prev-1.0 if b_prev else 0.0
    s_returns=pd.to_numeric(stock["Close"],errors="coerce").pct_change()
    b_returns=pd.to_numeric(bench["Close"],errors="coerce").pct_change()
    aligned=pd.concat([s_returns.rename("s"),b_returns.rename("b")],axis=1).dropna()
    relative=aligned["s"]-aligned["b"] if not aligned.empty else pd.Series(dtype=float)
    vol=stock.get("Volume",pd.Series(dtype=float))
    day=stock.tail(min(8,len(stock)))
    range_pct=(float(day["High"].max())-float(day["Low"].min()))/latest if latest else 0.0
    ts=stock.index[-1]
    source_time=(ts.to_pydatetime().astimezone(timezone.utc).isoformat() if getattr(ts,"tzinfo",None) else pd.Timestamp(ts,tz="UTC").isoformat())
    payload={"ticker":ticker,"benchmark":benchmark,"latest_price":latest,"benchmark_latest_price":b_latest,"previous_session_close":prev,"benchmark_previous_session_close":b_prev,
             "market_return_1d":ret,"benchmark_return_1d":bret,"benchmark_relative_return_1d":ret-bret,"return_z_20":_zscore_last(aligned["s"] if not aligned.empty else s_returns),
             "relative_return_z_20":_zscore_last(relative),"volume_z_20":_zscore_last(vol),"intraday_range_pct":range_pct}
    return {"event_id":_event_id("market",scope,source_time,payload),"source":"market","scope_key":scope,"event_type":"market_snapshot","ticker":ticker,"benchmark":benchmark,"source_time":source_time,"received_at":_now(),"payload":payload}


def fetch_sec_event(ticker: str) -> Dict[str,Any]:
    ua=(os.getenv("SEC_USER_AGENT") or "").strip()
    if not ua: raise RuntimeError("SEC_USER_AGENT not configured")
    client=SecClient(user_agent=ua,cache_max_age_hours=0.25)
    mapping=client.ticker_to_cik(); cik=mapping.get(ticker.upper().replace(".","-"))
    if not cik: raise RuntimeError("SEC CIK mapping unavailable")
    url=f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    data=client._json(url,f"submissions-CIK{int(cik):010d}.json")
    recent=(data.get("filings") or {}).get("recent") or {}
    forms=recent.get("form") or []; filed=recent.get("filingDate") or []; accepted=recent.get("acceptanceDateTime") or []; acc=recent.get("accessionNumber") or []; docs=recent.get("primaryDocument") or []
    if not forms: raise RuntimeError("SEC filing metadata unavailable")
    payload={"form":forms[0],"filing_date":filed[0] if filed else None,"acceptance_datetime":accepted[0] if accepted else None,"accession":acc[0] if acc else None,"primary_document":docs[0] if docs else None,"cik":int(cik)}
    source_time=None
    if payload.get("acceptance_datetime"):
        try:
            source_time=pd.to_datetime(payload["acceptance_datetime"],utc=True).isoformat()
        except Exception:
            source_time=None
    if source_time is None:
        source_time=f"{payload['filing_date']}T23:59:59+00:00" if payload.get("filing_date") else _now()
    scope=ticker.upper()
    return {"event_id":_event_id("sec",scope,source_time,payload),"source":"sec","scope_key":scope,"event_type":"filing","ticker":scope,"source_time":source_time,"received_at":_now(),"payload":payload}


def _fred_series(series_id: str, limit: int=3):
    if not FRED_API_KEY: raise RuntimeError("FRED_API_KEY not configured")
    r=requests.get(FRED_BASE,params={"series_id":series_id,"api_key":FRED_API_KEY,"file_type":"json","sort_order":"desc","limit":limit},timeout=12)
    r.raise_for_status(); obs=[o for o in r.json().get("observations",[]) if o.get("value") not in (None,".","")]
    if not obs: raise RuntimeError(f"FRED {series_id} unavailable")
    return obs


def fetch_macro_event() -> Dict[str,Any]:
    yc=_fred_series(FRED_SERIES["yield_curve"]); hy=_fred_series(FRED_SERIES["credit_spread"])
    y0=float(yc[0]["value"]); y1=float(yc[1]["value"]) if len(yc)>1 else y0
    h0=float(hy[0]["value"]); h1=float(hy[1]["value"]) if len(hy)>1 else h0
    source_date=max(yc[0]["date"],hy[0]["date"]); source_time=f"{source_date}T23:59:59+00:00"
    payload={"yield_curve_10y2y":y0,"yield_curve_change":y0-y1,"credit_spread_hy_oas":h0,"hy_spread_change":h0-h1}
    return {"event_id":_event_id("macro","global",source_time,payload),"source":"macro","scope_key":"global","event_type":"macro_snapshot","source_time":source_time,"received_at":_now(),"payload":payload}
