"""Applicability preflight for forecasts.

Answers "can THIS model honestly be applied to THIS instrument?" WITHOUT running
inference, returning three separate concepts the caller must all satisfy before a
forecast is allowed:

    {"data_ready": ..., "computationally_compatible": ..., "scientifically_supported": ...}

Scientific support is NEVER inferred from feature compatibility alone — it is
decided from the instrument classification, the model's declared
applicability_domain, and the benchmark policy. Every predictable failure carries
a machine-readable reason code and honest values; the frontend maps codes to
plain language and must not parse prose.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from forecasting.features import build_price_features, build_monthly_relative_features
from forecasting.registry import load_model
from services.forecast_service import _get_price_history
from services.instrument_classification import classify_instrument
from services.benchmark_resolver import resolve_benchmark


def _rows(frame) -> int:
    return 0 if frame is None else int(len(frame))


def _domain_reasons(classification: Dict[str, Any], domain: Optional[Dict[str, Any]],
                    benchmark_policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scientific-applicability reasons: is this instrument inside the model's
    declared evidentiary domain, with a matching benchmark family?"""
    reasons: List[Dict[str, Any]] = []
    if not classification.get("available"):
        reasons.append({"code": "INSTRUMENT_CLASSIFICATION_UNAVAILABLE", "message_data": {"symbol": classification.get("symbol")}})
        return reasons
    if not domain:
        reasons.append({"code": "MODEL_DOMAIN_UNKNOWN", "message_data": {}})
        return reasons

    asset_class = str(classification.get("asset_class") or "").lower()
    region = str(classification.get("region") or "").upper()
    sec_type = str(classification.get("security_type") or "")

    supported_classes = [str(a).lower() for a in (domain.get("asset_classes") or [])]
    supported_regions = [str(r).upper() for r in (domain.get("regions") or [])]

    if supported_classes and asset_class not in supported_classes:
        reasons.append({"code": "UNSUPPORTED_ASSET_CLASS",
                        "message_data": {"asset_class": asset_class, "supported": supported_classes}})
    if supported_regions and region and region not in supported_regions:
        reasons.append({"code": "UNSUPPORTED_REGION",
                        "message_data": {"region": region, "supported": supported_regions}})

    # security-type gates (an equity ETF has asset_class 'equity' but is still an ETF)
    st_low = sec_type.lower()
    if st_low == "etf" and not domain.get("supports_etf", False):
        reasons.append({"code": "UNSUPPORTED_SECURITY_TYPE", "message_data": {"security_type": sec_type}})
    elif st_low == "crypto" and not domain.get("supports_crypto", False):
        reasons.append({"code": "UNSUPPORTED_SECURITY_TYPE", "message_data": {"security_type": sec_type}})
    elif "bond" in st_low and not domain.get("supports_bonds", False):
        reasons.append({"code": "UNSUPPORTED_SECURITY_TYPE", "message_data": {"security_type": sec_type}})
    elif "commodity" in st_low and not domain.get("supports_commodity_proxies", False):
        reasons.append({"code": "UNSUPPORTED_SECURITY_TYPE", "message_data": {"security_type": sec_type}})

    # benchmark family must match the model's declared family
    model_family = domain.get("benchmark_family")
    if not benchmark_policy.get("supported"):
        reasons.append({"code": "BENCHMARK_MISMATCH",
                        "message_data": {"reason": benchmark_policy.get("reason")}})
    elif model_family and benchmark_policy.get("benchmark_family") != model_family:
        reasons.append({"code": "BENCHMARK_MISMATCH",
                        "message_data": {"instrument_family": benchmark_policy.get("benchmark_family"),
                                         "model_family": model_family}})

    return reasons


