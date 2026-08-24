"""FinCompass calibrated frozen-anchor probabilistic ensemble (3.0 methodology, governed by 4.0).

The locked test partition is never used to fit base models, calibrators, or
ensemble weights. It is used only once for release-gate evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from forecasting.bayesian import BayesianLogisticClassifier
from forecasting.calibration import ProbabilityCalibrator
from forecasting.config import ForecastSettings
from forecasting.features import feature_columns
from forecasting.metrics import date_cluster_bootstrap, evaluate_probabilities


@dataclass
class EnsembleForecastModel:
    feature_names: List[str]
    settings: Dict[str, Any]
    bayes: BayesianLogisticClassifier
    component_models: Dict[str, Any]
    component_calibrators: Dict[str, ProbabilityCalibrator]
    ensemble_weights: Dict[str, float]
    ensemble_calibrator: ProbabilityCalibrator
    train_event_rate: float

    def _matrix(self, frame: pd.DataFrame) -> np.ndarray:
        missing = [c for c in self.feature_names if c not in frame.columns]
        if missing:
            raise ValueError(f"forecast input missing features: {missing}")
        return frame[self.feature_names].to_numpy(dtype=float)

    def component_probabilities(self, frame: pd.DataFrame) -> Dict[str, np.ndarray]:
        X = self._matrix(frame)
        out: Dict[str, np.ndarray] = {}
        raw_bayes = self.bayes.predict_proba(X)[:, 1]
        out["bayesian_logistic"] = self.component_calibrators["bayesian_logistic"].transform(raw_bayes)
        for name, model in self.component_models.items():
            raw = model.predict_proba(X)[:, 1]
            out[name] = self.component_calibrators[name].transform(raw)
        return out

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        comps = self.component_probabilities(frame)
        raw = np.zeros(len(frame), dtype=float)
        for name, p in comps.items():
            raw += float(self.ensemble_weights.get(name, 0.0)) * p
        return self.ensemble_calibrator.transform(raw)

    def predict_with_uncertainty(self, frame: pd.DataFrame) -> List[Dict[str, Any]]:
        X = self._matrix(frame)
        comps = self.component_probabilities(frame)
        point = self.predict_proba(frame)
        settings = ForecastSettings(**self.settings).validate()
        _, bayes_lo_raw, bayes_hi_raw = self.bayes.posterior_probability_interval(
            X, draws=settings.posterior_draws, level=settings.prediction_credible_level
        )
        bayes_cal = self.component_calibrators["bayesian_logistic"]
        bayes_lo = bayes_cal.transform(bayes_lo_raw)
        bayes_hi = bayes_cal.transform(bayes_hi_raw)
        rows: List[Dict[str, Any]] = []
        for i in range(len(frame)):
            component_values = {name: float(p[i]) for name, p in comps.items()}
            low_raw = min([float(bayes_lo[i]), *component_values.values()])
            high_raw = max([float(bayes_hi[i]), *component_values.values()])
            # Final calibration is monotone for sigmoid/isotonic, so endpoints
            # can be transformed directly.
            lo, hi = self.ensemble_calibrator.transform([low_raw, high_raw])
            p = float(point[i])
            abstain = abs(p - 0.5) <= settings.abstain_probability_band
            if settings.abstain_if_interval_crosses_half and float(lo) <= 0.5 <= float(hi):
                abstain = True
            rows.append({
                "probability_outperform": p,
                "uncertainty_interval": [float(min(lo, hi)), float(max(lo, hi))],
                "uncertainty_level": settings.prediction_credible_level,
                "component_probabilities": component_values,
                "abstain": bool(abstain),
                "interpretation": "Interval combines Bayesian coefficient uncertainty and inter-model dispersion; it is not a guaranteed coverage interval for market returns.",
            })
        return rows



def _partition_validation(validation: pd.DataFrame, settings: ForecastSettings) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Create purged, embargoed chronological validation fitting stages.

    Component calibration, stacking, and final calibration must not only use
    different observation dates; their forward target windows must also resolve
    before the next stage starts. This prevents overlapping outcome windows from
    leaking dependence across fitting roles.
    """
    work = validation.copy()
    work["date"] = pd.to_datetime(work["date"])
    work["target_end_date"] = pd.to_datetime(work["target_end_date"])
    dates = np.array(sorted(work["date"].dropna().unique()))
    if len(dates) < 18:
        raise ValueError("validation partition requires at least 18 distinct observation dates for purged three-stage fitting")
    cut1 = max(6, len(dates) // 3)
    cut2 = max(cut1 + 6, (2 * len(dates)) // 3)
    cut2 = min(cut2, len(dates) - 6)
    stage2_start = pd.Timestamp(dates[cut1])
    stage3_start = pd.Timestamp(dates[cut2])

    embargo1 = stage2_start - pd.offsets.BDay(settings.embargo_trading_days)
    embargo2 = stage3_start - pd.offsets.BDay(settings.embargo_trading_days)
    p1 = work[(work["date"] < embargo1) & (work["target_end_date"] < stage2_start)].copy()
    p2 = work[(work["date"] >= stage2_start) & (work["date"] < embargo2) & (work["target_end_date"] < stage3_start)].copy()
    p3 = work[work["date"] >= stage3_start].copy()
    parts = [p1, p2, p3]
    names = ["component_calibration", "ensemble_stacking", "final_calibration"]
    meta: Dict[str, Any] = {
        "stage2_start": stage2_start.date().isoformat(),
        "stage3_start": stage3_start.date().isoformat(),
        "embargo_trading_days": int(settings.embargo_trading_days),
    }
    for name, part in zip(names, parts):
        if part.empty or part["target_outperform"].nunique() < 2:
            raise ValueError(f"{name} validation stage is empty or lacks both target classes after purge/embargo; provide more history or a shorter horizon/embargo")
        meta[name] = {
            "rows": int(len(part)),
            "distinct_dates": int(part["date"].nunique()),
            "start": pd.Timestamp(part["date"].min()).date().isoformat(),
            "end": pd.Timestamp(part["date"].max()).date().isoformat(),
            "target_end_max": pd.Timestamp(part["target_end_date"].max()).date().isoformat(),
            "event_rate": float(part["target_outperform"].mean()),
        }
    return parts[0], parts[1], parts[2], meta


def _make_component_models(settings: ForecastSettings) -> Dict[str, Any]:
    models: Dict[str, Any] = {}
    if settings.use_hist_gradient_boosting:
        models["hist_gradient_boosting"] = HistGradientBoostingClassifier(
            learning_rate=0.045,
            max_iter=180,
            max_leaf_nodes=15,
            min_samples_leaf=30,
            l2_regularization=1.0,
            random_state=settings.random_seed,
        )
    if settings.use_random_forest:
        models["random_forest"] = Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("model", RandomForestClassifier(
                n_estimators=260,
                min_samples_leaf=24,
                max_features="sqrt",
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=settings.random_seed,
            )),
        ])
    return models


