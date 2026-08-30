"""Scientific model resolution by horizon and applicability domain."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from forecasting.registry import list_model_manifests

_RANK = {"bayesian_baseline": 1, "validated_research": 2, "validated_market": 3}


def _horizon_months(m: Dict[str, Any]) -> int:
    t = m.get("target") or {}
    if t.get("horizon_months") is not None:
        return int(t["horizon_months"])
    return int(round(float(t.get("horizon_trading_days") or 0) / 21.0))


def _domain(m: Dict[str, Any]) -> Dict[str, Any]:
    return dict(m.get("applicability_domain") or {})


def applicability(manifest: Dict[str, Any], instrument: Dict[str, Any], benchmark: Dict[str, Any]) -> Dict[str, Any]:
    d = _domain(manifest)
    if not d:
        return {"supported": False, "reason_code": "MODEL_DOMAIN_UNKNOWN", "reason": "Model applicability domain is not declared."}
    if instrument.get("asset_class") not in set(d.get("asset_classes") or []):
        return {"supported": False, "reason_code": "UNSUPPORTED_ASSET_CLASS", "reason": "Asset class is outside the model domain."}
    if instrument.get("region") not in set(d.get("regions") or []):
        return {"supported": False, "reason_code": "UNSUPPORTED_REGION", "reason": "Region is outside the model domain."}
    sec = instrument.get("security_type")
    allowed_sec = set(d.get("security_types") or [])
    if allowed_sec and sec not in allowed_sec:
        return {"supported": False, "reason_code": "UNSUPPORTED_SECURITY_TYPE", "reason": "Security type is outside the model domain."}
    fam = d.get("benchmark_family")
    if fam and fam != benchmark.get("family"):
        return {"supported": False, "reason_code": "BENCHMARK_MISMATCH", "reason": "Resolved benchmark family does not match the model."}
    return {"supported": True, "reason_code": None, "reason": "Exact declared applicability-domain match."}


def select_model(instrument: Dict[str, Any], benchmark: Dict[str, Any], horizon_months: int) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for m in list_model_manifests():
        if m.get("validation_tier") not in _RANK or m.get("guided_eligible", True) is False or _horizon_months(m) != int(horizon_months):
            continue
        verdict = applicability(m, instrument, benchmark)
        if verdict["supported"]:
            candidates.append(m)
        else:
            rejected.append({"model_id": m.get("model_id"), "tier": m.get("validation_tier"), **verdict})
    candidates.sort(key=lambda m: (_RANK.get(m.get("validation_tier"), 0), m.get("created_at", "")), reverse=True)
    return {"selected": candidates[0] if candidates else None, "eligible": candidates, "rejected": rejected}
