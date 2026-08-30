"""Mandatory scientific Forecast preflight."""
from __future__ import annotations
from typing import Any, Dict
from services.model_selection import applicability


def evaluate_preflight(instrument: Dict[str, Any], benchmark: Dict[str, Any], manifest: Dict[str, Any] | None, *, data_ready: bool) -> Dict[str, Any]:
    if instrument.get("asset_class") == "unknown":
        return {"data_ready": data_ready, "computationally_compatible": False, "scientifically_supported": False, "reason_codes": ["INSTRUMENT_CLASSIFICATION_UNAVAILABLE"]}
    if not benchmark.get("supported"):
        return {"data_ready": data_ready, "computationally_compatible": False, "scientifically_supported": False, "reason_codes": ["BENCHMARK_UNAVAILABLE"]}
    if manifest is None:
        return {"data_ready": data_ready, "computationally_compatible": True, "scientifically_supported": False, "reason_codes": ["NO_ELIGIBLE_MODEL"]}
    verdict = applicability(manifest, instrument, benchmark)
    return {"data_ready": bool(data_ready), "computationally_compatible": True, "scientifically_supported": bool(verdict["supported"]), "reason_codes": ([] if verdict["supported"] else [verdict["reason_code"]])}
