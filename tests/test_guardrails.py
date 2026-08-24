from pathlib import Path

from services.guardrails import SQLiteRateLimiter, validate_ticker
from fastapi import HTTPException


def test_sqlite_rate_limit_is_shared_across_instances(tmp_path: Path):
    db = tmp_path / "rate.db"
    a = SQLiteRateLimiter(db)
    b = SQLiteRateLimiter(db)
    assert a.check("ip:analyze", 2, 60)[0] is True
    assert b.check("ip:analyze", 2, 60)[0] is True
    allowed, retry = a.check("ip:analyze", 2, 60)
    assert allowed is False
    assert retry >= 1


def test_ticker_validation():
    assert validate_ticker("brk-b") == "BRK-B"
    try:
        validate_ticker("AAPL<script>")
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("invalid ticker was accepted")


def test_default_audit_identity_is_not_raw_ip():
    from services.guardrails import _audit_client_id
    value = _audit_client_id("203.0.113.5")
    assert value != "203.0.113.5"
    assert value is None or len(value) == 16


def test_endpoint_grouping_keeps_refresh_status_polling_out_of_screener_budget():
    from services.guardrails import _endpoint_group
    assert _endpoint_group("/api/v1/screener/refresh") == "refresh"
    assert _endpoint_group("/api/v1/screener/status") == "status"
    assert _endpoint_group("/api/v1/export/screener.csv") == "export"
    assert _endpoint_group("/api/v1/screener") == "screener"


def test_cycle_pillar_has_no_calendar_cycle_dependency():
    """Cycle evidence must be causal/current-state evidence, never a calendar overlay."""
    import inspect
    import services.scoring as scoring

    sig = inspect.signature(scoring.score_cycle)
    assert list(sig.parameters) == ["fund", "macro", "commodity"]
    source = inspect.getsource(scoring.score_cycle).lower()
    forbidden = ["date.today", "datetime.now", "benner", "18.6", "lunar", "year %", "month %"]
    assert not any(token in source for token in forbidden)
