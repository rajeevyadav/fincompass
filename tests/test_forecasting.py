from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from api import app
from forecasting.bayesian import BayesianLogisticClassifier
from forecasting.config import get_profile, settings_from_dict
from forecasting.features import build_price_features
from forecasting.model import dataset_validation_tier
from forecasting.metrics import date_cluster_bootstrap
from forecasting.registry import registry_status
from forecasting.sec_fundamentals import extract_annual_fundamentals
from forecasting.split import purged_chronological_split
from tools.audit_forecast_dataset import audit_bundle


def _prices(n=420, future_bump=0.0):
    idx = pd.bdate_range("2020-01-01", periods=n)
    close = 100 * np.exp(np.linspace(0, 0.35, n))
    if future_bump:
        close[-20:] *= future_bump
    return pd.DataFrame({"Close": close, "Volume": np.linspace(1e6, 2e6, n)}, index=idx)


def test_price_features_do_not_change_when_future_prices_change():
    base = _prices()
    changed = _prices(future_bump=8.0)
    benchmark = _prices()
    a = build_price_features(base, benchmark)
    b = build_price_features(changed, benchmark)
    # A date well before the modified tail must be identical: no future lookup.
    date = a.index[-40]
    pd.testing.assert_series_equal(a.loc[date], b.loc[date], check_names=False)


def test_purged_split_prevents_target_overlap_and_applies_embargo():
    settings = settings_from_dict({"horizon_trading_days": 63, "embargo_trading_days": 63}, base="standard")
    dates = pd.bdate_range("2010-01-01", periods=900)[::10]
    df = pd.DataFrame({
        "date": dates,
        "target_end_date": dates + pd.offsets.BDay(63),
        "ticker": "SIM",
        "x": np.arange(len(dates), dtype=float),
        "target_outperform": np.arange(len(dates)) % 2,
    })
    result = purged_chronological_split(df, settings)
    val_start = pd.Timestamp(result.metadata["val_start"])
    test_start = pd.Timestamp(result.metadata["test_start"])
    assert result.train["target_end_date"].max() < val_start
    assert result.validation["target_end_date"].max() < test_start
    assert result.train["date"].max() < val_start - pd.offsets.BDay(63)


def test_bayesian_logistic_returns_ordered_probability_intervals():
    rng = np.random.default_rng(7)
    X = rng.normal(size=(500, 3))
    p = 1 / (1 + np.exp(-(0.7 * X[:, 0] - 0.4 * X[:, 1])))
    y = (rng.random(500) < p).astype(int)
    model = BayesianLogisticClassifier(prior_sigma=1.5, random_seed=7).fit(X, y)
    mean, lo, hi = model.posterior_probability_interval(X[:10], draws=300, level=0.9)
    assert np.all((mean >= 0) & (mean <= 1))
    assert np.all(lo <= hi)
    assert np.all((lo >= 0) & (hi <= 1))


def test_validation_tier_requires_dataset_quality_for_market_grade():
    report = {"synthetic": False, "data_quality": {"point_in_time_features": True, "survivorship_control": False, "delistings_included": False, "corporate_action_adjusted": True}}
    assert dataset_validation_tier(report, True) == "validated_research"
    report["data_quality"].update({"survivorship_control": True, "delistings_included": True})
    # Bare affirmative flags are not enough for market-grade governance.
    assert dataset_validation_tier(report, True) == "validated_research"
    report["data_quality"]["evidence"] = {
        "point_in_time_features": "feature availability audit",
        "survivorship_control": "point-in-time membership source",
        "delistings_included": "delisting reconciliation",
        "corporate_action_adjusted": "price adjustment audit",
    }
    assert dataset_validation_tier(report, True) == "validated_market"
    report["synthetic"] = True
    assert dataset_validation_tier(report, True) == "fixture_only"


def test_settings_reject_unknown_or_invalid_fields():
    assert get_profile("strict").horizon_trading_days == 252
    try:
        settings_from_dict({"made_up": 1})
        assert False, "unknown setting should fail"
    except ValueError:
        pass
    try:
        settings_from_dict({"horizon_trading_days": 5})
        assert False, "invalid horizon should fail"
    except ValueError:
        pass
    for invalid in [
        {"use_random_forest": "false"},
        {"benchmark": "SPY;DROP"},
        {"random_seed": -1},
        {"min_auc": 2.0},
    ]:
        try:
            settings_from_dict(invalid)
            assert False, f"invalid setting should fail: {invalid}"
        except (TypeError, ValueError):
            pass


