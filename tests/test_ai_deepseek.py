"""Tests for the DeepSeek AI profiling backend and its wiring in the web layer."""

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO_ROOT, os.path.join(REPO_ROOT, "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

from modules.ai import deepseek  # noqa: E402  (path set above)

SITES = ["GitHub (User)", "GitLab", "Dev.to", "Twitch"]


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def chat_body(content):
    return {"choices": [{"message": {"content": content}}]}


def fake_post(response, calls):
    def _post(url, headers=None, json=None, timeout=None, allow_redirects=True):
        calls.append({
            "url": url, "headers": headers, "json": json,
            "timeout": timeout, "allow_redirects": allow_redirects,
        })
        return response

    return _post


def test_analyze_sites_sends_only_site_names_and_parses_result():
    content = json.dumps({
        "summary": "Perfil técnico.",
        "categorization": "Desarrollador",
        "insights": ["Activo en repositorios de código"],
        "risk_flags": [],
        "tags": ["tech", "gaming"],
    })
    calls = []
    result = deepseek.analyze_sites(
        SITES, api_key="sk-test", post=fake_post(FakeResponse(body=chat_body(content)), calls)
    )

    assert result == {
        "summary": "Perfil técnico.",
        "categorization": "Desarrollador",
        "insights": ["Activo en repositorios de código"],
        "risk_flags": [],
        "tags": ["tech", "gaming"],
    }
    call = calls[0]
    assert call["url"] == "https://api.deepseek.com/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["json"]["model"] == "deepseek-chat"
    assert call["json"]["response_format"] == {"type": "json_object"}
    assert call["timeout"] == deepseek.DEFAULT_TIMEOUT
    assert call["allow_redirects"] is False
    user_message = call["json"]["messages"][-1]["content"]
    assert json.loads(user_message.split("\n", 1)[1]) == SITES


def test_analyze_sites_sanitizes_and_caps_site_names():
    calls = []
    noisy = ["  Git\nHub\x00 ", "", "x" * 500] + [f"s{i}" for i in range(deepseek.MAX_SITES + 50)]
    deepseek.analyze_sites(
        noisy, api_key="k",
        post=fake_post(FakeResponse(body=chat_body(json.dumps({"summary": "x"}))), calls),
    )
    sent = json.loads(calls[0]["json"]["messages"][-1]["content"].split("\n", 1)[1])
    assert sent[0] == "Git Hub"
    assert sent[1] == "x" * deepseek.MAX_SITE_NAME_LENGTH
    assert len(sent) == deepseek.MAX_SITES


def test_analyze_sites_honours_base_url_and_model():
    calls = []
    content = json.dumps({"summary": "x"})
    deepseek.analyze_sites(
        SITES,
        api_key="k",
        base_url="https://proxy.example/v1/",
        model="deepseek-reasoner",
        post=fake_post(FakeResponse(body=chat_body(content)), calls),
    )
    assert calls[0]["url"] == "https://proxy.example/v1/chat/completions"
    assert calls[0]["json"]["model"] == "deepseek-reasoner"


def test_analyze_sites_normalizes_missing_and_malformed_fields():
    content = json.dumps({
        "summary": "  Resumen  ",
        "insights": "uno solo",
        "risk_flags": None,
        "tags": ["ok", 3, "", "  b  "],
    })
    result = deepseek.analyze_sites(
        SITES, api_key="k", post=fake_post(FakeResponse(body=chat_body(content)), [])
    )
    assert result == {
        "summary": "Resumen",
        "categorization": "",
        "insights": ["uno solo"],
        "risk_flags": [],
        "tags": ["ok", "b"],
    }


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status_code=401, body={"error": {"message": "bad key"}}),
        FakeResponse(status_code=500, text="boom"),
        FakeResponse(body={"choices": []}),
        FakeResponse(body=chat_body("esto no es json")),
        FakeResponse(body=chat_body(json.dumps({"summary": ""}))),
        FakeResponse(body=None),
    ],
)
def test_analyze_sites_raises_on_bad_responses(response):
    with pytest.raises(deepseek.DeepSeekError) as exc:
        deepseek.analyze_sites(SITES, api_key="sk-secret", post=fake_post(response, []))
    assert "sk-secret" not in str(exc.value)


def test_analyze_sites_wraps_network_errors():
    def _post(*args, **kwargs):
        raise deepseek.requests.ConnectionError("down")

    with pytest.raises(deepseek.DeepSeekError):
        deepseek.analyze_sites(SITES, api_key="k", post=_post)


# ------------------------------ web wiring -----------------------------------
@pytest.fixture
def ai_service():
    pytest.importorskip("rich")
    pytest.importorskip("fastapi")
    # Load the app first, as production does: the legacy core puts its
    # `utils` package on sys.path as a side effect of importing the scanners.
    import web.app  # noqa: F401
    from web import ai_service as module

    return module


def make_config(**overrides):
    class Cfg:
        pass

    cfg = Cfg()
    cfg.api_url = None
    cfg.deepseek_api_key = None
    cfg.deepseek_base_url = None
    cfg.deepseek_model = None
    cfg.verbose = False
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_service_uses_deepseek_when_key_configured(ai_service, monkeypatch):
    seen = {}

    def fake_analyze(site_names, **kwargs):
        seen["sites"] = site_names
        seen["kwargs"] = kwargs
        return {"summary": "s", "categorization": "c", "insights": [], "risk_flags": [], "tags": []}

    monkeypatch.setattr(ai_service.deepseek, "analyze_sites", fake_analyze)
    cfg = make_config(deepseek_api_key="sk-x", deepseek_model="deepseek-chat")
    out = ai_service._analyze_sync(SITES, cfg)

    assert out["available"] is True and out["ok"] is True
    assert out["result"]["summary"] == "s"
    assert seen["sites"] == SITES
    assert seen["kwargs"]["api_key"] == "sk-x"
    assert seen["kwargs"]["model"] == "deepseek-chat"


def test_service_reports_deepseek_failure_without_leaking_key(ai_service, monkeypatch):
    def failing(site_names, **kwargs):
        raise ai_service.deepseek.DeepSeekError("DeepSeek respondió 401")

    monkeypatch.setattr(ai_service.deepseek, "analyze_sites", failing)
    out = ai_service._analyze_sync(SITES, make_config(deepseek_api_key="sk-x"))

    assert out["available"] is True and out["ok"] is False
    assert "sk-x" not in json.dumps(out)


def test_service_unavailable_without_any_backend(ai_service, monkeypatch):
    monkeypatch.setattr(ai_service, "load_api_key_from_file", lambda cfg: None)
    out = ai_service._analyze_sync(SITES, make_config())
    assert out["available"] is False


def test_build_config_reads_deepseek_env(monkeypatch):
    pytest.importorskip("rich")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-reasoner")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    from web.config_factory import build_config

    cfg = build_config()
    assert cfg.deepseek_api_key == "sk-env"
    assert cfg.deepseek_model == "deepseek-reasoner"
    assert cfg.deepseek_base_url is None
