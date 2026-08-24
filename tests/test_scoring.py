import math

from services.scoring import compute_scores, score_safety, score_quality


def rich_fund(**overrides):
    data = {
        "ticker": "TEST",
        "name": "Test Corp",
        "sector": "Technology",
        "source": "fixture",
        "roe": 0.20,
        "roic": 0.16,
        "operating_margin": 0.22,
        "net_margin": 0.16,
        "gross_margin": 0.55,
        "fcf_margin": 0.18,
        "revenue_growth": 0.12,
        "earnings_growth": 0.15,
        "debt_to_equity": 0.40,
        "current_ratio": 1.80,
        "interest_coverage": 10.0,
        "pe": 22.0,
        "pb": 4.0,
        "ev_ebitda": 14.0,
        "ps": 4.0,
    }
    data.update(overrides)
    return data


def test_probabilistic_output_is_deterministic_for_same_ticker():
    a = compute_scores(rich_fund())
    b = compute_scores(rich_fund())
    assert a["composite"] == b["composite"]
    assert a["uncertainty"] == b["uncertainty"]
    assert a["uncertainty"]["credible_interval"][0] < a["composite"] < a["uncertainty"]["credible_interval"][1]


def test_sparse_evidence_is_shrunk_and_marked_low_confidence():
    r = compute_scores({"ticker": "SPARSE", "sector": "Technology", "source": "fixture", "roe": 0.25})
    assert 5.0 < r["composite"] < 7.5
    assert r["uncertainty"]["confidence"] == "Low"
    assert r["uncertainty"]["evidence_coverage"] < 0.30
    assert r["data_quality"]["metric_completeness"] < 0.10


def test_negative_debt_to_equity_is_not_rewarded_as_low_leverage():
    score, details, _ = score_safety({"sector": "Industrials", "debt_to_equity": -1.2})
    assert score < 5.0
    assert details["debt_to_equity"]["score"] <= 2.0
    assert "negative book equity" in details["debt_to_equity"]["note"].lower()


def test_financial_services_avoids_industrial_balance_sheet_ratios():
    score, details, _ = score_safety({
        "sector": "Financial Services",
        "debt_to_equity": 3.0,
        "current_ratio": 0.4,
        "interest_coverage": 1.0,
    })
    assert math.isclose(score, 5.0, abs_tol=0.01)
    assert details["bayesian"]["evidence_coverage"] == 0.0
    assert "not used" in details["sector_adjustment"].lower()


def test_quality_weighting_does_not_treat_discounted_metric_as_full_denominator():
    # Gross margin has a smaller evidence weight than ROIC. A discounted metric
    # should be discounted in both numerator and denominator of the raw score.
    score, details, _ = score_quality({"sector": "Technology", "roic": 0.18, "gross_margin": 0.15})
    raw = details["bayesian"]["raw_score"]
    roic = details["roic"]["score"]
    gross = details["gross_margin"]["score"]
    expected = (roic * 1.35 + gross * 0.55) / (1.35 + 0.55)
    assert abs(raw - expected) < 0.02
    assert 0 <= score <= 10


def test_probability_labels_are_about_score_not_returns():
    r = compute_scores(rich_fund())
    text = r["uncertainty"]["interpretation"].lower()
    assert "not future investment returns" in text
    assert 0 <= r["uncertainty"]["probability_strong_score"] <= 1


def test_dependence_sensitivity_does_not_understate_independent_interval():
    fund = rich_fund()
    result = compute_scores(fund)
    u = result["uncertainty"]
    envelope = u["model_interval_90"]
    independent = u["dependence_sensitivity"]["independent_interval_90"]
    assert envelope[0] <= independent[0]
    assert envelope[1] >= independent[1]
    assert 0 <= u["probability_strong_score_range"][0] <= u["probability_strong_score_range"][1] <= 1


def test_continuous_quality_curve_avoids_threshold_cliff():
    low, _, _ = score_quality({"sector": "Technology", "roe": 0.0799})
    high, _, _ = score_quality({"sector": "Technology", "roe": 0.0801})
    assert high >= low
    assert high - low < 0.02
