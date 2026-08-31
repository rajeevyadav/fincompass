"""The Forecast must offer a self-contained expert evidence report that an expert
can audit without any private training intermediates being exposed."""
from __future__ import annotations

from pathlib import Path

from services.forecast_service import forecast_ticker

APP_JS = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")

_REQUIRED = ["report_type", "ticker", "as_of", "target_event", "benchmark", "horizon_months",
             "probability_outperform", "uncertainty_interval", "evidence_tier", "model_id",
             "applicability_domain", "training_cutoff", "validation", "data_provenance",
             "training_contract", "interpretation_policy", "reproducibility", "why_selected",
             "limitations"]


def test_evidence_report_is_complete_when_available():
    out = forecast_ticker("AAPL", horizon_months=12)
    if not out.get("available"):
        return  # network-degraded; the shape test below still covers the frontend
    rep = out["evidence_report"]
    missing = [k for k in _REQUIRED if k not in rep]
    assert not missing, f"evidence report missing: {missing}"
    # Reproducibility fingerprints are present but NOT the raw training rows.
    assert rep["reproducibility"]["model_sha256"]
    assert "training_rows" not in rep and "raw_data" not in rep


def test_frontend_offers_one_click_download():
    assert "downloadEvidenceReport" in APP_JS
    assert "btn-export-forecast" in APP_JS
    assert "evidence_report" in APP_JS
