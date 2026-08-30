"""Versioned formula registry + the universal research-result contract.

Every metric declares a machine-readable definition (formula, inputs, units,
conventions, policies, supported asset classes, version, reference). Results are
returned in a stable envelope so provenance and the exact formula are always
retrievable, even from efficient batch APIs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# metric_id -> definition
REGISTRY: Dict[str, Dict[str, Any]] = {}


def register(metric_id: str, *, name: str, category: str, formula: str,
             inputs: List[str], units: str, sign_convention: str,
             supported_asset_classes: List[str], version: str = "1",
             annualization: str = "none", period_assumption: str = "none",
             missing_data_policy: str = "drop non-finite",
             zero_denominator_policy: str = "return NaN",
             reference: str = "standard definition") -> None:
    """Register (or update) a metric definition. Idempotent by ``metric_id``."""
    REGISTRY[metric_id] = {
        "metric_id": metric_id, "name": name, "category": category,
        "formula": formula, "inputs": list(inputs), "units": units,
        "sign_convention": sign_convention,
        "supported_asset_classes": list(supported_asset_classes),
        "version": version, "annualization": annualization,
        "period_assumption": period_assumption,
        "missing_data_policy": missing_data_policy,
        "zero_denominator_policy": zero_denominator_policy,
        "reference": reference,
    }


def definition(metric_id: str) -> Optional[Dict[str, Any]]:
    return REGISTRY.get(metric_id)


def result(metric_id: str, value: Any, *, display_value: Optional[str] = None,
           period: Optional[str] = None, as_of: Optional[str] = None,
           inputs: Optional[Dict[str, Any]] = None,
           source_refs: Optional[List[Any]] = None,
           quality_flags: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build the universal result envelope for a computed metric."""
    definition_ = REGISTRY.get(metric_id) or {}
    return {
        "metric": definition_.get("name", metric_id),
        "value": value,
        "display_value": display_value if display_value is not None else _display(metric_id, value),
        "formula_id": metric_id,
        "period": period,
        "as_of": as_of,
        "inputs": inputs or {},
        "source_refs": source_refs or [],
        "quality_flags": quality_flags or [],
        "method_version": definition_.get("version", "1"),
    }


def _display(metric_id: str, value: Any) -> Optional[str]:
    d = REGISTRY.get(metric_id) or {}
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return "—"
    units = d.get("units")
    if units == "ratio_percent":
        return f"{v * 100:.1f}%"
    if units == "ratio":
        return f"{v:.2f}"
    return f"{v:.4f}"
