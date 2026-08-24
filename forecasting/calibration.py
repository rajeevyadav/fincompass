"""Separate-set probability calibration helpers."""
from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression


def _clip(p):
    return np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)


class ProbabilityCalibrator:
    def __init__(self, method: str = "sigmoid"):
        if method not in {"sigmoid", "isotonic"}:
            raise ValueError("method must be sigmoid or isotonic")
        self.method = method
        self.model = None

    def fit(self, raw_probability, y):
        p = _clip(raw_probability)
        y = np.asarray(y, dtype=int)
        if len(np.unique(y)) < 2:
            raise ValueError("calibration requires both classes")
        if self.method == "isotonic":
            self.model = IsotonicRegression(out_of_bounds="clip")
            self.model.fit(p, y)
        else:
            x = np.log(p / (1.0 - p)).reshape(-1, 1)
            self.model = LogisticRegression(C=1e4, solver="lbfgs", max_iter=1000)
            self.model.fit(x, y)
        return self

    def transform(self, raw_probability):
        if self.model is None:
            raise RuntimeError("calibrator is not fitted")
        p = _clip(raw_probability)
        if self.method == "isotonic":
            return _clip(self.model.predict(p))
        x = np.log(p / (1.0 - p)).reshape(-1, 1)
        return _clip(self.model.predict_proba(x)[:, 1])
