"""action_policy_v1: table-driven verification of the five-verb interpretation policy.

No model is trained here. The policy maps (probability, tier, safety, position,
data) to exactly one verb, and Limited evidence may only ever Watch.
"""
import pytest

from services import action_policy as A


@pytest.mark.parametrize("p, tier, kw, expected", [
    # No usable model or missing data -> Don't decide.
    (0.70, None, {}, A.DONT_DECIDE),
    (0.70, "rejected", {}, A.DONT_DECIDE),
    (0.70, "validated_research", {"data_ok": False}, A.DONT_DECIDE),
    (None, "validated_research", {}, A.DONT_DECIDE),
    # Limited evidence (Bayesian baseline) may only Watch, whatever p is.
    (0.80, "bayesian_baseline", {}, A.WATCH),
    (0.20, "bayesian_baseline", {}, A.WATCH),
    # Research tier drives money verbs around the frozen bars.
    (0.61, "validated_research", {"position_weight": 0.05}, A.DCA_SMALL),
    (0.58, "validated_research", {}, A.DCA_SMALL),      # boundary is inclusive
    (0.50, "validated_research", {}, A.HOLD),
    (0.42, "validated_research", {}, A.TRIM),           # boundary is inclusive
    (0.30, "validated_research", {}, A.TRIM),
    # Market tier behaves like research (>= research rank).
    (0.61, "validated_market", {}, A.DCA_SMALL),
    # Safety / position override toward Trim even with a decent probability.
    (0.61, "validated_research", {"safety_broken": True}, A.TRIM),
    (0.61, "validated_research", {"position_weight": 0.5}, A.TRIM),
])
def test_action_table(p, tier, kw, expected):
    assert A.decide_action(p, tier, **kw)["action"] == expected


def test_never_emits_a_buy_or_sell_all_verb():
    verbs = {A.DONT_DECIDE, A.WATCH, A.DCA_SMALL, A.HOLD, A.TRIM}
    for p in (0.0, 0.42, 0.5, 0.58, 0.99):
        for tier in (None, "bayesian_baseline", "validated_research", "validated_market"):
            out = A.decide_action(p, tier)
            assert out["action"] in verbs
            assert "buy" not in out["action"] and "sell_all" not in out["action"]


def test_limited_high_probability_never_becomes_an_action():
    # The honesty test: a Limited-evidence 54% is not "DCA a little".
    out = A.decide_action(0.54, "bayesian_baseline")
    assert out["action"] == A.WATCH


def test_result_declares_policy_id_and_branch():
    out = A.decide_action(0.61, "validated_research", position_weight=0.05)
    assert out["action_policy_id"] == "action_policy_v1"
    assert out["branch"] == "research_prob_at_or_above_bar"
    assert out["plain_language_summary"] and out["disclaimer"] == "Not advice. A guess can be wrong."


def test_changing_a_threshold_would_be_a_new_policy_version():
    # The bars are frozen constants, part of the versioned contract.
    assert A.DCA_MIN_PROB == 0.58 and A.TRIM_MAX_PROB == 0.42
    assert A.POLICY_ID == "action_policy_v1"
