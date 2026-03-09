from __future__ import annotations

import pathlib
import sys

from fastapi import Request

repo_root = pathlib.Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))
sys.path.append(str(repo_root / "src"))

from web.backend.app import _resolve_cookie_samesite, _resolve_secure_cookies
from web.backend.app import _is_https_request, _resolve_cookie_policy_for_request


def _request(scope_overrides: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "scheme": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    if scope_overrides:
        scope.update(scope_overrides)
    return Request(scope)


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


def test_cookie_samesite_default_none_when_no_local_redirect(monkeypatch):
    monkeypatch.delenv("DASHBOARD_COOKIE_SAMESITE", raising=False)
    monkeypatch.delenv("DISCORD_OAUTH_REDIRECT_URI", raising=False)

    assert _resolve_cookie_samesite() == "none"


def test_cookie_samesite_default_lax_for_localhost(monkeypatch):
    monkeypatch.delenv("DASHBOARD_COOKIE_SAMESITE", raising=False)
    monkeypatch.setenv("DISCORD_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/discord/callback")

    assert _resolve_cookie_samesite() == "lax"


def test_cookie_samesite_env_override(monkeypatch):
    monkeypatch.setenv("DASHBOARD_COOKIE_SAMESITE", "strict")
    monkeypatch.setenv("DISCORD_OAUTH_REDIRECT_URI", "https://backend.example.com/auth/discord/callback")

    assert _resolve_cookie_samesite() == "strict"


def test_is_https_request_reads_forwarded_proto_header():
    request = _request({"headers": [(b"x-forwarded-proto", b"https")]})

    assert _is_https_request(request) is True


def test_cookie_policy_auto_downgrades_none_to_lax_when_http(monkeypatch):
    monkeypatch.delenv("DASHBOARD_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("DASHBOARD_COOKIE_SAMESITE", raising=False)

    secure, same_site = _resolve_cookie_policy_for_request(
        _request(),
        default_secure=True,
        default_samesite="none",
    )

    assert secure is False
    assert same_site == "lax"


def test_cookie_policy_keeps_none_for_https_request(monkeypatch):
    monkeypatch.delenv("DASHBOARD_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("DASHBOARD_COOKIE_SAMESITE", raising=False)

    secure, same_site = _resolve_cookie_policy_for_request(
        _request({"scheme": "https"}),
        default_secure=True,
        default_samesite="none",
    )

    assert secure is True
    assert same_site == "none"
