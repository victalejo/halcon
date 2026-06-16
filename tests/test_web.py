"""Tests for the Halcon web layer.

Pure-logic tests (event serialization, config isolation, path-safety) run with
no heavy dependencies. Integration tests that import the full app skip
automatically when ``rich`` / ``fastapi`` / ``httpx`` are unavailable.
"""

import os
import sys

import pytest

# Make the `web` package importable.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# --------------------------------- events ------------------------------------
from web import events  # noqa: E402  (path set above; events has no heavy deps)


def test_json_safe_passes_primitives():
    assert events.json_safe(1) == 1
    assert events.json_safe("x") == "x"
    assert events.json_safe(True) is True
    assert events.json_safe(None) is None


def test_json_safe_nested_and_fallback():
    class Weird:
        def __str__(self):
            return "weird"

    out = events.json_safe({"a": [1, {"b": Weird()}], "c": (1, 2)})
    assert out == {"a": [1, {"b": "weird"}], "c": [1, 2]}


def test_serialize_result_projects_fields():
    raw = {
        "name": "GitHub",
        "url": "https://github.com/x",
        "category": "coding",
        "status": "FOUND",
        "metadata": [{"name": "bio", "value": "hi"}],
        "extra": "dropped",
    }
    out = events.serialize_result(raw)
    assert out == {
        "name": "GitHub",
        "url": "https://github.com/x",
        "category": "coding",
        "metadata": [{"name": "bio", "value": "hi"}],
    }
    assert "status" not in out and "extra" not in out


def test_sse_framing():
    frame = events.sse({"type": "progress", "completed": 1, "total": 2})
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    assert '"type": "progress"' in frame


# ------------------------------ config factory -------------------------------
from web.config_factory import build_config, QuietConsole  # noqa: E402


def test_build_config_clamps_bounds():
    cfg = build_config(timeout=99999, max_concurrent_requests=99999)
    assert cfg.timeout == 120
    assert cfg.max_concurrent_requests == 100

    cfg2 = build_config(timeout=-5, max_concurrent_requests=0)
    assert cfg2.timeout == 1
    assert cfg2.max_concurrent_requests == 1


def test_build_config_is_isolated():
    a = build_config()
    b = build_config()
    a.currentUser = "alice"
    assert b.currentUser is None  # no shared global state

    # Inline-AI branch must stay disabled in the web layer.
    assert a.ai is False
    assert a.aiModel is None
    # Module constants are copied through.
    assert hasattr(a, "USERNAME_LIST_PATH")
    assert hasattr(a, "FONT_NAME_BOLD")


def test_quiet_console_swallows_everything():
    c = QuietConsole()
    # Any call shape must be a harmless no-op.
    assert c.print("hello", style="red") is None
    assert c.log("x") is None
    assert c.anything_at_all(1, 2, key=3) is None


# ------------------------------ export safety --------------------------------
from web.sanitize import safe_identifier  # noqa: E402  (dependency-free)


def test_safe_identifier_blocks_traversal():
    assert safe_identifier("../../etc/passwd") == "etc_passwd"
    assert "/" not in safe_identifier("a/b/c")
    assert ".." not in safe_identifier("..")
    assert safe_identifier("") == "result"
    assert safe_identifier("john.doe@example.com").startswith("john.doe@example.com")
    assert len(safe_identifier("x" * 500)) <= 100


# ------------------------------- integration ---------------------------------
@pytest.fixture
def client():
    pytest.importorskip("rich")
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from web.app import app

    # Plain instantiation does NOT trigger lifespan, so no network call here.
    return TestClient(app)


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "site_list_present" in body


def test_username_search_rejects_empty(client):
    assert client.get("/api/search/username?q=").status_code == 400
    assert client.get("/api/search/username?q=%20%20").status_code == 400


def test_email_search_requires_at(client):
    assert client.get("/api/search/email?q=notanemail").status_code == 400


def test_export_rejects_empty_results(client):
    res = client.post(
        "/api/export",
        json={"format": "csv", "kind": "username", "target": "x", "results": []},
    )
    assert res.status_code == 400


def test_export_rejects_bad_format(client):
    res = client.post(
        "/api/export",
        json={
            "format": "exe",
            "kind": "username",
            "target": "x",
            "results": [{"name": "a", "url": "b"}],
        },
    )
    assert res.status_code == 400
