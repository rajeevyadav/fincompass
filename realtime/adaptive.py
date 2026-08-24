from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np

from realtime import REALTIME_ENGINE_VERSION
from realtime.config import RealtimeSettings

FEATURE_NAMES = [
    "market_return_1d",
    "benchmark_relative_return_1d",
    "return_z_20",
    "relative_return_z_20",
    "volume_z_20",
    "intraday_range_pct",
    "sec_filing_freshness",
    "sec_is_8k_6k",
    "sec_is_10q",
    "sec_is_10k_family",
    "yield_curve_change",
    "hy_spread_change",
    "macro_freshness",
]


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-min(x, 50.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(x, -50.0))
    return z / (1.0 + z)


def logit(p: float) -> float:
    p=min(max(float(p),1e-9),1-1e-9)
    return math.log(p/(1-p))


def clip_probability(p: float, clip: float) -> float:
    return min(max(float(p), clip), 1.0-clip)


def state_key(base_model_id: str, settings: RealtimeSettings) -> str:
    raw=f"{base_model_id}|{REALTIME_ENGINE_VERSION}|{settings.fingerprint()}"
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def initial_state(settings: RealtimeSettings) -> Dict[str, Any]:
    n=len(FEATURE_NAMES)
    var=float(settings.adaptive_prior_sigma)**2
    return {
        "engine_version": REALTIME_ENGINE_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "mean": [0.0]*n,
        "covariance": (np.eye(n)*var).tolist(),
        "updates": 0,
        "status": "warming",
        "drift": {"alert": False, "ewma": 0.0, "variance": 0.0, "samples": 0},
        "gate": {"active": False, "checks": {}},
    }


def vectorize(features: Dict[str, Any]) -> np.ndarray:
    vals=[]
    for name in FEATURE_NAMES:
        try:
            v=float(features.get(name,0.0) or 0.0)
        except Exception:
            v=0.0
        vals.append(v if math.isfinite(v) else 0.0)
    return np.asarray(vals,dtype=float)


def predict(anchor_probability: float, features: Dict[str, Any], state: Dict[str, Any], settings: RealtimeSettings) -> Dict[str, Any]:
    x=vectorize(features)
    mean=np.asarray(state.get("mean") or [0.0]*len(FEATURE_NAMES),dtype=float)
    cov=np.asarray(state.get("covariance") or np.eye(len(FEATURE_NAMES)),dtype=float)
    raw_delta=float(x@mean)
    delta=max(-settings.adaptive_max_logit_shift,min(settings.adaptive_max_logit_shift,raw_delta))
    candidate=clip_probability(sigmoid(logit(anchor_probability)+delta),settings.probability_clip)
    variance=max(0.0,float(x@cov@x))
    contributions=[{"feature":name,"value":float(x[i]),"coefficient":float(mean[i]),"log_odds_contribution":float(x[i]*mean[i])} for i,name in enumerate(FEATURE_NAMES)]
    contributions.sort(key=lambda r:abs(r["log_odds_contribution"]),reverse=True)
    return {
        "anchor_probability":float(anchor_probability),
        "candidate_probability":candidate,
        "raw_logit_shift":raw_delta,
        "bounded_logit_shift":delta,
        "posterior_shift_sd":math.sqrt(variance),
        "top_contributions":contributions[:6],
    }


def _date_balanced_metric(rows: Sequence[Dict[str,Any]], field: str) -> float:
    buckets: Dict[str,List[float]]={}
    for r in rows:
        buckets.setdefault(str(r["observation_date"]),[]).append(float(r[field]))
    if not buckets: return float("nan")
    return float(np.mean([np.mean(v) for v in buckets.values()]))


def expected_calibration_error(rows: Sequence[Dict[str,Any]], prob_field: str="adaptive_probability", bins: int=10) -> float:
    """Date-balanced expected calibration error.

    Each observation date receives equal total mass and observations within a
    date split that mass equally. This prevents a large same-day cross section
    from dominating the online calibration gate.
    """
    if not rows:
        return float("nan")
    p=np.asarray([float(r[prob_field]) for r in rows],dtype=float)
    y=np.asarray([int(r["label"]) for r in rows],dtype=float)
    dates=[str(r["observation_date"]) for r in rows]
    counts: Dict[str,int]={}
    for d in dates:
        counts[d]=counts.get(d,0)+1
    n_dates=max(len(counts),1)
    weights=np.asarray([1.0/(n_dates*counts[d]) for d in dates],dtype=float)
    edges=np.linspace(0,1,bins+1); ece=0.0
    for i in range(bins):
        mask=(p>=edges[i]) & ((p<edges[i+1]) if i<bins-1 else (p<=edges[i+1]))
        if not mask.any():
            continue
        w=weights[mask]; mass=float(w.sum())
        if mass<=0:
            continue
        p_bar=float(np.sum(w*p[mask])/mass)
        y_bar=float(np.sum(w*y[mask])/mass)
        ece += mass*abs(p_bar-y_bar)
    return float(ece)


