from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from hashlib import sha256
import json
from typing import Any, Dict

from realtime import REALTIME_ENGINE_VERSION


@dataclass(frozen=True)
class RealtimeSettings:
    market_refresh_seconds: int = 60
    sec_refresh_seconds: int = 600
    macro_refresh_seconds: int = 900
    max_market_staleness_seconds: int = 900
    max_sec_staleness_seconds: int = 86400
    max_macro_staleness_seconds: int = 86400
    event_half_life_hours: float = 36.0
    retention_days: int = 120
    snapshot_min_spacing_seconds: int = 300
    pending_label_limit: int = 20000

    adaptive_prior_sigma: float = 0.75
    forgetting_factor: float = 0.997
    process_noise: float = 0.0005
    adaptive_max_logit_shift: float = 0.75
    probability_clip: float = 0.01

    min_matured_observations: int = 120
    min_unique_observation_dates: int = 60
    min_observation_span_days: int = 180
    online_eval_window: int = 250
    max_brier_regret: float = 0.0
    max_log_loss_regret: float = 0.0
    max_ece: float = 0.08

    drift_allowance: float = 0.001
    drift_alpha: float = 0.08
    drift_control_multiplier: float = 2.75
    drift_min_samples: int = 60

    enable_adaptive_application: bool = True
    enable_online_learning: bool = True

    def validate(self) -> "RealtimeSettings":
        positive_ints = [
            "market_refresh_seconds", "sec_refresh_seconds", "macro_refresh_seconds",
            "max_market_staleness_seconds", "max_sec_staleness_seconds", "max_macro_staleness_seconds",
            "retention_days", "snapshot_min_spacing_seconds", "pending_label_limit",
            "min_matured_observations", "min_unique_observation_dates", "min_observation_span_days",
            "online_eval_window", "drift_min_samples",
        ]
        for name in positive_ints:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not 1.0 <= self.event_half_life_hours <= 24 * 365:
            raise ValueError("event_half_life_hours must be in [1, 8760]")
        if not 0.05 <= self.adaptive_prior_sigma <= 10:
            raise ValueError("adaptive_prior_sigma must be in [0.05, 10]")
        if not 0.90 <= self.forgetting_factor <= 1.0:
            raise ValueError("forgetting_factor must be in [0.90, 1.0]")
        if not 0.0 <= self.process_noise <= 0.1:
            raise ValueError("process_noise must be in [0, 0.1]")
        if not 0.0 < self.adaptive_max_logit_shift <= 3.0:
            raise ValueError("adaptive_max_logit_shift must be in (0, 3]")
        if not 0.0001 <= self.probability_clip <= 0.10:
            raise ValueError("probability_clip must be in [0.0001, 0.10]")
        if self.online_eval_window < self.min_unique_observation_dates:
            raise ValueError("online_eval_window cannot be smaller than min_unique_observation_dates")
        if not -0.10 <= self.max_brier_regret <= 0.10:
            raise ValueError("max_brier_regret must be in [-0.10, 0.10]")
        if not -0.50 <= self.max_log_loss_regret <= 0.50:
            raise ValueError("max_log_loss_regret must be in [-0.50, 0.50]")
        if not 0.0 < self.max_ece <= 0.25:
            raise ValueError("max_ece must be in (0, 0.25]")
        if not 0.0 <= self.drift_allowance <= 0.10:
            raise ValueError("drift_allowance must be in [0, 0.10]")
        if not 0.001 <= self.drift_alpha <= 1.0:
            raise ValueError("drift_alpha must be in [0.001, 1]")
        if not 0.5 <= self.drift_control_multiplier <= 10:
            raise ValueError("drift_control_multiplier must be in [0.5, 10]")
        if type(self.enable_adaptive_application) is not bool or type(self.enable_online_learning) is not bool:
            raise ValueError("adaptive switches must be booleans")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return sha256(raw.encode("utf-8")).hexdigest()[:16]


BALANCED = RealtimeSettings()
RESPONSIVE = replace(
    BALANCED,
    market_refresh_seconds=30,
    sec_refresh_seconds=300,
    macro_refresh_seconds=600,
    event_half_life_hours=18.0,
    adaptive_prior_sigma=0.9,
    forgetting_factor=0.992,
    process_noise=0.001,
    min_matured_observations=100,
    min_unique_observation_dates=50,
    min_observation_span_days=150,
    adaptive_max_logit_shift=0.9,
)
CONSERVATIVE = replace(
    BALANCED,
    market_refresh_seconds=120,
    sec_refresh_seconds=900,
    macro_refresh_seconds=1800,
    event_half_life_hours=72.0,
    adaptive_prior_sigma=0.6,
    forgetting_factor=0.999,
    process_noise=0.0002,
    min_matured_observations=180,
    min_unique_observation_dates=90,
    min_observation_span_days=270,
    adaptive_max_logit_shift=0.55,
    max_ece=0.06,
)
PROFILES = {"balanced": BALANCED, "responsive": RESPONSIVE, "conservative": CONSERVATIVE}


def settings_from_dict(payload: Dict[str, Any] | None, base: str = "balanced") -> RealtimeSettings:
    if base not in PROFILES:
        raise ValueError(f"Unknown realtime profile: {base}")
    payload = dict(payload or {})
    known = {f.name for f in fields(RealtimeSettings)}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise ValueError("Unknown realtime setting(s): " + ", ".join(unknown))
    obj = replace(PROFILES[base], **payload)
    return obj.validate()


def settings_schema() -> Dict[str, Any]:
    return {
        "engine_version": REALTIME_ENGINE_VERSION,
        "profiles": {name: cfg.to_dict() for name, cfg in PROFILES.items()},
        "fields": {f.name: str(f.type) for f in fields(RealtimeSettings)},
        "lineage_rule": "The complete validated settings object is fingerprinted into adaptive state and pending-label identity.",
    }