def test_sec_features_use_filing_date_as_availability_date():
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"form":"10-K","filed":"2022-02-15","accn":"a1","fy":2021,"fp":"FY","end":"2021-12-31","val":100.0},
            {"form":"10-K","filed":"2023-02-15","accn":"a2","fy":2022,"fp":"FY","end":"2022-12-31","val":120.0},
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            {"form":"10-K","filed":"2022-02-15","accn":"a1","fy":2021,"fp":"FY","end":"2021-12-31","val":10.0},
            {"form":"10-K","filed":"2023-02-15","accn":"a2","fy":2022,"fp":"FY","end":"2022-12-31","val":18.0},
        ]}},
        "Assets": {"units": {"USD": [
            {"form":"10-K","filed":"2022-02-15","accn":"a1","fy":2021,"fp":"FY","end":"2021-12-31","val":200.0},
            {"form":"10-K","filed":"2023-02-15","accn":"a2","fy":2022,"fp":"FY","end":"2022-12-31","val":210.0},
        ]}},
    }}}
    df = extract_annual_fundamentals(facts)
    assert list(df["available_date"].dt.strftime("%Y-%m-%d")) == ["2022-02-15", "2023-02-15"]
    assert abs(float(df.iloc[1]["sec_revenue_growth_yoy"]) - 0.2) < 1e-9




def test_sec_amendment_growth_uses_prior_fiscal_year_not_same_year_original():
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"form":"10-K","filed":"2022-02-15","accn":"a1","fy":2021,"fp":"FY","end":"2021-12-31","val":100.0},
            {"form":"10-K","filed":"2023-02-15","accn":"a2","fy":2022,"fp":"FY","end":"2022-12-31","val":120.0},
            {"form":"10-K/A","filed":"2023-04-01","accn":"a2a","fy":2022,"fp":"FY","end":"2022-12-31","val":125.0},
        ]}},
    }}}
    df = extract_annual_fundamentals(facts).sort_values("available_date").reset_index(drop=True)
    assert pd.isna(df.loc[0, "sec_revenue_growth_yoy"])
    assert abs(float(df.loc[1, "sec_revenue_growth_yoy"]) - 0.20) < 1e-9
    assert abs(float(df.loc[2, "sec_revenue_growth_yoy"]) - 0.25) < 1e-9

def test_sec_missing_debt_stays_missing_instead_of_becoming_zero():
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            {"form":"10-K","filed":"2023-02-15","accn":"a1","fy":2022,"fp":"FY","end":"2022-12-31","val":100.0},
        ]}},
        "StockholdersEquity": {"units": {"USD": [
            {"form":"10-K","filed":"2023-02-15","accn":"a1","fy":2022,"fp":"FY","end":"2022-12-31","val":50.0},
        ]}},
    }}}
    df = extract_annual_fundamentals(facts)
    assert pd.isna(df.iloc[0]["sec_debt_to_equity"])

def test_forecast_api_exposes_schema_and_blocks_fixture_as_live():
    client = TestClient(app)
    schema = client.get("/api/v3/settings/schema")
    assert schema.status_code == 200
    body = schema.json()
    assert "strict" in body["settings"]["profiles"]
    assert set(body["settings"]["fields"]) == set(body["settings"]["profiles"]["strict"])
    validated = client.post("/api/v3/settings/validate", json={"_profile":"strict", "horizon_trading_days":126, "embargo_trading_days":126})
    assert validated.status_code == 200
    assert validated.json()["settings"]["horizon_trading_days"] == 126
    status = client.get("/api/v3/forecast/status")
    assert status.status_code == 200
    assert status.json()["usable_models"] == 0
    live = client.get("/api/v3/forecast/AAPL")
    assert live.status_code == 409
    assert live.json()["available"] is False


def test_fixture_registry_is_not_usable_for_live_forecast():
    status = registry_status()
    assert status["models_total"] >= 1
    assert status["usable_models"] == 0
    manifests = list(Path("models").glob("*.json"))
    assert manifests
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["model_id"] == manifest["model_sha256"][:16]


def test_fixture_manifest_has_hash_sidecar():
    sidecar = Path("datasets/fixtures/dataset_manifest.sha256")
    assert sidecar.exists()
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    from hashlib import sha256
    actual = sha256(Path("datasets/fixtures/dataset_manifest.json").read_bytes()).hexdigest()
    assert actual == expected


def test_bundled_fixture_passes_dataset_audit():
    report = audit_bundle(Path("datasets/fixtures"))
    assert report["passed"] is True
    assert all(report["checks"].values())
    assert report["details"]["synthetic"] is True


def test_date_block_bootstrap_preserves_configured_block_metadata():
    rng = np.random.default_rng(99)
    dates = pd.bdate_range("2020-01-01", periods=20)
    rows = []
    for d in dates:
        for i in range(4):
            rows.append({"date": d, "target_outperform": i % 2, "p": float(np.clip(0.35 + 0.3 * (i % 2) + rng.normal(0, 0.03), 0.01, 0.99))})
    report = date_cluster_bootstrap(pd.DataFrame(rows), "p", reference_rate=0.5, draws=60, block_dates=5)
    assert report["_meta"]["method"] == "moving_date_block_cross_sectional_cluster"
    assert report["_meta"]["block_dates"] == 5
    assert "brier_skill" in report


def test_fixture_walk_forward_folds_are_purged_and_embargoed():
    payload = json.loads(Path("datasets/fixtures/validation_report.json").read_text(encoding="utf-8"))
    for fold in payload["report"]["walk_forward"]["folds"]:
        assert pd.Timestamp(fold["train_target_end_max"]) < pd.Timestamp(fold["test_start"])
        assert pd.Timestamp(fold["train_date_max"]) < pd.Timestamp(fold["embargo_cutoff"])
