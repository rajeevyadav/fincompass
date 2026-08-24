"""
Investor Posture indicators (D-001) — three mechanically-derived, model-free
signals computed from existing pillar/uncertainty data at the presentation
layer. These do NOT touch services/scoring.py and never produce a combined
"verdict" score. They are research signals, not buy/sell recommendations.

Guardrail (blocking): no action verbs (buy/sell/trim/hold/add/exit/enter/
open/close or synonyms) may appear in any generated copy or identifier here.
See tests/test_posture.py, which greps every generated string.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import (
    POSTURE_FUNDAMENTALS_MIN,
    POSTURE_STRONG_MIN,
    POSTURE_VALUATION_RICH_MIN,
    POSTURE_VALUATION_WEAK_MAX,
    POSTURE_WEAK_MAX,
)

# Title-Case display names. Internal key `moat` surfaces as "Durability" (the
# spec name); the lower-case forms are used inside sentence-case descriptions.
_PILLAR_NAMES = {
    "quality": "Quality",
    "moat": "Durability",
    "safety": "Safety",
    "valuation": "Valuation",
    "cycle": "Cycle",
}

# Pillar-specific phrase used when a pillar reads weak, sentence case.
_PILLAR_HINTS = {
    "quality": "the quality of earnings and returns",
    "moat": "how durable the competitive position really is",
    "safety": "leverage and liquidity",
    "valuation": "whether the price still makes sense",
    "cycle": "where it sits in its cycle",
}

_PILLAR_ORDER = ["quality", "moat", "safety", "valuation", "cycle"]


def _score(pillars: Dict[str, Any], key: str) -> float:
    try:
        return float(pillars.get(key, {}).get("score", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _weak_pillars(pillars: Dict[str, Any]) -> List[str]:
    """Pillar keys whose score falls in the "Weak" band (< POSTURE_WEAK_MAX)."""
    return [k for k in _PILLAR_ORDER if _score(pillars, k) < POSTURE_WEAK_MAX]


def _weakest_below_floor(pillars: Dict[str, Any]) -> Optional[str]:
    """Lowest-scoring pillar that is below the weak floor, else None."""
    below = [(k, _score(pillars, k)) for k in _PILLAR_ORDER if _score(pillars, k) < POSTURE_WEAK_MAX]
    if not below:
        return None
    return min(below, key=lambda kv: kv[1])[0]


def new_position_priority(
    composite: float, confidence: str, interval_width: float, pillars: Dict[str, Any]
) -> Dict[str, str]:
    """§2.1 — priority for fresh research based on composite + confidence."""
    conf = str(confidence or "Low")
    if composite >= POSTURE_STRONG_MIN and conf == "High":
        value, tone = "High", "success"
        desc = (
            "Strong fundamentals with high confidence — a reasonable starting "
            "point for deeper research."
        )
    elif composite < POSTURE_WEAK_MAX or conf == "Low":
        value, tone = "Low", "danger"
        desc = (
            "Either the composite or the confidence is weak — treat this as "
            "early-stage research, not a shortlist candidate."
        )
    else:
        value, tone = "Medium", "warning"
        weakest = _weakest_below_floor(pillars)
        reason = _PILLAR_NAMES[weakest].lower() if weakest else "the wide interval"
        desc = (
            f"Strong on some pillars, but {reason} warrants a closer read first."
        )
    return {
        "key": "new_position_priority",
        "label": "New-Position Priority",
        "value": value,
        "tone": tone,
        "description": desc,
    }


def accumulation_signal(pillars: Dict[str, Any]) -> Dict[str, str]:
    """§2.2 — whether the pillar shape matches a classic accumulation zone."""
    quality = _score(pillars, "quality")
    durability = _score(pillars, "moat")
    valuation = _score(pillars, "valuation")
    fundamentals_strong = quality >= POSTURE_FUNDAMENTALS_MIN and durability >= POSTURE_FUNDAMENTALS_MIN
    valuation_weak = valuation < POSTURE_VALUATION_WEAK_MAX

    if fundamentals_strong and valuation_weak:
        value, tone = "Yes", "success"
        desc = (
            "Strong quality and durability, weak valuation — the classic "
            "accumulation-zone shape."
        )
    elif fundamentals_strong and valuation >= POSTURE_VALUATION_RICH_MIN:
        value, tone = "No — Momentum Zone", "muted"
        desc = "Strong fundamentals, but already priced accordingly."
    elif (not fundamentals_strong) and valuation_weak:
        value, tone = "No — Check For Value Trap", "warning"
        desc = (
            "Cheap, but fundamentals are weak too — verify this isn't cheap "
            "for a structural reason."
        )
    else:
        value, tone = "No", "muted"
        desc = "Doesn't match a clean accumulation or momentum pattern right now."
    return {
        "key": "accumulation_signal",
        "label": "Accumulation Signal",
        "value": value,
        "tone": tone,
        "description": desc,
    }


def re_underwrite_trigger(pillars: Dict[str, Any]) -> Dict[str, str]:
    """§2.3 — flags when any pillar has slipped into weak territory."""
    weak = _weak_pillars(pillars)
    if not weak:
        return {
            "key": "re_underwrite_trigger",
            "label": "Re-Underwrite Trigger",
            "value": "No",
            "tone": "success",
            "description": (
                "No pillar is currently flagging weak — no specific trigger to "
                "re-examine right now."
            ),
        }

    names = [_PILLAR_NAMES[k] for k in weak]
    value = "Yes — " + ", ".join(names)

    if len(weak) == 1:
        subject = f"The {names[0]} pillar has"
        hints = _PILLAR_HINTS[weak[0]]
    else:
        subject = f"The {', '.join(names[:-1])} and {names[-1]} pillars have"
        hints = "; ".join(_PILLAR_HINTS[k] for k in weak)
    # Note: the D-001 sample copy used "if you hold a position"; "hold" is a
    # blocked verb, so the trigger is phrased without any action verb.
    desc = (
        f"{subject} moved into weak territory — worth a fresh look at {hints} "
        "specifically."
    )
    return {
        "key": "re_underwrite_trigger",
        "label": "Re-Underwrite Trigger",
        "value": value,
        "tone": "warning",
        "description": desc,
    }


def build_posture(result: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the three presentation-layer indicators from a scoring result."""
    pillars = result.get("pillars", {}) or {}
    composite = float(result.get("composite", 0.0))
    unc = result.get("uncertainty", {}) or {}
    confidence = str(unc.get("confidence") or "Low")
    interval = unc.get("credible_interval") or [composite, composite]
    try:
        interval_width = float(interval[1]) - float(interval[0])
    except (TypeError, ValueError, IndexError):
        interval_width = 0.0

    return {
        "caption": "research signals, not buy/sell recommendations",
        "indicators": [
            new_position_priority(composite, confidence, interval_width, pillars),
            accumulation_signal(pillars),
            re_underwrite_trigger(pillars),
        ],
    }
