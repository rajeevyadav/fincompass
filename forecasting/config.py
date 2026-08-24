"""Forecast-anchor configuration inherited from FinCompass 3.0 and governed by FinCompass 4.0.

The settings are intentionally explicit because a probability forecast is only
meaningful relative to a fixed target definition, data protocol, split policy,
and validation gate. Target-defining settings are written into every model
manifest and changing them requires retraining.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
import re
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class ForecastSettings:
    # Target definition
    horizon_trading_days: int = 252
    benchmark: str = "SPY"
    excess_return_threshold: float = 0.00
    sample_step_trading_days: int = 21

    # Temporal split / leakage control
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    test_fraction: float = 0.20
    embargo_trading_days: int = 252

    # Model / posterior
    bayesian_prior_sigma: float = 1.50
    posterior_draws: int = 1200
    prediction_credible_level: float = 0.90
    random_seed: int = 37001
    use_hist_gradient_boosting: bool = True
    use_random_forest: bool = True
    calibration_method: str = "sigmoid"  # sigmoid | isotonic

    # Validation / bootstrap
    walk_forward_splits: int = 4
    bootstrap_draws: int = 300
    bootstrap_block_dates: int = 0  # 0 = auto ceil(horizon/sample_step)
    min_test_samples: int = 500
    min_class_count: int = 100
    min_test_dates: int = 24
    min_test_span_days: int = 540
    min_auc: float = 0.52
    min_brier_skill: float = 0.00
    min_log_loss_skill: float = 0.00
    max_ece: float = 0.08
    min_bootstrap_brier_skill_low: float = 0.00
    min_bootstrap_log_loss_skill_low: float = 0.00
    min_bootstrap_auc_low: float = 0.50
    max_bootstrap_ece_high: float = 0.10
    min_calibration_slope: float = 0.50
    max_calibration_slope: float = 1.50
    min_positive_walk_forward_fraction: float = 0.50

    # Abstention / presentation
    abstain_if_interval_crosses_half: bool = False
    abstain_probability_band: float = 0.03

    def validate(self) -> "ForecastSettings":
        int_fields = {
            "horizon_trading_days": self.horizon_trading_days,
            "sample_step_trading_days": self.sample_step_trading_days,
            "embargo_trading_days": self.embargo_trading_days,
            "posterior_draws": self.posterior_draws,
            "random_seed": self.random_seed,
            "walk_forward_splits": self.walk_forward_splits,
            "bootstrap_draws": self.bootstrap_draws,
            "bootstrap_block_dates": self.bootstrap_block_dates,
            "min_test_samples": self.min_test_samples,
            "min_class_count": self.min_class_count,
            "min_test_dates": self.min_test_dates,
            "min_test_span_days": self.min_test_span_days,
        }
        for name, value in int_fields.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        for name, value in {
            "train_fraction": self.train_fraction,
            "validation_fraction": self.validation_fraction,
            "test_fraction": self.test_fraction,
            "excess_return_threshold": self.excess_return_threshold,
            "bayesian_prior_sigma": self.bayesian_prior_sigma,
            "prediction_credible_level": self.prediction_credible_level,
            "min_auc": self.min_auc,
            "min_brier_skill": self.min_brier_skill,
            "min_log_loss_skill": self.min_log_loss_skill,
            "max_ece": self.max_ece,
            "min_bootstrap_brier_skill_low": self.min_bootstrap_brier_skill_low,
            "min_bootstrap_log_loss_skill_low": self.min_bootstrap_log_loss_skill_low,
            "min_bootstrap_auc_low": self.min_bootstrap_auc_low,
            "max_bootstrap_ece_high": self.max_bootstrap_ece_high,
            "min_calibration_slope": self.min_calibration_slope,
            "max_calibration_slope": self.max_calibration_slope,
            "min_positive_walk_forward_fraction": self.min_positive_walk_forward_fraction,
            "abstain_probability_band": self.abstain_probability_band,
        }.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")
        for name, value in {
            "use_hist_gradient_boosting": self.use_hist_gradient_boosting,
            "use_random_forest": self.use_random_forest,
            "abstain_if_interval_crosses_half": self.abstain_if_interval_crosses_half,
        }.items():
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be boolean")
        if not isinstance(self.benchmark, str) or not re.fullmatch(r"[A-Za-z0-9.^=-]{1,15}", self.benchmark.strip()):
            raise ValueError("benchmark must be a valid ticker-like symbol")
        if self.horizon_trading_days < 21 or self.horizon_trading_days > 756:
            raise ValueError("horizon_trading_days must be between 21 and 756")
        if self.sample_step_trading_days < 1 or self.sample_step_trading_days > 63:
            raise ValueError("sample_step_trading_days must be between 1 and 63")
        if not (0.0 <= self.excess_return_threshold <= 1.0):
            raise ValueError("excess_return_threshold must be between 0 and 1")
        total = self.train_fraction + self.validation_fraction + self.test_fraction
        if abs(total - 1.0) > 1e-9:
            raise ValueError("train/validation/test fractions must sum to 1")
        if min(self.train_fraction, self.validation_fraction, self.test_fraction) <= 0:
            raise ValueError("split fractions must all be positive")
        if self.embargo_trading_days < 0:
            raise ValueError("embargo_trading_days must be non-negative")
        if self.bayesian_prior_sigma <= 0:
            raise ValueError("bayesian_prior_sigma must be positive")
        if self.posterior_draws < 100:
            raise ValueError("posterior_draws must be at least 100")
        if not (0.50 < self.prediction_credible_level < 1.0):
            raise ValueError("prediction_credible_level must be between 0.5 and 1")
        if self.random_seed < 0 or self.random_seed > 2147483647:
            raise ValueError("random_seed must be between 0 and 2147483647")
        if self.calibration_method not in {"sigmoid", "isotonic"}:
            raise ValueError("calibration_method must be sigmoid or isotonic")
        if self.walk_forward_splits < 2 or self.walk_forward_splits > 20:
            raise ValueError("walk_forward_splits must be between 2 and 20")
        if self.bootstrap_draws < 50 or self.bootstrap_draws > 5000:
            raise ValueError("bootstrap_draws must be between 50 and 5000")
        if self.bootstrap_block_dates < 0 or self.bootstrap_block_dates > 252:
            raise ValueError("bootstrap_block_dates must be between 0 and 252")
        if self.min_test_samples < 100:
            raise ValueError("min_test_samples must be at least 100")
        if self.min_class_count < 20:
            raise ValueError("min_class_count must be at least 20")
        if self.min_test_dates < 6:
            raise ValueError("min_test_dates must be at least 6")
        if self.min_test_span_days < 90:
            raise ValueError("min_test_span_days must be at least 90")
        if not (0.0 <= self.min_auc <= 1.0):
            raise ValueError("min_auc must be in [0,1]")
        if not (-1.0 <= self.min_brier_skill <= 1.0) or not (-1.0 <= self.min_log_loss_skill <= 1.0):
            raise ValueError("skill thresholds must be in [-1,1]")
        if not (0.0 <= self.max_ece <= 0.5):
            raise ValueError("max_ece must be between 0 and 0.5")
        if not (-1.0 <= self.min_bootstrap_brier_skill_low <= 1.0):
            raise ValueError("min_bootstrap_brier_skill_low must be in [-1,1]")
        if not (-1.0 <= self.min_bootstrap_log_loss_skill_low <= 1.0):
            raise ValueError("min_bootstrap_log_loss_skill_low must be in [-1,1]")
        if not (0.0 <= self.min_bootstrap_auc_low <= 1.0):
            raise ValueError("min_bootstrap_auc_low must be in [0,1]")
        if not (0.0 <= self.max_bootstrap_ece_high <= 0.5):
            raise ValueError("max_bootstrap_ece_high must be in [0,0.5]")
        if self.min_calibration_slope <= 0 or self.max_calibration_slope <= self.min_calibration_slope:
            raise ValueError("calibration slope limits are invalid")
        if not (0.0 <= self.min_positive_walk_forward_fraction <= 1.0):
            raise ValueError("min_positive_walk_forward_fraction must be in [0,1]")
        if not (0.0 <= self.abstain_probability_band <= 0.25):
            raise ValueError("abstain_probability_band must be in [0,0.25]")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


VALIDATION_PROFILES: Dict[str, ForecastSettings] = {
    "strict": ForecastSettings(),
    "standard": replace(
        ForecastSettings(),
        min_test_samples=300,
        min_class_count=60,
        min_test_dates=18,
        min_test_span_days=365,
        min_auc=0.51,
        max_ece=0.10,
        min_bootstrap_brier_skill_low=-0.02,
        min_bootstrap_log_loss_skill_low=-0.02,
        min_bootstrap_auc_low=0.48,
        max_bootstrap_ece_high=0.14,
        min_calibration_slope=0.40,
        max_calibration_slope=1.75,
        bootstrap_draws=200,
    ),
    "exploratory": replace(
        ForecastSettings(),
        min_test_samples=150,
        min_class_count=30,
        min_test_dates=9,
        min_test_span_days=180,
        min_auc=0.50,
        min_brier_skill=-0.02,
        min_log_loss_skill=-0.02,
        max_ece=0.15,
        min_bootstrap_brier_skill_low=-0.08,
        min_bootstrap_log_loss_skill_low=-0.08,
        min_bootstrap_auc_low=0.45,
        max_bootstrap_ece_high=0.22,
        min_calibration_slope=0.25,
        max_calibration_slope=2.5,
        walk_forward_splits=3,
        bootstrap_draws=100,
    ),
}

TARGET_DEFINING_FIELDS: Tuple[str, ...] = (
    "horizon_trading_days",
    "benchmark",
    "excess_return_threshold",
    "sample_step_trading_days",
)


def get_profile(name: str = "strict") -> ForecastSettings:
    key = (name or "strict").strip().lower()
    if key not in VALIDATION_PROFILES:
        raise ValueError(f"Unknown forecast profile: {name}")
    return VALIDATION_PROFILES[key].validate()


def settings_from_dict(data: Dict[str, Any], base: str = "strict") -> ForecastSettings:
    base_settings = get_profile(base)
    allowed = set(base_settings.to_dict())
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"Unknown forecast setting(s): {', '.join(sorted(unknown))}")
    return replace(base_settings, **data).validate()


def settings_schema() -> Dict[str, Any]:
    d = ForecastSettings().to_dict()
    return {
        "profiles": {k: v.to_dict() for k, v in VALIDATION_PROFILES.items()},
        "target_defining_fields": list(TARGET_DEFINING_FIELDS),
        "fields": {
            "horizon_trading_days": {"type": "integer", "min": 21, "max": 756, "default": d["horizon_trading_days"], "requires_retrain": True},
            "benchmark": {"type": "ticker", "default": d["benchmark"], "requires_retrain": True},
            "excess_return_threshold": {"type": "number", "min": 0, "max": 1, "default": d["excess_return_threshold"], "requires_retrain": True},
            "sample_step_trading_days": {"type": "integer", "min": 1, "max": 63, "default": d["sample_step_trading_days"], "requires_retrain": True},
            "train_fraction": {"type": "number", "min": 0.4, "max": 0.8, "default": d["train_fraction"], "requires_retrain": True},
            "validation_fraction": {"type": "number", "min": 0.1, "max": 0.3, "default": d["validation_fraction"], "requires_retrain": True},
            "test_fraction": {"type": "number", "min": 0.1, "max": 0.3, "default": d["test_fraction"], "requires_retrain": True},
            "embargo_trading_days": {"type": "integer", "min": 0, "max": 756, "default": d["embargo_trading_days"], "requires_retrain": True},
            "bayesian_prior_sigma": {"type": "number", "min": 0.25, "max": 5.0, "default": d["bayesian_prior_sigma"], "requires_retrain": True},
            "posterior_draws": {"type": "integer", "min": 100, "max": 20000, "default": d["posterior_draws"], "requires_retrain": False},
            "prediction_credible_level": {"type": "number", "min": 0.8, "max": 0.99, "default": d["prediction_credible_level"], "requires_retrain": False},
            "use_hist_gradient_boosting": {"type": "boolean", "default": d["use_hist_gradient_boosting"], "requires_retrain": True},
            "use_random_forest": {"type": "boolean", "default": d["use_random_forest"], "requires_retrain": True},
            "calibration_method": {"type": "enum", "values": ["sigmoid", "isotonic"], "default": d["calibration_method"], "requires_retrain": True},
            "random_seed": {"type": "integer", "min": 0, "max": 2147483647, "default": d["random_seed"], "requires_retrain": True},
            "walk_forward_splits": {"type": "integer", "min": 2, "max": 20, "default": d["walk_forward_splits"], "requires_retrain": False},
            "bootstrap_draws": {"type": "integer", "min": 50, "max": 5000, "default": d["bootstrap_draws"], "requires_retrain": False},
            "bootstrap_block_dates": {"type": "integer", "min": 0, "max": 252, "default": d["bootstrap_block_dates"], "requires_retrain": False},
            "min_test_samples": {"type": "integer", "min": 100, "max": 1000000, "default": d["min_test_samples"], "requires_retrain": False},
            "min_class_count": {"type": "integer", "min": 20, "max": 500000, "default": d["min_class_count"], "requires_retrain": False},
            "min_test_dates": {"type": "integer", "min": 6, "max": 10000, "default": d["min_test_dates"], "requires_retrain": False},
            "min_test_span_days": {"type": "integer", "min": 90, "max": 20000, "default": d["min_test_span_days"], "requires_retrain": False},
            "min_auc": {"type": "number", "min": 0.5, "max": 1.0, "default": d["min_auc"], "requires_retrain": False},
            "min_brier_skill": {"type": "number", "min": -0.5, "max": 1.0, "default": d["min_brier_skill"], "requires_retrain": False},
            "min_log_loss_skill": {"type": "number", "min": -0.5, "max": 1.0, "default": d["min_log_loss_skill"], "requires_retrain": False},
            "max_ece": {"type": "number", "min": 0.01, "max": 0.5, "default": d["max_ece"], "requires_retrain": False},
            "min_bootstrap_brier_skill_low": {"type": "number", "min": -1, "max": 1, "default": d["min_bootstrap_brier_skill_low"], "requires_retrain": False},
            "min_bootstrap_log_loss_skill_low": {"type": "number", "min": -1, "max": 1, "default": d["min_bootstrap_log_loss_skill_low"], "requires_retrain": False},
            "min_bootstrap_auc_low": {"type": "number", "min": 0, "max": 1, "default": d["min_bootstrap_auc_low"], "requires_retrain": False},
            "max_bootstrap_ece_high": {"type": "number", "min": 0, "max": 0.5, "default": d["max_bootstrap_ece_high"], "requires_retrain": False},
            "min_calibration_slope": {"type": "number", "min": 0.01, "max": 5.0, "default": d["min_calibration_slope"], "requires_retrain": False},
            "max_calibration_slope": {"type": "number", "min": 0.02, "max": 10.0, "default": d["max_calibration_slope"], "requires_retrain": False},
            "min_positive_walk_forward_fraction": {"type": "number", "min": 0, "max": 1, "default": d["min_positive_walk_forward_fraction"], "requires_retrain": False},
            "abstain_if_interval_crosses_half": {"type": "boolean", "default": d["abstain_if_interval_crosses_half"], "requires_retrain": False},
            "abstain_probability_band": {"type": "number", "min": 0, "max": 0.25, "default": d["abstain_probability_band"], "requires_retrain": False},
        },
    }
