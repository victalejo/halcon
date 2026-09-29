"""Unit tests for web.security (no FastAPI app import required)."""

import base64
import os
import sys
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from web.security import (  # noqa: E402
    RateLimiter,
    SecurityConfig,
    authenticate,
    extract_api_key,
    is_public_path,
    reset_rate_limiter,
)


def test_is_public_path():
    assert is_public_path("/") is True
    assert is_public_path("/api/health") is True
    assert is_public_path("/static/app.js") is True
    assert is_public_path("/static/img/x.png") is True
    assert is_public_path("/api/search/username") is False
    assert is_public_path("/api/export") is False


def test_security_config_from_env_open_by_default(monkeypatch):
    monkeypatch.delenv("HALCON_API_KEY", raising=False)
    monkeypatch.delenv("HALCON_BASIC_USER", raising=False)
    monkeypatch.delenv("HALCON_BASIC_PASSWORD", raising=False)
    monkeypatch.delenv("HALCON_RATE_LIMIT", raising=False)
    cfg = SecurityConfig.from_env()
    assert cfg.auth_required is False
    assert cfg.auth_modes == []
    assert cfg.rate_limit == 60
    assert cfg.rate_limit_enabled is True


def test_security_config_api_key_and_basic(monkeypatch):
    monkeypatch.setenv("HALCON_API_KEY", "s3cret")
    monkeypatch.setenv("HALCON_BASIC_USER", "admin")
    monkeypatch.setenv("HALCON_BASIC_PASSWORD", "pass")
    monkeypatch.setenv("HALCON_RATE_LIMIT", "0")
    cfg = SecurityConfig.from_env()
    assert cfg.auth_required is True
    assert set(cfg.auth_modes) == {"api_key", "basic"}
    assert cfg.rate_limit_enabled is False


def test_security_config_basic_incomplete(monkeypatch):
    monkeypatch.delenv("HALCON_API_KEY", raising=False)
    monkeypatch.setenv("HALCON_BASIC_USER", "admin")
    monkeypatch.delenv("HALCON_BASIC_PASSWORD", raising=False)
    cfg = SecurityConfig.from_env()
    assert cfg.auth_required is False


def test_rate_limiter_blocks_after_limit():
    lim = RateLimiter(limit=2, window=60)
    assert lim.allow("1.1.1.1") is True
    assert lim.allow("1.1.1.1") is True
    assert lim.allow("1.1.1.1") is False
    # Different client is independent.
    assert lim.allow("2.2.2.2") is True
    assert lim.remaining("1.1.1.1") == 0
    assert lim.remaining("2.2.2.2") == 1


def test_rate_limiter_window_expiry():
    lim = RateLimiter(limit=1, window=1)
    assert lim.allow("ip") is True
    assert lim.allow("ip") is False
    # Force expiry by rewriting timestamps.
    with lim._lock:
        lim._hits["ip"].clear()
        lim._hits["ip"].append(__import__("time").monotonic() - 2)
    assert lim.allow("ip") is True


class _FakeRequest:
    def __init__(self, headers=None, query=None, client_host="127.0.0.1"):
        self.headers = headers or {}
        self.query_params = query or {}
        self.client = SimpleNamespace(host=client_host) if client_host else None


def test_extract_api_key_sources():
    assert extract_api_key(_FakeRequest(headers={"x-api-key": "a"})) == "a"
    assert (
        extract_api_key(_FakeRequest(headers={"authorization": "Bearer tok"})) == "tok"
    )
    assert extract_api_key(_FakeRequest(query={"api_key": "q"})) == "q"
    assert extract_api_key(_FakeRequest()) is None


def test_authenticate_api_key():
    cfg = SecurityConfig(api_key="good")
    assert authenticate(_FakeRequest(headers={"x-api-key": "good"}), cfg) is True
    assert authenticate(_FakeRequest(headers={"x-api-key": "bad"}), cfg) is False
    assert authenticate(_FakeRequest(query={"api_key": "good"}), cfg) is True
    assert (
        authenticate(_FakeRequest(headers={"authorization": "Bearer good"}), cfg)
        is True
    )


def test_authenticate_basic():
    cfg = SecurityConfig(basic_user="u", basic_password="p")
    token = base64.b64encode(b"u:p").decode()
    ok = _FakeRequest(headers={"authorization": f"Basic {token}"})
    bad = _FakeRequest(
        headers={"authorization": "Basic " + base64.b64encode(b"u:wrong").decode()}
    )
    assert authenticate(ok, cfg) is True
    assert authenticate(bad, cfg) is False
    assert authenticate(_FakeRequest(), cfg) is False


def test_authenticate_open_when_not_configured():
    cfg = SecurityConfig()
    assert authenticate(_FakeRequest(), cfg) is True


def test_reset_rate_limiter_clears_state():
    reset_rate_limiter()