def _fit_weights(component_val: Dict[str, np.ndarray], y_val: np.ndarray) -> Dict[str, float]:
    names = list(component_val)
    matrix = np.column_stack([component_val[n] for n in names])
    k = len(names)
    if k == 1:
        return {names[0]: 1.0}

    def objective(w):
        pred = np.clip(matrix @ w, 1e-6, 1 - 1e-6)
        brier = np.mean((pred - y_val) ** 2)
        penalty = 0.01 * np.sum((w - 1.0 / k) ** 2)
        return float(brier + penalty)

    result = minimize(
        objective,
        np.full(k, 1.0 / k),
        method="SLSQP",
        bounds=[(0.0, 1.0)] * k,
        constraints={"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
        options={"maxiter": 400, "ftol": 1e-12},
    )
    w = result.x if result.success else np.full(k, 1.0 / k)
    w = np.maximum(w, 0.0)
    w = w / w.sum()
    return {name: float(value) for name, value in zip(names, w)}


def _walk_forward_baseline(dev: pd.DataFrame, features: List[str], settings: ForecastSettings) -> Dict[str, Any]:
    dates = np.array(sorted(pd.to_datetime(dev["date"]).unique()))
    n = len(dates)
    splits = min(settings.walk_forward_splits, max(2, n // 8))
    fold_size = max(2, n // (splits + 2))
    rows = []
    for fold in range(splits):
        train_end = fold_size * (fold + 2)
        test_end = min(n, train_end + fold_size)
        if test_end <= train_end or train_end >= n:
            break
        train_dates = dates[:train_end]
        test_dates = dates[train_end:test_end]
        tr = dev[dev["date"].isin(train_dates)].copy()
        te = dev[dev["date"].isin(test_dates)].copy()
        test_start = pd.Timestamp(pd.to_datetime(te["date"]).min()) if not te.empty else None
        embargo_cutoff = test_start
        if test_start is not None:
            # Purge training labels that resolve into the fold's test window and
            # apply the same explicit embargo used by the final dataset split.
            tr = tr[pd.to_datetime(tr["target_end_date"]) < test_start]
            if settings.embargo_trading_days > 0:
                embargo_cutoff = test_start - pd.offsets.BDay(settings.embargo_trading_days)
                tr = tr[pd.to_datetime(tr["date"]) < embargo_cutoff]
        if len(tr) < 100 or len(te) < 30 or tr["target_outperform"].nunique() < 2 or te["target_outperform"].nunique() < 2:
            continue
        model = BayesianLogisticClassifier(settings.bayesian_prior_sigma, settings.random_seed + fold)
        model.fit(tr[features].to_numpy(float), tr["target_outperform"].to_numpy(int))
        p = model.predict_proba(te[features].to_numpy(float))[:, 1]
        m = evaluate_probabilities(te["target_outperform"].to_numpy(int), p, reference_rate=float(tr["target_outperform"].mean()))
        rows.append({
            "fold": fold + 1,
            "train_rows": len(tr),
            "test_rows": len(te),
            "train_date_max": pd.Timestamp(pd.to_datetime(tr["date"]).max()).date().isoformat(),
            "train_target_end_max": pd.Timestamp(pd.to_datetime(tr["target_end_date"]).max()).date().isoformat(),
            "test_start": test_start.date().isoformat() if test_start is not None else None,
            "test_end": pd.Timestamp(pd.to_datetime(te["date"]).max()).date().isoformat(),
            "embargo_cutoff": pd.Timestamp(embargo_cutoff).date().isoformat() if embargo_cutoff is not None else None,
            **m,
        })
    skills = [r["brier_skill"] for r in rows if np.isfinite(r.get("brier_skill", np.nan))]
    positive_fraction = float(np.mean(np.array(skills) > 0.0)) if skills else 0.0
    return {
        "folds": rows,
        "positive_brier_skill_fraction": positive_fraction,
        "median_brier_skill": float(np.median(skills)) if skills else float("nan"),
    }


def _validation_gate(metrics: Dict[str, float], bootstrap: Dict[str, Dict[str, float]], walk: Dict[str, Any], test: pd.DataFrame, settings: ForecastSettings) -> Dict[str, Any]:
    y_test = test["target_outperform"].to_numpy(int)
    class_counts = {"0": int(np.sum(y_test == 0)), "1": int(np.sum(y_test == 1))}
    test_dates = pd.to_datetime(test["date"]).dropna()
    distinct_test_dates = int(test_dates.nunique())
    test_span_days = int((test_dates.max() - test_dates.min()).days) if len(test_dates) else 0

    def boot(metric: str, bound: str, default: float) -> float:
        try:
            return float(bootstrap.get(metric, {}).get(bound, default))
        except Exception:
            return float(default)

    checks = {
        "minimum_test_samples": len(y_test) >= settings.min_test_samples,
        "minimum_each_class": min(class_counts.values()) >= settings.min_class_count,
        "minimum_test_dates": distinct_test_dates >= settings.min_test_dates,
        "minimum_test_span_days": test_span_days >= settings.min_test_span_days,
        "roc_auc": float(metrics.get("roc_auc", 0.0)) >= settings.min_auc,
        "brier_skill": float(metrics.get("brier_skill", -9.0)) >= settings.min_brier_skill,
        "log_loss_skill": float(metrics.get("log_loss_skill", -9.0)) >= settings.min_log_loss_skill,
        "ece": float(metrics.get("ece_10", 9.0)) <= settings.max_ece,
        "bootstrap_brier_skill_low": boot("brier_skill", "low", -9.0) >= settings.min_bootstrap_brier_skill_low,
        "bootstrap_log_loss_skill_low": boot("log_loss_skill", "low", -9.0) >= settings.min_bootstrap_log_loss_skill_low,
        "bootstrap_auc_low": boot("roc_auc", "low", -9.0) >= settings.min_bootstrap_auc_low,
        "bootstrap_ece_high": boot("ece_10", "high", 9.0) <= settings.max_bootstrap_ece_high,
        "calibration_slope": settings.min_calibration_slope <= float(metrics.get("calibration_slope", -9.0)) <= settings.max_calibration_slope,
        "walk_forward_stability": float(walk.get("positive_brier_skill_fraction", 0.0)) >= settings.min_positive_walk_forward_fraction,
    }
    return {
        "passed": bool(all(checks.values())),
        "checks": checks,
        "class_counts": class_counts,
        "test_temporal_coverage": {"distinct_dates": distinct_test_dates, "span_days": test_span_days},
        "thresholds": {
            "min_test_samples": settings.min_test_samples,
            "min_class_count": settings.min_class_count,
            "min_test_dates": settings.min_test_dates,
            "min_test_span_days": settings.min_test_span_days,
            "min_auc": settings.min_auc,
            "min_brier_skill": settings.min_brier_skill,
            "min_log_loss_skill": settings.min_log_loss_skill,
            "max_ece": settings.max_ece,
            "min_bootstrap_brier_skill_low": settings.min_bootstrap_brier_skill_low,
            "min_bootstrap_log_loss_skill_low": settings.min_bootstrap_log_loss_skill_low,
            "min_bootstrap_auc_low": settings.min_bootstrap_auc_low,
            "max_bootstrap_ece_high": settings.max_bootstrap_ece_high,
            "calibration_slope": [settings.min_calibration_slope, settings.max_calibration_slope],
            "min_positive_walk_forward_fraction": settings.min_positive_walk_forward_fraction,
        },
        "bootstrap": bootstrap,
    }


def dataset_validation_tier(dataset_manifest: Dict[str, Any], gates_passed: bool) -> str:
    if bool(dataset_manifest.get("synthetic")):
        return "fixture_only"
    if not gates_passed:
        return "rejected"
    quality = dataset_manifest.get("data_quality", {})
    required = [
        "point_in_time_features",
        "survivorship_control",
        "delistings_included",
        "corporate_action_adjusted",
    ]
    flags_ok = all(bool(quality.get(k)) for k in required)
    # `validated_market` requires not only affirmative flags but an evidence
    # record for each control. This cannot prove external truth, but it prevents
    # a bare set of booleans from being treated as sufficient governance.
    evidence = quality.get("evidence") or {}
    evidence_ok = all(bool(evidence.get(k)) for k in required)
    return "validated_market" if flags_ok and evidence_ok else "validated_research"


def train_validate_ensemble(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
    dataset_manifest: Dict[str, Any],
    settings: ForecastSettings,
) -> Tuple[EnsembleForecastModel, Dict[str, Any], pd.DataFrame]:
    settings.validate()
    features = list(feature_columns(train))
    if not features:
        raise ValueError("no numeric feature columns found")
    for part_name, part in [("train", train), ("validation", validation), ("test", test)]:
        if part["target_outperform"].nunique() < 2:
            raise ValueError(f"{part_name} partition must contain both target classes")
        missing = [c for c in features if c not in part]
        if missing:
            raise ValueError(f"{part_name} missing features: {missing}")

    # Three chronological validation stages with purge/embargo boundaries prevent reusing the
    # same validation observations to calibrate components, choose ensemble
    # weights, and then calibrate that ensemble. The test partition is untouched.
    val_cal, val_stack, val_final, val_protocol = _partition_validation(validation, settings)

    X_train = train[features].to_numpy(float)
    y_train = train["target_outperform"].to_numpy(int)
    y_test = test["target_outperform"].to_numpy(int)

    bayes = BayesianLogisticClassifier(settings.bayesian_prior_sigma, settings.random_seed).fit(X_train, y_train)
    models = _make_component_models(settings)
    for component in models.values():
        component.fit(X_train, y_train)

    # Stage 1: component calibration.
    X_cal = val_cal[features].to_numpy(float)
    y_cal = val_cal["target_outperform"].to_numpy(int)
    calibrators: Dict[str, ProbabilityCalibrator] = {}
    calibrators["bayesian_logistic"] = ProbabilityCalibrator(settings.calibration_method).fit(
        bayes.predict_proba(X_cal)[:, 1], y_cal
    )
    for name, component in models.items():
        calibrators[name] = ProbabilityCalibrator(settings.calibration_method).fit(
            component.predict_proba(X_cal)[:, 1], y_cal
        )

    # Stage 2: learn non-negative ensemble weights on a later validation window.
    X_stack = val_stack[features].to_numpy(float)
    y_stack = val_stack["target_outperform"].to_numpy(int)
    component_stack: Dict[str, np.ndarray] = {
        "bayesian_logistic": calibrators["bayesian_logistic"].transform(bayes.predict_proba(X_stack)[:, 1])
    }
    for name, component in models.items():
        component_stack[name] = calibrators[name].transform(component.predict_proba(X_stack)[:, 1])
    weights = _fit_weights(component_stack, y_stack)

    # Stage 3: final ensemble calibration on a still later validation window.
    X_final = val_final[features].to_numpy(float)
    y_final = val_final["target_outperform"].to_numpy(int)
    component_final: Dict[str, np.ndarray] = {
        "bayesian_logistic": calibrators["bayesian_logistic"].transform(bayes.predict_proba(X_final)[:, 1])
    }
    for name, component in models.items():
        component_final[name] = calibrators[name].transform(component.predict_proba(X_final)[:, 1])
    final_raw = sum(weights[name] * component_final[name] for name in weights)
    ensemble_cal = ProbabilityCalibrator(settings.calibration_method).fit(final_raw, y_final)

    model = EnsembleForecastModel(
        feature_names=features,
        settings=settings.to_dict(),
        bayes=bayes,
        component_models=models,
        component_calibrators=calibrators,
        ensemble_weights=weights,
        ensemble_calibrator=ensemble_cal,
        train_event_rate=float(y_train.mean()),
    )

    # Locked test: first use is here, after all fitting/calibration/weighting.
    p_test = model.predict_proba(test)
    dev_reference_rate = float(pd.concat([train[["target_outperform"]], validation[["target_outperform"]]], ignore_index=True)["target_outperform"].mean())
    test_metrics = evaluate_probabilities(y_test, p_test, reference_rate=dev_reference_rate)
    predictions = test[[c for c in ["date", "ticker", "target_end_date", "target_outperform", "forward_excess_return"] if c in test.columns]].copy()
    predictions["probability_outperform"] = p_test
    bootstrap = date_cluster_bootstrap(
        predictions,
        "probability_outperform",
        reference_rate=dev_reference_rate,
        draws=settings.bootstrap_draws,
        seed=settings.random_seed,
        level=settings.prediction_credible_level,
        block_dates=(settings.bootstrap_block_dates or max(1, int(np.ceil(settings.horizon_trading_days / settings.sample_step_trading_days)))),
    )
    dev = pd.concat([train, validation], ignore_index=True)
    walk = _walk_forward_baseline(dev, features, settings)
    gate = _validation_gate(test_metrics, bootstrap, walk, test, settings)
    tier = dataset_validation_tier(dataset_manifest, gate["passed"])
    report = {
        "validation_tier": tier,
        "gate": gate,
        "locked_test_metrics": test_metrics,
        "walk_forward": walk,
        "validation_protocol": {
            "method": "purged_embargoed_three_stage_validation_then_locked_test",
            "stages": val_protocol,
            "locked_test_used_for_fitting": False,
        },
        "ensemble_weights": weights,
        "features": features,
        "train_event_rate": float(y_train.mean()),
        "validation_event_rate": float(validation["target_outperform"].mean()),
        "test_event_rate": float(y_test.mean()),
        "validation_reference_event_rate": dev_reference_rate,
        "bayesian_coefficients_standardized": bayes.coefficient_summary(features),
        "interpretation": (
            "A validated_* tier means the configured probability model passed the locked-test gates for this dataset. "
            "validated_research still carries dataset limitations such as current-universe survivorship risk. "
            "validated_market additionally requires point-in-time features, survivorship controls, delistings, and corporate-action-adjusted prices."
        ),
    }
    return model, report, predictions
