"""Lightweight Bayesian logistic regression via Laplace approximation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
from scipy.optimize import minimize


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class BayesianLogisticClassifier:
    prior_sigma: float = 1.5
    random_seed: int = 37001

    medians_: Optional[np.ndarray] = None
    means_: Optional[np.ndarray] = None
    scales_: Optional[np.ndarray] = None
    coef_: Optional[np.ndarray] = None
    covariance_: Optional[np.ndarray] = None

    def _prep_fit(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        self.medians_ = np.nanmedian(X, axis=0)
        self.medians_ = np.where(np.isfinite(self.medians_), self.medians_, 0.0)
        X = np.where(np.isfinite(X), X, self.medians_)
        self.means_ = X.mean(axis=0)
        self.scales_ = X.std(axis=0)
        self.scales_ = np.where(self.scales_ > 1e-9, self.scales_, 1.0)
        return (X - self.means_) / self.scales_

    def _prep(self, X: np.ndarray) -> np.ndarray:
        if self.medians_ is None or self.means_ is None or self.scales_ is None:
            raise RuntimeError("model is not fitted")
        X = np.asarray(X, dtype=float)
        X = np.where(np.isfinite(X), X, self.medians_)
        return (X - self.means_) / self.scales_

    def fit(self, X: np.ndarray, y: np.ndarray) -> "BayesianLogisticClassifier":
        Xs = self._prep_fit(X)
        y = np.asarray(y, dtype=float).reshape(-1)
        if len(np.unique(y)) < 2:
            raise ValueError("Bayesian logistic regression requires both target classes")
        Xa = np.column_stack([np.ones(len(Xs)), Xs])
        prior_prec = np.full(Xa.shape[1], 1.0 / (self.prior_sigma ** 2), dtype=float)
        prior_prec[0] = 1.0 / (5.0 ** 2)

        def nlp(beta: np.ndarray) -> float:
            z = Xa @ beta
            likelihood = np.sum(np.logaddexp(0.0, z) - y * z)
            prior = 0.5 * np.sum(prior_prec * beta * beta)
            return float(likelihood + prior)

        def grad(beta: np.ndarray) -> np.ndarray:
            p = _sigmoid(Xa @ beta)
            return Xa.T @ (p - y) + prior_prec * beta

        result = minimize(nlp, np.zeros(Xa.shape[1]), jac=grad, method="L-BFGS-B", options={"maxiter": 800, "ftol": 1e-10})
        if not result.success:
            raise RuntimeError(f"Bayesian logistic optimization failed: {result.message}")
        beta = np.asarray(result.x, dtype=float)
        p = _sigmoid(Xa @ beta)
        w = np.clip(p * (1.0 - p), 1e-8, None)
        hessian = Xa.T @ (Xa * w[:, None]) + np.diag(prior_prec)
        covariance = np.linalg.pinv(hessian)
        covariance = (covariance + covariance.T) / 2.0
        self.coef_ = beta
        self.covariance_ = covariance
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        Xs = self._prep(X)
        Xa = np.column_stack([np.ones(len(Xs)), Xs])
        p = _sigmoid(Xa @ self.coef_)
        return np.column_stack([1.0 - p, p])

    def posterior_probability_interval(self, X: np.ndarray, draws: int = 1200, level: float = 0.90) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.coef_ is None or self.covariance_ is None:
            raise RuntimeError("model is not fitted")
        Xs = self._prep(X)
        Xa = np.column_stack([np.ones(len(Xs)), Xs])
        rng = np.random.default_rng(self.random_seed)
        beta_draws = rng.multivariate_normal(self.coef_, self.covariance_, size=int(draws), check_valid="ignore")
        probs = _sigmoid(Xa @ beta_draws.T)
        tail = (1.0 - float(level)) / 2.0
        lo = np.quantile(probs, tail, axis=1)
        hi = np.quantile(probs, 1.0 - tail, axis=1)
        mean = probs.mean(axis=1)
        return mean, lo, hi

    def coefficient_summary(self, feature_names) -> Dict[str, float]:
        if self.coef_ is None:
            return {}
        return {name: float(value) for name, value in zip(["intercept", *feature_names], self.coef_)}
