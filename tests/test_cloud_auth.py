"""Hosted-edition cloud auth. Hosting mode is read live from the environment, so
the desktop edition (no env set) is unaffected and tests never leak state."""
import services.cloud_auth as cloud_auth


def test_default_is_not_hosted():
    # With no env set, the desktop edition sees hosting off and no auth gate.
    assert cloud_auth.hosted_mode() is False
    assert cloud_auth.auth_mode() == "off"


def test_hosted_config_has_no_private_user_store(monkeypatch):
    monkeypatch.setenv("FINCOMPASS_HOSTED_MODE", "1")
    monkeypatch.setenv("FINCOMPASS_AUTH_MODE", "required")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "example")
    monkeypatch.setenv("FIREBASE_API_KEY", "public-web-key")
    cfg = cloud_auth.cloud_config_payload()
    assert cfg["hosted"] is True
    assert cfg["auth_mode"] == "required"
    assert cfg["privacy"]["server_side_research_profile"] is False
    assert "password" not in str(cfg).lower()


def test_env_toggle_does_not_persist(monkeypatch):
    # After a hosted-mode test, the flag must be off again (live env read).
    assert cloud_auth.hosted_mode() is False


def test_hosted_csp_frame_ancestors(monkeypatch):
    # Cloud Run stays strict by default; an embedder (e.g. a Hugging Face Space)
    # can open framing, and bare keywords are quoted automatically.
    import importlib
    monkeypatch.setenv("FINCOMPASS_HOSTED_MODE", "1")
    import config
    importlib.reload(config)
    import services.guardrails as g
    importlib.reload(g)
    try:
        assert "frame-ancestors 'none'" in g._csp_for("/")
        monkeypatch.setenv("FINCOMPASS_FRAME_ANCESTORS", "self https://huggingface.co https://*.hf.space")
        csp = g._csp_for("/")
        assert "frame-ancestors 'self' https://huggingface.co https://*.hf.space" in csp
    finally:
        monkeypatch.delenv("FINCOMPASS_HOSTED_MODE", raising=False)
        monkeypatch.delenv("FINCOMPASS_FRAME_ANCESTORS", raising=False)
        importlib.reload(config)
        importlib.reload(g)