def update_drift(drift: Dict[str,Any], loss_diff: float, settings: RealtimeSettings) -> Dict[str,Any]:
    a=float(settings.drift_alpha); n=int(drift.get("samples",0))+1
    old=float(drift.get("ewma",0.0)); ewma=(1-a)*old+a*float(loss_diff)
    old_var=float(drift.get("variance",0.0)); var=(1-a)*old_var+a*(float(loss_diff)-ewma)**2
    scale=math.sqrt(max(var,1e-12))
    alert = n>=settings.drift_min_samples and ewma > settings.drift_allowance + settings.drift_control_multiplier*scale/math.sqrt(max(n,1))
    return {"alert":bool(alert),"ewma":ewma,"variance":var,"samples":n,"control_limit":settings.drift_allowance+settings.drift_control_multiplier*scale/math.sqrt(max(n,1))}


def evaluate_gate(rows: Sequence[Dict[str,Any]], drift: Dict[str,Any], settings: RealtimeSettings) -> Dict[str,Any]:
    if not rows:
        return {"active":False,"status":"warming","checks":{},"metrics":{}}
    dates=sorted({str(r["observation_date"]) for r in rows})
    span=0
    if len(dates)>=2:
        span=(date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days
    ba=_date_balanced_metric(rows,"brier_anchor"); bp=_date_balanced_metric(rows,"brier_adaptive")
    la=_date_balanced_metric(rows,"log_anchor"); lp=_date_balanced_metric(rows,"log_adaptive")
    ece=expected_calibration_error(rows)
    checks={
        "min_matured_observations":len(rows)>=settings.min_matured_observations,
        "min_unique_observation_dates":len(dates)>=settings.min_unique_observation_dates,
        "min_observation_span_days":span>=settings.min_observation_span_days,
        "brier_noninferiority":bp-ba<=settings.max_brier_regret,
        "log_loss_noninferiority":lp-la<=settings.max_log_loss_regret,
        "max_ece":ece<=settings.max_ece,
        "no_drift":not bool(drift.get("alert")),
    }
    active=all(checks.values()) and settings.enable_adaptive_application
    if active: status="active"
    elif checks.get("min_matured_observations") and checks.get("min_unique_observation_dates") and checks.get("min_observation_span_days"): status="degraded"
    else: status="warming"
    return {"active":active,"status":status,"checks":checks,"metrics":{"observations":len(rows),"unique_dates":len(dates),"span_days":span,"anchor_brier":ba,"adaptive_brier":bp,"brier_improvement":ba-bp,"anchor_log_loss":la,"adaptive_log_loss":lp,"log_loss_improvement":la-lp,"ece":ece}}


def update_state(anchor_probability: float, features: Dict[str,Any], label: int, state: Dict[str,Any], settings: RealtimeSettings) -> Tuple[Dict[str,Any],Dict[str,Any]]:
    """Predict-before-update Bayesian residual step with rank-one covariance update."""
    prediction=predict(anchor_probability,features,state,settings)
    y=int(label); p=prediction["candidate_probability"]
    diff=(p-y)**2-(float(anchor_probability)-y)**2
    drift=update_drift(state.get("drift") or {},diff,settings)
    out=dict(state); out["drift"]=drift
    if settings.enable_online_learning:
        x=vectorize(features)
        m=np.asarray(state.get("mean"),dtype=float)
        P=np.asarray(state.get("covariance"),dtype=float)
        # Discount old information and add process noise.
        P=P/max(settings.forgetting_factor,1e-9)+np.eye(len(x))*settings.process_noise
        w=max(p*(1-p),1e-6)
        Px=P@x
        denom=1.0+w*float(x@Px)
        # Equivalent rank-one Hessian inverse update.
        P_new=P-(w/denom)*np.outer(Px,Px)
        m_new=m+(Px/denom)*(y-p)
        # Numerical symmetry / floor.
        P_new=(P_new+P_new.T)/2.0
        eig_min=float(np.linalg.eigvalsh(P_new).min())
        if eig_min<=1e-10:
            P_new+=np.eye(len(x))*(1e-10-eig_min+1e-12)
        out["mean"]=m_new.tolist(); out["covariance"]=P_new.tolist(); out["updates"]=int(state.get("updates",0))+1
    return out,prediction


def state_sha256(state: Dict[str,Any]) -> str:
    raw=json.dumps(state,sort_keys=True,separators=(",",":"),allow_nan=False)
    return sha256(raw.encode("utf-8")).hexdigest()
