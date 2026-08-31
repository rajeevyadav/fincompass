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
