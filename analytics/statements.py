"""Canonical financial-statement schema + provider-independent normalization.

Ratio formulas must NEVER see provider vocabulary. The flow is strictly:

    provider payload -> provider adapter (alias map) -> canonical statements -> ratios

Every canonical value keeps a normalization status so missing accounting data is
never silently turned into zero:

    reported        directly reported by the source
    mapped          taken from a provider alias for the same concept
    derived         computed from other canonical fields (e.g. FCF = OCF - CapEx)
    unavailable     not present (value is None, NOT 0)
    not_applicable  structurally meaningless for this issuer type (e.g. inventory
                    for a bank)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

REPORTED = "reported"
MAPPED = "mapped"
DERIVED = "derived"
UNAVAILABLE = "unavailable"
NOT_APPLICABLE = "not_applicable"

INCOME = "income"
BALANCE = "balance"
CASHFLOW = "cashflow"

# Canonical field names per statement kind. Provider adapters translate into these.
CANONICAL_FIELDS: Dict[str, set] = {
    INCOME: {
        "revenue", "cost_of_revenue", "gross_profit", "operating_income", "ebit",
        "ebitda", "depreciation_amortization", "interest_expense", "pretax_income",
        "tax_expense", "net_income", "shares_basic", "shares_diluted", "eps_diluted",
    },
    BALANCE: {
        "total_assets", "current_assets", "cash_and_equivalents", "inventory",
        "receivables", "total_liabilities", "current_liabilities", "payables",
        "short_term_debt", "long_term_debt", "total_debt", "total_equity",
    },
    CASHFLOW: {
        "operating_cash_flow", "capital_expenditure", "free_cash_flow",
        "dividends_paid",
    },
}


@dataclass
class Value:
    """A single canonical value with its normalization status and source."""
    value: Optional[float]
    status: str
    source: Optional[str] = None


@dataclass
class Statement:
    kind: str
    period_type: str            # "annual" | "quarterly" | "ttm"
    fiscal_end: Optional[str] = None
    currency: Optional[str] = None
    unit_scale: float = 1.0     # multiply raw values to reach absolute units
    restated: Optional[bool] = None
    provenance: Optional[Dict[str, Any]] = None
    values: Dict[str, Value] = field(default_factory=dict)

    def get(self, name: str) -> Optional[float]:
        v = self.values.get(name)
        return v.value if v else None

    def status(self, name: str) -> str:
        v = self.values.get(name)
        return v.status if v else UNAVAILABLE


def normalize(raw: Dict[str, Any], alias_map: Dict[str, str], *, kind: str,
              period_type: str, fiscal_end: Optional[str] = None,
              currency: Optional[str] = None, unit_scale: float = 1.0,
              restated: Optional[bool] = None, provenance: Optional[Dict[str, Any]] = None,
              not_applicable: Optional[set] = None) -> Statement:
    """Map a raw provider payload into a canonical statement.

    ``alias_map`` maps provider field names -> canonical names. A canonical name
    matched directly is ``reported``; matched via a differently-spelled alias is
    ``mapped``. Fields absent from the payload are ``unavailable`` (value None),
    never 0. ``unit_scale`` is applied so all canonical values share absolute units.
    """
    canon = CANONICAL_FIELDS.get(kind, set())
    st = Statement(kind=kind, period_type=period_type, fiscal_end=fiscal_end,
                   currency=currency, unit_scale=unit_scale, restated=restated,
                   provenance=provenance)
    na = not_applicable or set()

    # index the raw payload by canonical target
    resolved: Dict[str, tuple] = {}
    for raw_key, val in raw.items():
        target = alias_map.get(raw_key, raw_key if raw_key in canon else None)
        if target in canon and val is not None:
            status = REPORTED if raw_key == target else MAPPED
            resolved[target] = (val, status, raw_key)

    for name in canon:
        if name in na:
            st.values[name] = Value(None, NOT_APPLICABLE)
        elif name in resolved:
            val, status, src = resolved[name]
            try:
                num = float(val) * float(unit_scale)
            except (TypeError, ValueError):
                st.values[name] = Value(None, UNAVAILABLE, src)
                continue
            st.values[name] = Value(num, status, src)
        else:
            st.values[name] = Value(None, UNAVAILABLE)
    return st


def derive(statement: Statement) -> Statement:
    """Fill canonical fields derivable from reported ones, marking them ``derived``.

    Only fills a field that is currently unavailable and whose inputs are present.
    Never overwrites a reported/mapped value.
    """
    g = statement.get
    def set_if_absent(name: str, value: Optional[float]):
        if value is not None and statement.status(name) in (UNAVAILABLE,):
            statement.values[name] = Value(float(value), DERIVED)

    if statement.kind == INCOME:
        if g("gross_profit") is None and g("revenue") is not None and g("cost_of_revenue") is not None:
            set_if_absent("gross_profit", g("revenue") - g("cost_of_revenue"))
        # EBIT ~ operating income when not separately reported
        if g("ebit") is None and g("operating_income") is not None:
            set_if_absent("ebit", g("operating_income"))
        # EBITDA = EBIT + D&A (explicit construction; requires both)
        if g("ebitda") is None and g("ebit") is not None and g("depreciation_amortization") is not None:
            set_if_absent("ebitda", g("ebit") + g("depreciation_amortization"))
    elif statement.kind == BALANCE:
        if g("total_debt") is None and (g("short_term_debt") is not None or g("long_term_debt") is not None):
            set_if_absent("total_debt", (g("short_term_debt") or 0.0) + (g("long_term_debt") or 0.0))
    elif statement.kind == CASHFLOW:
        # CapEx is commonly negative in cash-flow statements; FCF = OCF + CapEx
        if g("free_cash_flow") is None and g("operating_cash_flow") is not None and g("capital_expenditure") is not None:
            set_if_absent("free_cash_flow", g("operating_cash_flow") + g("capital_expenditure"))
    return statement


def merged_values(*statements: Statement) -> Dict[str, Optional[float]]:
    """Flatten several canonical statements into one {field: value} view for ratios."""
    out: Dict[str, Optional[float]] = {}
    for st in statements:
        for name, v in st.values.items():
            out[name] = v.value
    return out
