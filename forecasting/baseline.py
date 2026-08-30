"""FinCompass v2 Bayesian reference forecast model.

This module separates *model validity* from *demonstrated predictive skill*.
A hard-valid Bayesian reference may be retained as ``bayesian_baseline`` even
when the stricter validated_research gate is not met.  The tier is deliberately
not live-eligible and must never be represented as demonstrated alpha.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from forecasting.bayesian import BayesianLogisticClassifier
from forecasting.calibration import ProbabilityCalibrator
from forecasting.config import ForecastSettings
from forecasting.metrics import date_cluster_bootstrap, evaluate_probabilities

DAILY_REFERENCE_FEATURES = [
    "rel_ret_21", "rel_ret_63", "rel_ret_126", "rel_ret_252",
    "vol_63", "benchmark_vol_63", "drawdown_252", "sma_50_200",
]
MONTHLY_REFERENCE_FEATURES = [
    "rel_ret_1m", "rel_ret_3m", "rel_ret_6m", "rel_ret_12m",
    "vol_6m", "benchmark_vol_6m", "drawdown_12m", "sma_3_12",
]


@dataclass
class BayesianReferenceForecastModel:
    feature_names: List[str]
    settings: Dict[str, Any]
    bayes: BayesianLogisticClassifier
    calibrator: ProbabilityCalibrator
    train_event_rate: float
    evidence_tier: str = "bayesian_baseline"

    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.feature_names if c not in frame.columns]
        if missing:
            raise ValueError(f"forecast input missing features: {missing}")
        return frame[self.feature_names].to_numpy(dtype=float)

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        raw = self.bayes.predict_proba(self._matrix(frame))[:, 1]
        return self.calibrator.transform(raw)

    def predict_with_uncertainty(self, frame: pd.DataFrame) -> List[Dict[str, Any]]:
        X = self._matrix(frame)
        settings = ForecastSettings(**self.settings).validate()
        raw_mean, raw_lo, raw_hi = self.bayes.posterior_probability_interval(
            X,
            draws=settings.posterior_draws,
            level=settings.prediction_credible_level,
        )
        point = self.calibrator.transform(raw_mean)
        lo = self.calibrator.transform(raw_lo)
        hi = self.calibrator.transform(raw_hi)
        rows: List[Dict[str, Any]] = []
        for i in range(len(frame)):
            p = float(point[i])
            low = float(min(lo[i], hi[i]))
            high = float(max(lo[i], hi[i]))
            rows.append({
                "probability_outperform": p,
                "uncertainty_interval": [low, high],
                "uncertainty_level": settings.prediction_credible_level,
                "component_probabilities": {"bayesian_reference": p},
                "abstain": bool(low <= 0.5 <= high or abs(p - 0.5) <= settings.abstain_probability_band),
                "interpretation": (
                    "Posterior coefficient uncertainty propagated through the calibrated Bayesian reference model. "
                    "This interval is not a guaranteed interval for future market returns."
                ),
            })
        return rows


def _reference_features(train: pd.DataFrame) -> List[str]:
    if any(c in train.columns for c in MONTHLY_REFERENCE_FEATURES):
        candidates = MONTHLY_REFERENCE_FEATURES
    else:
        candidates = DAILY_REFERENCE_FEATURES
    selected = [c for c in candidates if c in train.columns]
    if len(selected) < 4:
        # Conservative fallback: numeric, point-in-time feature columns only.
        excluded = {
            "target_outperform", "forward_return", "benchmark_forward_return",
            "forward_excess_return", "date", "target_end_date",
        }
        selected = [
            c for c in train.columns
            if c not in excluded and pd.api.types.is_numeric_dtype(train[c])
        ][:12]
    return selected


def _hard_validity(train: pd.DataFrame, validation: pd.DataFrame, test: pd.DataFrame, features: List[str]) -> Dict[str, Any]:
    checks: Dict[str, bool] = {}
    checks["minimum_training_rows"] = len(train) >= 120
    checks["minimum_validation_rows"] = len(validation) >= 40
    checks["minimum_test_rows"] = len(test) >= 30
    checks["training_has_both_classes"] = train["target_outperform"].nunique() >= 2
    checks["validation_has_both_classes"] = validation["target_outperform"].nunique() >= 2
    checks["features_present"] = len(features) >= 4
    for name, part in (("train", train), ("validation", validation), ("test", test)):
        checks[f"{name}_target_matured"] = bool(part["target_outperform"].notna().all())
        checks[f"{name}_target_end_present"] = bool(part["target_end_date"].notna().all())
        if "date" in part.columns:
            d = pd.to_datetime(part["date"])
            e = pd.to_datetime(part["target_end_date"])
            checks[f"{name}_forward_endpoint_after_observation"] = bool((e > d).all())
    return {
        "passed": bool(all(checks.values())),
        "checks": checks,
        "meaning": "Hard validity checks model estimability and temporal integrity; it does not assert predictive skill.",
    }


def train_validate_bayesian_reference(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
    dataset_manifest: Dict[str, Any],
    settings: ForecastSettings,
) -> Tuple[BayesianReferenceForecastModel, Dict[str, Any], pd.DataFrame]:
    """Fit a calibrated regularized Bayesian reference model.

    The locked test is used only for evidence characterization.  Failing a
    predictive-skill threshold does not erase a hard-valid probability model.
    """
    settings.validate()
    features = _reference_features(train)
    hard = _hard_validity(train, validation, test, features)
    if not hard["passed"]:
        failed = [k for k, v in hard["checks"].items() if not v]
        raise ValueError("Bayesian reference hard-validity failure: " + ", ".join(failed))

    X_train = train[features].to_numpy(float)
    y_train = train["target_outperform"].to_numpy(int)
    X_val = validation[features].to_numpy(float)
    y_val = validation["target_outperform"].to_numpy(int)
    y_test = test["target_outperform"].to_numpy(int)

    bayes = BayesianLogisticClassifier(settings.bayesian_prior_sigma, settings.random_seed).fit(X_train, y_train)
    if bayes.coef_ is None or bayes.covariance_ is None:
        raise RuntimeError("Bayesian reference posterior was not produced")
    if not np.isfinite(bayes.coef_).all() or not np.isfinite(bayes.covariance_).all():
        raise RuntimeError("Bayesian reference posterior contains non-finite values")

    raw_val = bayes.predict_proba(X_val)[:, 1]
    calibrator = ProbabilityCalibrator(settings.calibration_method).fit(raw_val, y_val)
    model = BayesianReferenceForecastModel(
        feature_names=features,
        settings=settings.to_dict(),
        bayes=bayes,
        calibrator=calibrator,
        train_event_rate=float(np.mean(y_train)),
    )

    p_test = model.predict_proba(test)
    if not np.isfinite(p_test).all() or np.any((p_test <= 0.0) | (p_test >= 1.0)):
        raise RuntimeError("Bayesian reference produced invalid probability values")

    dev_rate = float(pd.concat([train[["target_outperform"]], validation[["target_outperform"]]])["target_outperform"].mean())
    metrics = evaluate_probabilities(y_test, p_test, reference_rate=dev_rate)
    predictions = test[[c for c in ["date", "ticker", "target_end_date", "target_outperform", "forward_excess_return"] if c in test.columns]].copy()
    predictions["probability_outperform"] = p_test
    bootstrap = date_cluster_bootstrap(
        predictions,
        "probability_outperform",
        reference_rate=dev_rate,
        draws=min(max(100, settings.bootstrap_draws), 300),
        seed=settings.random_seed,
        level=settings.prediction_credible_level,
        block_dates=(settings.bootstrap_block_dates or max(1, int(np.ceil(settings.horizon_trading_days / settings.sample_step_trading_days)))),
    )
    report = {
        "validation_tier": "bayesian_baseline",
        "hard_validity": hard,
        "locked_test_metrics": metrics,
        "bootstrap": bootstrap,
        "features": features,
        "train_event_rate": float(np.mean(y_train)),
        "validation_event_rate": float(np.mean(y_val)),
        "test_event_rate": float(np.mean(y_test)),
        "validation_reference_event_rate": dev_rate,
        "bayesian_coefficients_standardized": bayes.coefficient_summary(features),
        "calibration": {
            "method": settings.calibration_method,
            "rows": int(len(validation)),
            "event_rate": float(np.mean(y_val)),
        },
        "gate": {
            "passed": False,
            "checks": {},
            "meaning": "The strong research-validation gate was not claimed by the reference-model path.",
        },
        "interpretation": (
            "bayesian_baseline means the model is temporally valid, estimable, regularized and calibrated, "
            "but stronger out-of-sample predictive skill has not been established. It is forecast-eligible "
            "with Limited evidence labeling and is not adaptive-Live eligible."
        ),
        "dataset_quality": dataset_manifest.get("data_quality") or {},
    }
    return model, report, predictions
