from __future__ import annotations

from web.backend.app import _resolve_secure_cookies


def test_secure_cookies_default_true_when_no_oauth_redirect(monkeypatch):
    monkeypatch.delenv("DASHBOARD_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("DISCORD_OAUTH_REDIRECT_URI", raising=False)

    assert _resolve_secure_cookies() is True


def test_secure_cookies_default_false_for_localhost_oauth_redirect(monkeypatch):
    monkeypatch.delenv("DASHBOARD_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("DISCORD_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/discord/callback")

    assert _resolve_secure_cookies() is False


def test_secure_cookies_default_false_for_loopback_oauth_redirect(monkeypatch):
    monkeypatch.delenv("DASHBOARD_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("DISCORD_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/auth/discord/callback")

    assert _resolve_secure_cookies() is False


def test_secure_cookies_env_override_has_priority(monkeypatch):
    monkeypatch.setenv("DASHBOARD_COOKIE_SECURE", "true")
    monkeypatch.setenv("DISCORD_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/discord/callback")

    assert _resolve_secure_cookies() is True
