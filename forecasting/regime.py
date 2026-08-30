"""Regime-aware Bayesian reference model for FinCompass v2.

A small Gaussian HMM estimates market-regime probabilities from benchmark-only,
backward-looking features. Those filtered regime probabilities augment the
regularized Bayesian logistic reference model. The HMM is fitted on training
information only; validation/test states are produced by forward filtering.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.special import logsumexp

from forecasting.bayesian import BayesianLogisticClassifier
from forecasting.calibration import ProbabilityCalibrator
from forecasting.config import ForecastSettings
from forecasting.metrics import date_cluster_bootstrap, evaluate_probabilities
from forecasting.baseline import _hard_validity, _reference_features

REGIME_INPUTS = ["benchmark_ret_1m", "benchmark_ret_6m", "benchmark_vol_6m"]


@dataclass
class GaussianHMMRegime:
    n_states: int = 3
    max_iter: int = 100
    tol: float = 1e-5
    random_seed: int = 37001
    means_: np.ndarray | None = None
    vars_: np.ndarray | None = None
    trans_: np.ndarray | None = None
    init_: np.ndarray | None = None
    medians_: np.ndarray | None = None
    state_order_: np.ndarray | None = None

    def _prepare_fit(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, float)
        self.medians_ = np.nanmedian(X, axis=0)
        self.medians_ = np.where(np.isfinite(self.medians_), self.medians_, 0.0)
        return np.where(np.isfinite(X), X, self.medians_)

    def _prepare(self, X: np.ndarray) -> np.ndarray:
        if self.medians_ is None:
            raise RuntimeError("HMM is not fitted")
        X = np.asarray(X, float)
        return np.where(np.isfinite(X), X, self.medians_)

    @staticmethod
    def _log_gaussian(X: np.ndarray, means: np.ndarray, vars_: np.ndarray) -> np.ndarray:
        v = np.clip(vars_, 1e-6, None)
        diff = X[:, None, :] - means[None, :, :]
        return -0.5 * (np.sum(np.log(2.0 * np.pi * v)[None, :, :] + diff * diff / v[None, :, :], axis=2))

    def _forward_backward(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        loge = self._log_gaussian(X, self.means_, self.vars_)
        logt = np.log(np.clip(self.trans_, 1e-12, 1.0))
        logi = np.log(np.clip(self.init_, 1e-12, 1.0))
        T, K = loge.shape
        la = np.empty((T, K)); lb = np.zeros((T, K))
        la[0] = logi + loge[0]
        for t in range(1, T):
            la[t] = loge[t] + logsumexp(la[t-1][:, None] + logt, axis=0)
        ll = float(logsumexp(la[-1]))
        for t in range(T-2, -1, -1):
            lb[t] = logsumexp(logt + loge[t+1][None, :] + lb[t+1][None, :], axis=1)
        gamma = np.exp(la + lb - ll)
        xi = np.empty((max(T-1, 0), K, K))
        for t in range(T-1):
            z = la[t][:, None] + logt + loge[t+1][None, :] + lb[t+1][None, :]
            xi[t] = np.exp(z - logsumexp(z))
        return gamma, xi, ll

    def fit(self, X: np.ndarray) -> "GaussianHMMRegime":
        X = self._prepare_fit(X)
        if len(X) < 36:
            raise ValueError("regime model requires at least 36 unique training dates")
        K = self.n_states
        # Deterministic initialization by benchmark one-month return quantiles.
        q = pd.qcut(pd.Series(X[:, 0]), q=K, labels=False, duplicates="drop").to_numpy()
        if len(np.unique(q)) < K:
            qs = np.quantile(X[:, 0], np.linspace(0, 1, K + 1))
            q = np.clip(np.searchsorted(qs[1:-1], X[:, 0]), 0, K-1)
        self.means_ = np.vstack([X[q == k].mean(axis=0) if np.any(q == k) else X.mean(axis=0) for k in range(K)])
        self.vars_ = np.vstack([X[q == k].var(axis=0) + 1e-4 if np.any(q == k) else X.var(axis=0) + 1e-4 for k in range(K)])
        self.trans_ = np.full((K, K), 0.05 / max(K-1, 1)); np.fill_diagonal(self.trans_, 0.95)
        self.init_ = np.full(K, 1.0 / K)
        prev = -np.inf
        for _ in range(self.max_iter):
            gamma, xi, ll = self._forward_backward(X)
            weights = gamma.sum(axis=0) + 1e-8
            self.init_ = np.clip(gamma[0], 1e-8, None); self.init_ /= self.init_.sum()
            if len(xi):
                self.trans_ = xi.sum(axis=0) + 1e-4
                self.trans_ /= self.trans_.sum(axis=1, keepdims=True)
            self.means_ = (gamma.T @ X) / weights[:, None]
            diff = X[:, None, :] - self.means_[None, :, :]
            self.vars_ = (gamma[:, :, None] * diff * diff).sum(axis=0) / weights[:, None]
            self.vars_ = np.clip(self.vars_, 1e-6, None)
            if np.isfinite(prev) and abs(ll - prev) < self.tol:
                break
            prev = ll
        # order states low -> high benchmark return for stable semantics
        self.state_order_ = np.argsort(self.means_[:, 0])
        return self

    def filtered_probabilities(self, X: np.ndarray, initial: np.ndarray | None = None) -> Tuple[np.ndarray, np.ndarray]:
        X = self._prepare(X)
        loge = self._log_gaussian(X, self.means_, self.vars_)
        probs = np.empty((len(X), self.n_states))
        prev = np.asarray(initial, float) if initial is not None else self.init_.copy()
        prev = np.clip(prev, 1e-12, None); prev /= prev.sum()
        for i in range(len(X)):
            pred = prev @ self.trans_
            post = pred * np.exp(loge[i] - np.max(loge[i]))
            post = np.clip(post, 1e-300, None); post /= post.sum()
            probs[i] = post
            prev = post
        ordered = probs[:, self.state_order_]
        return ordered, prev


@dataclass
class BayesianRegimeForecastModel:
    feature_names: List[str]
    settings: Dict[str, Any]
    bayes: BayesianLogisticClassifier
    calibrator: ProbabilityCalibrator
    hmm: GaussianHMMRegime
    base_feature_names: List[str]
    regime_inputs: List[str]
    train_event_rate: float
    evidence_tier: str = "bayesian_baseline"

    def _augment(self, frame: pd.DataFrame) -> np.ndarray:
        if not all(c in frame.columns for c in self.regime_inputs):
            raise ValueError("forecast input missing regime features")
        dates = pd.to_datetime(frame["date"]) if "date" in frame.columns else pd.RangeIndex(len(frame))
        tmp = frame.copy(); tmp["__date"] = dates
        by_date = tmp.groupby("__date", sort=True)[self.regime_inputs].first()
        rp, _ = self.hmm.filtered_probabilities(by_date.to_numpy(float))
        rpdf = pd.DataFrame(rp, index=by_date.index, columns=["regime_risk_off", "regime_neutral", "regime_risk_on"])
        merged = tmp[["__date", *self.base_feature_names]].join(rpdf, on="__date")
        return merged[self.feature_names].to_numpy(float)

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        raw = self.bayes.predict_proba(self._augment(frame))[:, 1]
        return self.calibrator.transform(raw)

    def predict_with_uncertainty(self, frame: pd.DataFrame) -> List[Dict[str, Any]]:
        X = self._augment(frame)
        settings = ForecastSettings(**self.settings).validate()
        mean, lo, hi = self.bayes.posterior_probability_interval(X, draws=settings.posterior_draws, level=settings.prediction_credible_level)
        point = self.calibrator.transform(mean); lo = self.calibrator.transform(lo); hi = self.calibrator.transform(hi)
        return [{
            "probability_outperform": float(point[i]),
            "uncertainty_interval": [float(min(lo[i], hi[i])), float(max(lo[i], hi[i]))],
            "uncertainty_level": settings.prediction_credible_level,
            "component_probabilities": {"bayesian_regime": float(point[i])},
            "abstain": bool(min(lo[i], hi[i]) <= 0.5 <= max(lo[i], hi[i]) or abs(float(point[i])-0.5) <= settings.abstain_probability_band),
            "interpretation": "Regime probabilities are inferred from benchmark-only backward-looking features and propagated through a calibrated Bayesian reference model.",
        } for i in range(len(frame))]


def _unique_market_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if "date" not in frame.columns:
        raise ValueError("regime-aware model requires a date column")
    cols = ["date", *REGIME_INPUTS]
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise ValueError(f"regime-aware model missing inputs: {missing}")
    return frame[cols].sort_values("date").groupby("date", as_index=False).first()


def _regime_features(hmm: GaussianHMMRegime, frame: pd.DataFrame) -> pd.DataFrame:
    market = _unique_market_rows(frame)
    probs, _ = hmm.filtered_probabilities(market[REGIME_INPUTS].to_numpy(float))
    rp = pd.DataFrame(probs, columns=["regime_risk_off", "regime_neutral", "regime_risk_on"])
    rp["date"] = pd.to_datetime(market["date"]).to_numpy()
    out = frame.copy(); out["date"] = pd.to_datetime(out["date"])
    return out.merge(rp, on="date", how="left", validate="many_to_one")


def train_validate_bayesian_regime(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
    dataset_manifest: Dict[str, Any],
    settings: ForecastSettings,
) -> Tuple[BayesianRegimeForecastModel, Dict[str, Any], pd.DataFrame]:
    settings.validate()
    base = _reference_features(train)
    hard = _hard_validity(train, validation, test, base)
    if not hard["passed"]:
        failed = [k for k,v in hard["checks"].items() if not v]
        raise ValueError("Bayesian regime hard-validity failure: " + ", ".join(failed))
    market_train = _unique_market_rows(train)
    hmm = GaussianHMMRegime(random_seed=settings.random_seed).fit(market_train[REGIME_INPUTS].to_numpy(float))
    tr = _regime_features(hmm, train); va = _regime_features(hmm, validation); te = _regime_features(hmm, test)
    regime_cols = ["regime_risk_off", "regime_neutral", "regime_risk_on"]
    features = [*base, *regime_cols]
    bayes = BayesianLogisticClassifier(settings.bayesian_prior_sigma, settings.random_seed).fit(tr[features].to_numpy(float), tr["target_outperform"].to_numpy(int))
    raw_val = bayes.predict_proba(va[features].to_numpy(float))[:, 1]
    calibrator = ProbabilityCalibrator(settings.calibration_method).fit(raw_val, va["target_outperform"].to_numpy(int))
    model = BayesianRegimeForecastModel(features, settings.to_dict(), bayes, calibrator, hmm, base, REGIME_INPUTS, float(tr["target_outperform"].mean()))
    p = model.predict_proba(te)
    dev_rate = float(pd.concat([train[["target_outperform"]], validation[["target_outperform"]]])["target_outperform"].mean())
    metrics = evaluate_probabilities(te["target_outperform"].to_numpy(int), p, reference_rate=dev_rate)
    predictions = te[[c for c in ["date","ticker","target_end_date","target_outperform","forward_excess_return"] if c in te.columns]].copy()
    predictions["probability_outperform"] = p
    bootstrap = date_cluster_bootstrap(predictions, "probability_outperform", reference_rate=dev_rate, draws=min(max(100,settings.bootstrap_draws),300), seed=settings.random_seed, level=settings.prediction_credible_level, block_dates=(settings.bootstrap_block_dates or max(1,int(np.ceil(settings.horizon_trading_days/settings.sample_step_trading_days)))))
    ordered_means = hmm.means_[hmm.state_order_]
    report = {
        "validation_tier": "bayesian_baseline",
        "model_family": "bayesian_regime_hmm",
        "hard_validity": hard,
        "locked_test_metrics": metrics,
        "bootstrap": bootstrap,
        "features": features,
        "regime_model": {"states": 3, "inputs": REGIME_INPUTS, "ordered_state_means": ordered_means.tolist(), "semantics": ["risk_off","neutral","risk_on"]},
        "calibration": {"method": settings.calibration_method, "rows": int(len(validation))},
        "gate": {"passed": False, "checks": {}, "meaning": "Regime-aware reference remains Limited evidence unless the separate strong research-validation path passes."},
        "interpretation": "Regime-aware Bayesian reference; hard-valid probability model with no automatic claim of predictive alpha.",
        "dataset_quality": dataset_manifest.get("data_quality") or {},
    }
    return model, report, predictions
