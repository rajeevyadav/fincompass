"""FinCompass adaptive/live orchestration."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from typing import Any, Dict, Optional

import pandas as pd

from realtime import REALTIME_ENGINE_VERSION
from realtime.adaptive import evaluate_gate, initial_state, predict, state_key, update_state
from realtime.config import RealtimeSettings, PROFILES
from realtime.features import age_seconds, build_adaptive_features, provider_verified_recently
from realtime.providers import fetch_macro_event, fetch_market_event, fetch_sec_event
from realtime.registry import load_adaptive_artifact, registry_status
from realtime.store import RealtimeStore, store
from services.forecast_service import forecast_ticker, get_forecast_status
from services.analyzer import get_price_history_cached


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _due(check: Optional[Dict[str,Any]], cadence: int, now: datetime) -> bool:
    if not check or not check.get("last_checked_at"): return True
    age=age_seconds(check.get("last_checked_at"),now)
    return age is None or age>=cadence


def _refresh_one(source: str, scope: str, cadence: int, fn, db: RealtimeStore, now: datetime, force: bool=False):
    check=db.provider_check(source,scope)
    if not force and not _due(check,cadence,now):
        return {"checked":False,"reason":"cadence","provider":check}
    try:
        event=fn(); inserted=db.add_event(event); db.record_provider_check(source,scope,True,"ok",checked_at=now.isoformat())
        return {"checked":True,"success":True,"inserted":inserted,"event_id":event["event_id"]}
    except Exception as exc:
        db.record_provider_check(source,scope,False,type(exc).__name__,checked_at=now.isoformat())
        return {"checked":True,"success":False,"error":type(exc).__name__}


def refresh_sources(ticker: str, benchmark: str, settings: RealtimeSettings, db: RealtimeStore=store, force: bool=False) -> Dict[str,Any]:
    ticker=ticker.upper(); benchmark=benchmark.upper(); now=_now(); market_scope=f"{ticker}|{benchmark}"
    result={
        "market":_refresh_one("market",market_scope,settings.market_refresh_seconds,lambda:fetch_market_event(ticker,benchmark),db,now,force),
        "sec":_refresh_one("sec",ticker,settings.sec_refresh_seconds,lambda:fetch_sec_event(ticker),db,now,force),
        "macro":_refresh_one("macro","global",settings.macro_refresh_seconds,fetch_macro_event,db,now,force),
    }
    return result


def _load_runtime_state(base_model_id: str, settings: RealtimeSettings, db: RealtimeStore):
    skey=state_key(base_model_id,settings); stored=db.get_state(skey)
    if stored:
        if stored.get("settings_fingerprint")==settings.fingerprint() and stored.get("settings")==settings.to_dict():
            return skey,stored["state"],"runtime"
    # Only a separately live-eligible artifact may warm-start a runtime state.
    warm,manifest=load_adaptive_artifact(base_model_id=base_model_id,minimum_tier="validated_research")
    if warm is not None and manifest and manifest.get("settings_fingerprint")==settings.fingerprint():
        state=warm; source=f"artifact:{manifest.get('adaptive_id')}"
    else:
        state=initial_state(settings); source="cold_start"
    db.save_state(skey,base_model_id,settings.fingerprint(),settings.to_dict(),state)
    return skey,state,source


def _event_status(event,check,max_stale,now):
    return {
        "event_source_time":event.get("source_time") if event else None,
        "event_age_seconds":age_seconds(event.get("source_time"),now) if event else None,
        "last_checked_at":check.get("last_checked_at") if check else None,
        "last_success_at":check.get("last_success_at") if check else None,
        "verified_recently":provider_verified_recently(check,max_stale,now),
        "status":check.get("status") if check else "not_checked",
    }


def _pending_id(ticker,model_id,settings_fp,observation_date):
    return sha256(f"{ticker}|{model_id}|{settings_fp}|{observation_date}".encode("utf-8")).hexdigest()[:32]


def live_snapshot(
    ticker: str,
    model_id: Optional[str]=None,
    profile_name: Optional[str]=None,
    realtime_settings: Optional[RealtimeSettings]=None,
    db: RealtimeStore=store,
    force_sources: bool=False,
    queue_observation: bool=True,
) -> Dict[str,Any]:
    ticker=ticker.upper(); settings=(realtime_settings or PROFILES["balanced"]).validate(); now=_now()
    anchor=forecast_ticker(ticker,model_id=model_id,profile_name=profile_name)
    if not anchor.get("available"):
        return {"available":False,"ticker":ticker,"realtime_engine_version":REALTIME_ENGINE_VERSION,"anchor":anchor,"message":"Live probability requires a live-eligible validated anchor model. Synthetic fixture anchors remain blocked.","adaptive_registry":registry_status()}
    model_id=str(anchor["model_id"]); target=anchor.get("target") or {}; benchmark=str(target.get("benchmark") or "SPY").upper()
    source_refresh=refresh_sources(ticker,benchmark,settings,db=db,force=force_sources)
    market_scope=f"{ticker}|{benchmark}"
    market=db.latest_event("market",market_scope); sec=db.latest_event("sec",ticker); macro=db.latest_event("macro","global")
    market_check=db.provider_check("market",market_scope); sec_check=db.provider_check("sec",ticker); macro_check=db.provider_check("macro","global")
    features=build_adaptive_features(market,sec,macro,market_check,sec_check,macro_check,settings,now)
    skey,state,state_source=_load_runtime_state(model_id,settings,db)
    recent=db.performance_recent_dates(skey,settings.online_eval_window)
    gate=evaluate_gate(recent,state.get("drift") or {},settings)
    state["gate"]=gate; state["status"]=gate["status"]
    db.save_state(skey,model_id,settings.fingerprint(),settings.to_dict(),state)
    anchor_prob=float((anchor.get("probability") or {}).get("probability_outperform"))
    pred=predict(anchor_prob,features,state,settings)
    market_fresh=provider_verified_recently(market_check,settings.max_market_staleness_seconds,now)
    applied=bool(gate["active"] and market_fresh and settings.enable_adaptive_application)
    applied_prob=pred["candidate_probability"] if applied else anchor_prob
    source_health={
        "market":_event_status(market,market_check,settings.max_market_staleness_seconds,now),
        "sec":_event_status(sec,sec_check,settings.max_sec_staleness_seconds,now),
        "macro":_event_status(macro,macro_check,settings.max_macro_staleness_seconds,now),
    }
    pending={"created":False,"reason":"market context unavailable" if queue_observation else "comparison-only view; no learning observation queued"}
    mp=(market or {}).get("payload") or {}
    stock_price=mp.get("latest_price"); bench_price=mp.get("benchmark_latest_price")
    if queue_observation and settings.enable_online_learning and market_fresh and stock_price and bench_price:
        obs_date=now.date().isoformat(); horizon=int(target.get("horizon_trading_days") or 252); cal_days=max(1,int(math.ceil(horizon*365.25/252.0)))
        earliest=(now.date()+timedelta(days=cal_days)).isoformat(); lid=_pending_id(ticker,model_id,settings.fingerprint(),obs_date)
        pending_row={"label_id":lid,"ticker":ticker,"benchmark":benchmark,"base_model_id":model_id,"settings_fingerprint":settings.fingerprint(),"settings":settings.to_dict(),"observation_ts":now.isoformat(),"observation_date":obs_date,"earliest_maturity":earliest,"anchor_probability":anchor_prob,"candidate_probability":pred["candidate_probability"],"features":features,"stock_entry_price":float(stock_price),"benchmark_entry_price":float(bench_price),"horizon_trading_days":horizon,"excess_return_threshold":float(target.get("excess_return_threshold") or 0.0)}
        created=db.upsert_pending_label(pending_row); pending={"created":created,"label_id":lid,"earliest_maturity":earliest,"reason":"queued" if created else "one observation already exists for this ticker/model/settings/date"}
    snapshot={
        "available":True,"ticker":ticker,"benchmark":benchmark,"as_of":now.isoformat(),"base_model_id":model_id,"anchor_validation_tier":anchor.get("validation_tier"),"settings_fingerprint":settings.fingerprint(),"realtime_engine_version":REALTIME_ENGINE_VERSION,"state_key":skey,"state_source":state_source,
        "anchor_probability":anchor_prob,"adaptive_candidate_probability":pred["candidate_probability"],"adaptive_applied_probability":applied_prob,"adaptive_shift_applied":applied,"candidate_logit_shift":pred["bounded_logit_shift"],"posterior_shift_sd":pred["posterior_shift_sd"],"top_contributions":pred["top_contributions"],"features":features,"gate":gate,"drift":state.get("drift"),"source_health":source_health,"source_refresh":source_refresh,"pending_label":pending,"target":target,
        "disclaimer":"Near-real-time evidence can update the candidate immediately; adaptive parameters update only after labels mature. This is research support, not a trading signal or guarantee."
    }
    snap_key=sha256(f"{ticker}|{benchmark}|{model_id}|{settings.fingerprint()}".encode()).hexdigest()[:24]
    db.save_snapshot(snap_key,snapshot)
    return snapshot


def compare_live_profiles(
    ticker: str,
    model_id: Optional[str]=None,
    profile_name: Optional[str]=None,
    db: RealtimeStore=store,
    force_sources: bool=False,
) -> Dict[str,Any]:
    """Compare governed realtime profiles against the same observed information state.

    This is a sensitivity comparison of FinCompass adaptive settings, not a
    simulation of alternative future market scenarios. It never queues online
    learning observations, so comparing profiles cannot manufacture training
    evidence or alter pending-label counts.
    """
    ticker=str(ticker or "").strip().upper()
    rows=[]
    for index, name in enumerate(("conservative", "balanced", "responsive")):
        snapshot=live_snapshot(
            ticker,
            model_id=model_id,
            profile_name=profile_name,
            realtime_settings=PROFILES[name],
            db=db,
            force_sources=bool(force_sources and index == 0),
            queue_observation=False,
        )
        if not snapshot.get("available"):
            return {
                "available": False,
                "ticker": ticker,
                "anchor": snapshot.get("anchor"),
                "message": snapshot.get("message") or "No live-eligible anchor is available.",
                "conditions": [],
            }
        gate=snapshot.get("gate") or {}
        rows.append({
            "profile": name,
            "base_model_id": snapshot.get("base_model_id"),
            "settings_fingerprint": snapshot.get("settings_fingerprint"),
            "anchor_probability": snapshot.get("anchor_probability"),
            "adaptive_candidate_probability": snapshot.get("adaptive_candidate_probability"),
            "adaptive_applied_probability": snapshot.get("adaptive_applied_probability"),
            "adaptive_shift_applied": snapshot.get("adaptive_shift_applied"),
            "candidate_logit_shift": snapshot.get("candidate_logit_shift"),
            "posterior_shift_sd": snapshot.get("posterior_shift_sd"),
            "gate_status": gate.get("status") or "warming",
            "gate_active": bool(gate.get("active")),
            "gate_metrics": gate.get("metrics") or {},
            "source_health": snapshot.get("source_health") or {},
        })
    first=rows[0] if rows else {}
    return {
        "available": True,
        "ticker": ticker,
        "base_model_id": first.get("base_model_id"),
        "anchor_probability": first.get("anchor_probability"),
        "conditions": rows,
        "comparison_contract": "Same observed live information; only the governed adaptive profile changes.",
        "learning_side_effects": False,
        "disclaimer": "Condition comparison is sensitivity analysis, not a simulated future scenario or trading recommendation.",
    }


def _aligned_horizon_closes(
    ticker: str,
    benchmark: str,
    observation_date: str,
    horizon_trading_days: int,
    as_of_date: str,
) -> Optional[Dict[str,Any]]:
    """Resolve the exact H-th common trading-session close after observation.

    A delayed maturity job must not silently extend the forecast horizon by
    using whatever close happens to be latest when the job finally runs. The
    endpoint is therefore fixed to the H-th common stock/benchmark session
    after the observation date, and is returned only after that session is
    available as of the processing date.
    """
    horizon=max(1,int(horizon_trading_days))
    stock=get_price_history_cached(ticker,"max")
    bench=get_price_history_cached(benchmark,"max")
    if stock is None or bench is None or getattr(stock,"empty",True) or getattr(bench,"empty",True):
        return None
    try:
        def close_series(frame):
            values=pd.to_numeric(frame["Close"],errors="coerce")
            idx=pd.to_datetime(frame.index,utc=True).tz_convert(None).normalize()
            ser=pd.Series(values.to_numpy(),index=idx).dropna()
            return ser.groupby(level=0).last().sort_index()
        s=close_series(stock); b=close_series(bench)
        common=s.index.intersection(b.index).sort_values()
        obs=pd.Timestamp(observation_date).normalize(); cutoff=pd.Timestamp(as_of_date).normalize()
        future=common[(common>obs)&(common<=cutoff)]
        if len(future)<horizon:
            return None
        target_date=future[horizon-1]
        return {
            "target_date":target_date.date().isoformat(),
            "stock_close":float(s.loc[target_date]),
            "benchmark_close":float(b.loc[target_date]),
        }
    except Exception:
        return None


def process_matured_labels(as_of_date: Optional[str]=None, db: RealtimeStore=store, limit:int=500) -> Dict[str,Any]:
    as_of_date=as_of_date or date.today().isoformat(); rows=db.matured_pending(as_of_date,limit=limit); processed=0; skipped=0; state_updates={}
    for row in rows:
        try:
            settings=RealtimeSettings(**row["settings"]).validate()
            if settings.fingerprint()!=row["settings_fingerprint"]:
                db.resolve_pending(row["label_id"],0); skipped+=1; continue
            endpoint=_aligned_horizon_closes(row["ticker"],row["benchmark"],row["observation_date"],int(row["horizon_trading_days"]),as_of_date)
            if endpoint is None or row["stock_entry_price"]<=0 or row["benchmark_entry_price"]<=0:
                skipped+=1; continue
            stock_ret=float(endpoint["stock_close"])/float(row["stock_entry_price"])-1.0
            bench_ret=float(endpoint["benchmark_close"])/float(row["benchmark_entry_price"])-1.0
            label=int((stock_ret-bench_ret)>float(row["excess_return_threshold"]))
            skey=state_key(row["base_model_id"],settings); stored=db.get_state(skey); state=stored["state"] if stored else initial_state(settings)
            new_state,pred=update_state(float(row["anchor_probability"]),row["features"],label,state,settings)
            db.add_performance(skey,row["observation_date"],float(row["anchor_probability"]),float(pred["candidate_probability"]),label)
            recent=db.performance_recent_dates(skey,settings.online_eval_window); gate=evaluate_gate(recent,new_state.get("drift") or {},settings); new_state["gate"]=gate; new_state["status"]=gate["status"]
            db.save_state(skey,row["base_model_id"],settings.fingerprint(),settings.to_dict(),new_state); db.resolve_pending(row["label_id"],label); processed+=1; state_updates[skey]=gate
        except Exception:
            skipped+=1
    return {"as_of_date":as_of_date,"eligible":len(rows),"processed":processed,"skipped":skipped,"state_updates":state_updates}


def realtime_status(db:RealtimeStore=store)->Dict[str,Any]:
    return {"realtime_engine_version":REALTIME_ENGINE_VERSION,"adaptive_registry":registry_status(),"anchor_registry":get_forecast_status(),"provider_health":db.provider_health_aggregate(),"store_counts":db.counts(),"privacy_note":"Provider health is aggregate; ticker/benchmark-scoped research keys are not exposed."}