def forecast_preflight(
    ticker: str,
    model_id: Optional[str] = None,
    profile_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the full applicability contract for (ticker, model).

    status: "ready" | "needs_data" | "unsupported"
    flags: data_ready, computationally_compatible, scientifically_supported
    reasons: [{code, message_data}]
    """
    ticker = str(ticker or "").upper()
    model, manifest = load_model(
        model_id=model_id, profile_name=profile_name, minimum_tier="validated_research"
    )
    if model is None or manifest is None:
        return {
            "status": "unsupported", "model_id": None, "target": None, "benchmark": None,
            "history": {"stock_rows": 0, "benchmark_rows": 0},
            "data_ready": False, "computationally_compatible": False, "scientifically_supported": False,
            "classification": None, "benchmark_policy": None,
            "reasons": [{"code": "NO_ELIGIBLE_MODEL", "message_data": {}}],
        }

    target = manifest.get("target") or {}
    domain = manifest.get("applicability_domain")
    benchmark = str(target.get("benchmark") or model.settings.get("benchmark") or "SPY").upper()

    # --- scientific applicability (no inference, no heavy data) -------------
    classification = classify_instrument(ticker)
    benchmark_policy = resolve_benchmark(classification)
    domain_reasons = _domain_reasons(classification, domain, benchmark_policy)
    scientifically_supported = not domain_reasons

    # --- data + computational checks (feature construction uses the MODEL's
    #     own benchmark, regardless of the instrument's resolved benchmark) --
    reasons: List[Dict[str, Any]] = list(domain_reasons)
    stock = _get_price_history(ticker)
    bench = _get_price_history(benchmark)
    stock_rows, bench_rows = _rows(stock), _rows(bench)

    data_reasons: List[Dict[str, Any]] = []
    if bench is None or bench.empty:
        data_reasons.append({"code": "BENCHMARK_UNAVAILABLE", "message_data": {"benchmark": benchmark}})
    if stock is None or stock.empty:
        data_reasons.append({"code": "INSUFFICIENT_HISTORY", "message_data": {"available_rows": stock_rows}})

    compute_reasons: List[Dict[str, Any]] = []
    if not data_reasons:
        provenance = manifest.get("dataset_provenance") or {}
        contract = str(provenance.get("feature_contract") or "price_relative_v1")
        try:
            if contract == "monthly_relative_v1":
                features = build_monthly_relative_features(stock, bench)
            else:
                features = build_price_features(stock, bench)
        except Exception:
            features = None
        if features is None or getattr(features, "empty", True):
            data_reasons.append({"code": "INSUFFICIENT_HISTORY",
                                 "message_data": {"available_rows": stock_rows, "feature_contract": contract}})
        else:
            sample = features.tail(1)
            required_sec = [c for c in model.feature_names if c.startswith("sec_")]
            if required_sec and not os.getenv("SEC_USER_AGENT", "").strip():
                compute_reasons.append({"code": "SEC_FEATURES_REQUIRED", "message_data": {}})
            else:
                missing = [c for c in model.feature_names
                           if c not in sample.columns and not c.startswith("sec_")]
                if missing:
                    compute_reasons.append({"code": "FEATURES_UNAVAILABLE", "message_data": {"missing": missing}})

    data_ready = not data_reasons
    computationally_compatible = data_ready and not compute_reasons
    reasons.extend(data_reasons)
    reasons.extend(compute_reasons)

    # --- overall status ----------------------------------------------------
    if not scientifically_supported:
        status = "unsupported"
    elif not data_ready:
        status = "needs_data"
    elif not computationally_compatible:
        status = "unsupported"
    else:
        status = "ready"

    return {
        "status": status,
        "model_id": manifest.get("model_id"),
        "validation_tier": manifest.get("validation_tier"),
        "target": target,
        "benchmark": benchmark,
        "history": {"stock_rows": stock_rows, "benchmark_rows": bench_rows},
        "data_ready": data_ready,
        "computationally_compatible": computationally_compatible,
        "scientifically_supported": scientifically_supported,
        "classification": classification,
        "benchmark_policy": benchmark_policy,
        "applicability_domain": domain,
        "reasons": reasons,
    }
