"""Declared, versioned interpretation policy that sits ON the forecast probability.

This is deliberately NOT part of any trainer and never changes the probability
``p``. It maps one already-produced forecast to one of five plain-language
postures. The constants are frozen as a named policy version; changing a
threshold is a new policy version (``action_policy_id``), never a silent tweak.

Scientific boundary (stated here, in the UI, and in the documentation):

  * The interpretation policy does NOT change the forecast probability.
  * It is NOT part of model validation; Brier/AUC/calibration say nothing about
    these thresholds. The 0.58/0.42 probability bars and the 20% position bar are
    declared *policy assumptions*, separately versioned, not statistical results.
  * It does not incorporate individualized taxes, transaction costs, risk
    tolerance, liquidity needs, or portfolio optimisation unless those inputs are
    explicitly supplied.

Governance:
  * A Limited-evidence (Bayesian baseline) forecast can only ever justify Watch —
    never a money action, regardless of how high ``p`` is.
  * The policy never emits buy-all or sell-all. ``TRIM`` ("own less") is the only
    reduce action in v1.
  * Analytics (DCF, RSI, Sharpe) do not vote here; only probability, evidence
    tier, applicability/data, a safety flag, and an optional position weight.
  * The same policy result is shown in the plain-language summary and in the
    research rationale; the research rationale additionally names the branch that
    fired, the thresholds, and the inputs used.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

POLICY_ID = "action_policy_v1"
POLICY_TYPE = "interpretation_policy"

# Frozen constants for action_policy_v1. A change here is a NEW policy version.
# These are declared policy assumptions, not thresholds established by validation.
DCA_MIN_PROB = 0.58          # research-tier probability at/above which DCA is allowed
TRIM_MAX_PROB = 0.42         # research-tier probability at/below which Trim is advised
DEFAULT_MAX_NAME_WEIGHT = 0.20  # a single position larger than this is "too big"

# The five postures — the only actions this policy may return.
DONT_DECIDE = "dont_decide"
WATCH = "watch"
DCA_SMALL = "dca_small"
HOLD = "hold"
TRIM = "trim"

# Internal validation tiers mapped to a policy tier rank.
#   0 = none/unusable, 1 = limited (Bayesian baseline), 2 = research, 3 = market
_TIER_RANK = {
    None: 0, "": 0, "none": 0, "rejected": 0, "fixture_only": 0, "unknown": 0,
    "bayesian_baseline": 1,
    "validated_research": 2,
    "validated_market": 3,
}
_RESEARCH_RANK = 2

# Plain-language posture sentences, keyed by verb.
_PLAIN_SENTENCE = {
    DONT_DECIDE: "FinCompass will not tell you what to do.",
    WATCH: "There is a number. It is not strong enough to act.",
    DCA_SMALL: "If you already meant to own a slice of the market, add a little on a schedule.",
    HOLD: "Keep the plan you have. Do nothing this week.",
    TRIM: "Own less. You do not have to sell all of it.",
}
_POSTURE_LABEL = {
    DONT_DECIDE: "Don't decide", WATCH: "Watch", DCA_SMALL: "DCA a little",
    HOLD: "Hold", TRIM: "Trim",
}


def tier_rank(tier: Optional[str]) -> int:
    return _TIER_RANK.get(str(tier).lower() if tier is not None else None, 0)


def decide_action(p: Optional[float], tier: Optional[str], *,
                  data_ok: bool = True, safety_broken: bool = False,
                  position_weight: Optional[float] = None,
                  max_name_weight: float = DEFAULT_MAX_NAME_WEIGHT) -> Dict[str, Any]:
    """Return the interpretation-policy posture for one forecast, plus the branch
    that fired.

    ``p`` is the probability of outperformance; ``tier`` is the internal
    validation tier. The result never depends on any analytics metric and never
    changes ``p``.
    """
    rank = tier_rank(tier)
    # Order matters and is part of the policy contract.
    if not data_ok or rank == 0 or p is None:
        verb, branch = DONT_DECIDE, "no_model_or_data"
    elif rank < _RESEARCH_RANK:
        # Limited evidence (Bayesian baseline): Watch only, whatever p is.
        verb, branch = WATCH, "limited_evidence_watch_only"
    elif position_weight is not None and position_weight > max_name_weight:
        verb, branch = TRIM, "position_too_large"
    elif safety_broken:
        verb, branch = TRIM, "safety_broken"
    elif float(p) >= DCA_MIN_PROB:
        verb, branch = DCA_SMALL, "research_prob_at_or_above_bar"
    elif float(p) <= TRIM_MAX_PROB:
        verb, branch = TRIM, "research_prob_at_or_below_floor"
    else:
        verb, branch = HOLD, "research_prob_near_half"
    return {
        "action": verb,
        "action_label": _POSTURE_LABEL[verb],
        "plain_language_summary": _PLAIN_SENTENCE[verb],
        "action_policy_id": POLICY_ID,
        "policy_type": POLICY_TYPE,
        "branch": branch,
        "inputs": {
            "probability_outperform": (float(p) if p is not None else None),
            "tier": tier, "tier_rank": rank, "data_ok": bool(data_ok),
            "safety_broken": bool(safety_broken), "position_weight": position_weight,
            "max_name_weight": max_name_weight,
        },
        "thresholds": {"dca_min_prob": DCA_MIN_PROB, "trim_max_prob": TRIM_MAX_PROB,
                       "max_name_weight": max_name_weight},
        "policy_note": ("A practical posture, not model output. It does not change the "
                        "probability, is not part of model validation, and uses declared, "
                        "separately versioned assumptions rather than your individual taxes, "
                        "costs, or risk tolerance."),
        "disclaimer": "Not advice. A guess can be wrong.",
    }
