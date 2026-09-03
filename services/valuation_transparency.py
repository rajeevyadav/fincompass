"""
Valuation transparency, key-risk flags, and methodology footer.

Presentation-layer only: this module never touches services/scoring.py, never
changes the blended Valuation score or its composite weight, and produces no
rating badge, single price target, or blended "average of approaches" number
(enforced by tests/test_valuation_transparency.py).

The per-approach implied-price TABLE is rendered client-side (the scoring path
deliberately runs without a current price to avoid a network call — see
services/analyzer.py). This module exposes only the pieces that need no live
price: the two-tier key-risk flags and the methodology footer, both derived
from data already present in a scoring result.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import NON_AFFILIATION_NOTICE, SECTOR_RISK_TAGS
from services.posture import _weak_pillars  # reuse the shared weak-pillar detection

# Plain-language restatement of a weak pillar as a risk (§2.2, tier 1).
# Sentence case; no action verbs, matching the posture guardrail.
_WEAK_PILLAR_RISK = {
    "quality": "Earnings quality and returns on capital look weak relative to peers.",
    "moat": "The durability of the competitive position looks weak relative to peers.",
    "safety": "Elevated leverage or thin liquidity relative to peers.",
    "valuation": "The current price looks rich relative to the sector on the blended multiples.",
    "cycle": "The current regime signals look unfavorable relative to history.",
}


def mechanical_flags(pillars: Dict[str, Any]) -> List[str]:
    """Tier 1: weak pillars restated as plain-language risks (§2.2)."""
    return [_WEAK_PILLAR_RISK[k] for k in _weak_pillars(pillars) if k in _WEAK_PILLAR_RISK]


def sector_flags(sector: Optional[str]) -> List[str]:
    """Tier 2: generic, sector-keyed structural risk tags (§2.2)."""
    return list(SECTOR_RISK_TAGS.get(str(sector or "").strip(), []))


def methodology_footer(pillars: Dict[str, Any]) -> str:
    """One-line valuation basis from the live P/E peer median actually used (§2.3)."""
    val = (pillars.get("valuation", {}) or {}).get("details", {}) or {}
    pe = val.get("pe", {}) or {}
    baseline = pe.get("sector_baseline")
    peer = pe.get("peer", {}) or {}
    n = peer.get("n")
    if baseline and n:
        return (
            f"Valuation basis: live sector P/E median {float(baseline):.1f}x "
            f"from {int(n)} peer companies · Multiples window: trailing twelve months"
        )
    return (
        "Valuation basis: no live sector P/E peer sample was available; a "
        "reduced-weight absolute fallback curve was used · Multiples window: "
        "trailing twelve months"
    )


def build_valuation_transparency(result: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the price-independent transparency block from a scoring result."""
    pillars = result.get("pillars", {}) or {}
    sector = result.get("sector")
    mech = mechanical_flags(pillars)
    sect = sector_flags(sector)
    return {
        "risk_flags": {
            "mechanical": mech,
            "sector": sect,
            "caption": "Mechanical flags mirror weak pillars; sector flags are generic structural risks.",
        },
        "methodology": methodology_footer(pillars),
        "non_affiliation": NON_AFFILIATION_NOTICE,
        "implied_price_note": (
            "Each lens shown independently. FinCompass does not average these into a "
            "price target — see Methodology."
        ),
    }
