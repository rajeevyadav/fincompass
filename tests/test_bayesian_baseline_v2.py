from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from forecasting.baseline import train_validate_bayesian_reference
from forecasting.config import get_profile
from forecasting.registry import save_model, load_model, set_active_model, registry_status


def _part(start, n, seed):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    latent = 0.20 * x1 - 0.10 * x2 + rng.normal(scale=1.2, size=n)
    y = (latent > 0).astype(int)
    return pd.DataFrame({
        'date': dates,
        'target_end_date': dates + pd.offsets.BDay(126),
        'target_outperform': y,
        'rel_ret_21': x1,
        'rel_ret_63': x2,
        'rel_ret_126': rng.normal(size=n),
        'rel_ret_252': rng.normal(size=n),
        'vol_63': np.abs(rng.normal(.25,.05,size=n)),
        'benchmark_vol_63': np.abs(rng.normal(.20,.04,size=n)),
        'drawdown_252': -np.abs(rng.normal(.12,.08,size=n)),
        'sma_50_200': rng.normal(0,.08,size=n),
    })


def test_hard_valid_weak_skill_becomes_baseline():
    train = _part('2000-01-03', 300, 1)
    val = _part('2002-01-03', 120, 2)
    test = _part('2003-01-03', 120, 3)
    model, report, pred = train_validate_bayesian_reference(
        train, val, test,
        {'synthetic': False, 'data_quality': {'point_in_time_features': True}},
        get_profile('exploratory'),
    )
    assert report['validation_tier'] == 'bayesian_baseline'
    assert report['hard_validity']['passed'] is True
    assert len(pred) == len(test)
    p = model.predict_proba(test)
    assert np.isfinite(p).all()
    assert ((p > 0) & (p < 1)).all()


def test_baseline_is_forecast_loadable_but_not_live_activatable(tmp_path: Path):
    train = _part('2000-01-03', 300, 4)
    val = _part('2002-01-03', 120, 5)
    test = _part('2003-01-03', 120, 6)
    model, report, _ = train_validate_bayesian_reference(
        train, val, test,
        {'synthetic': False, 'schema_version': 'x', 'target': {'benchmark': 'SPY'}, 'provenance': {'live_eligible_target': True}},
        get_profile('exploratory'),
    )
    saved = save_model(model, report, {'schema_version': 'x', 'target': {'benchmark': 'SPY'}, 'provenance': {'live_eligible_target': True}}, profile_name='baseline-test', root=tmp_path)
    loaded, manifest = load_model(model_id=saved['model_id'], minimum_tier='bayesian_baseline', root=tmp_path)
    assert loaded is not None
    assert manifest['validation_tier'] == 'bayesian_baseline'
    with pytest.raises(ValueError, match='validated_research or validated_market'):
        set_active_model(saved['model_id'], root=tmp_path)
    status = registry_status(root=tmp_path)
    assert status['bayesian_baseline_models'] == 1
    assert status['live_eligible_models'] == 0
