"""Model-family search + deterministic ranking.

Given an instrument classification, resolved benchmark, and requested horizon,
search the model registry for models the instrument can HONESTLY use, and rank
them by a documented policy. Guided mode never asks the user to pick a model.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from forecasting.registry import MODEL_ROOT

_USABLE_TIERS = {"validated_research", "validated_market"}
_TIER_RANK = {"validated_market": 2, "validated_research": 1}


def _load_manifests() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    root = MODEL_ROOT
    if not root.exists():
        return out
    for path in sorted(root.glob("*.json")):
        name = path.name
        if name == "active_model.json" or name.endswith("-SUMMARY.json"):
            continue
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def _domain_matches(classification: Dict[str, Any], domain: Optional[Dict[str, Any]],
                    benchmark_policy: Dict[str, Any]) -> bool:
    """True only if the instrument is inside the model's declared domain AND the
    benchmark family matches (no cross-market comparison)."""
    if not classification.get("available") or not domain:
        return False
    asset_class = str(classification.get("asset_class") or "").lower()
    region = str(classification.get("region") or "").upper()
    sec_type = str(classification.get("security_type") or "").lower()

    classes = [str(a).lower() for a in (domain.get("asset_classes") or [])]
    regions = [str(r).upper() for r in (domain.get("regions") or [])]
    if classes and asset_class not in classes:
        return False
    if regions and region and region not in regions:
        return False
    if sec_type == "etf" and not domain.get("supports_etf", False):
        return False
    if sec_type == "crypto" and not domain.get("supports_crypto", False):
        return False
    if "bond" in sec_type and not domain.get("supports_bonds", False):
        return False
    if "commodity" in sec_type and not domain.get("supports_commodity_proxies", False):
        return False
    if not benchmark_policy.get("supported"):
        return False
    model_family = domain.get("benchmark_family")
    if model_family and benchmark_policy.get("benchmark_family") != model_family:
        return False
    return True


def _horizon_months(manifest: Dict[str, Any]) -> Optional[int]:
    dom = manifest.get("applicability_domain") or {}
    tgt = manifest.get("target") or {}
    h = dom.get("target_horizon_months") or tgt.get("horizon_months")
    return int(h) if h else None


def _summary(manifest: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "model_id": manifest.get("model_id"),
        "validation_tier": manifest.get("validation_tier"),
        "horizon_months": _horizon_months(manifest),
        "benchmark": (manifest.get("target") or {}).get("benchmark"),
        "applicability_domain": manifest.get("applicability_domain"),
    }


def find_models(classification: Dict[str, Any], benchmark_policy: Dict[str, Any],
                horizon_months: int) -> Dict[str, List[Dict[str, Any]]]:
    """Return {eligible, alternatives, unsupported} model summaries.

    - eligible: usable tier, domain+benchmark match, horizon == requested.
    - alternatives: usable tier, domain+benchmark match, DIFFERENT horizon.
    - unsupported: usable tier whose domain/benchmark does not match this instrument.
    Ranking within eligible/alternatives: tier (market>research), then exact horizon.
    """
    eligible: List[Dict[str, Any]] = []
    alternatives: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, Any]] = []

    for m in _load_manifests():
        tier = str(m.get("validation_tier") or "")
        if tier not in _USABLE_TIERS:
            continue  # fixture/rejected/failed are never selectable
        domain = m.get("applicability_domain")
        if _domain_matches(classification, domain, benchmark_policy):
            if _horizon_months(m) == int(horizon_months):
                eligible.append(_summary(m))
            else:
                alternatives.append(_summary(m))
        else:
            unsupported.append(_summary(m))

    def _key(s):
        return (-_TIER_RANK.get(str(s.get("validation_tier")), 0),)

    eligible.sort(key=_key)
    alternatives.sort(key=lambda s: (-_TIER_RANK.get(str(s.get("validation_tier")), 0),
                                     abs((s.get("horizon_months") or 0) - horizon_months)))
    return {"eligible": eligible, "alternatives": alternatives, "unsupported": unsupported}
