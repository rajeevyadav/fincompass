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


# Plain-language expansion of the applicability reason codes, for the unavailable
# case: which scientific condition was not satisfied, in words a reader can act on.
_PLAIN_REASON = {
    "MODEL_DOMAIN_UNKNOWN": "the model does not declare an applicability domain",
    "UNSUPPORTED_ASSET_CLASS": "this asset class is outside every installed model's domain",
    "UNSUPPORTED_REGION": "this market region is outside every installed model's domain",
    "UNSUPPORTED_SECURITY_TYPE": "this security type is outside every installed model's domain",
    "BENCHMARK_MISMATCH": "no installed model is validated against this instrument's benchmark family",
    "NO_APPLICABLE_MODEL_FAMILY": "no installed model family matches this market and horizon",
    "UNSUPPORTED_INSTRUMENT": "no scientifically appropriate benchmark/model family is available for this instrument",
}

_TIER_LABEL = {"bayesian_baseline": "Limited evidence", "validated_research": "Research validated",
               "validated_market": "Market validated"}


def selection_rationale(instrument: Dict[str, Any], benchmark: Dict[str, Any],
                        horizon_months: int, selected: Optional[Dict[str, Any]],
                        rejected: List[Dict[str, Any]], eligible_count: int) -> Dict[str, Any]:
    """A human-readable 'why this model' explanation for the Forecast.

    On success it names the deciding factors (instrument classification, horizon,
    benchmark family, evidence tier, applicability); on failure it states which
    applicability condition was not satisfied in plain language. This never
    changes the forecast - it only explains the selection an expert may audit.
    """
    sec = instrument.get("security_type") or instrument.get("asset_class") or "instrument"
    region = instrument.get("region") or "?"
    fam = benchmark.get("family") or "?"
    bsym = benchmark.get("symbol") or "?"
    rej = [{"model_id": r.get("model_id"), "tier": r.get("tier"),
            "reason": r.get("reason"), "reason_code": r.get("reason_code")} for r in (rejected or [])]
    if selected is None:
        codes = [r.get("reason_code") for r in (rejected or [])]
        primary = next((c for c in ("UNSUPPORTED_ASSET_CLASS", "UNSUPPORTED_REGION",
                                     "UNSUPPORTED_SECURITY_TYPE", "BENCHMARK_MISMATCH") if c in codes),
                       "NO_APPLICABLE_MODEL_FAMILY")
        return {
            "available": False,
            "summary": ("FinCompass can analyze this instrument, but "
                        f"{_PLAIN_REASON.get(primary, 'no installed model family applies')}."),
            "primary_reason_code": primary,
            "rejected_families": rej,
            "eligible_count": eligible_count,
        }
    tier = selected.get("validation_tier")
    factors = [
        {"label": "Instrument", "value": f"{region} {str(sec).replace('_', ' ')} ({instrument.get('asset_class')})"},
        {"label": "Horizon", "value": f"{int(horizon_months)} months"},
        {"label": "Benchmark family", "value": f"{fam} ({bsym})"},
        {"label": "Evidence tier", "value": f"{_TIER_LABEL.get(tier, tier)} ({tier})"},
        {"label": "Applicability", "value": "Exact declared applicability-domain match"},
    ]
    summary = (f"FinCompass selected this model because the security is a {region} "
               f"{str(sec).replace('_', ' ')}, the requested horizon is {int(horizon_months)} months, "
               f"the benchmark family matches {fam}, and this is the strongest installed model whose "
               f"applicability contract matches the request.")
    return {
        "available": True,
        "summary": summary,
        "factors": factors,
        "rejected_families": rej,
        "eligible_count": eligible_count,
    }
