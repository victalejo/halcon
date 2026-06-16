"""Per-request configuration objects for the web layer.

The CLI passes a single mutated ``config`` module everywhere. That global
singleton is unsafe for a concurrent web server, so we build a fresh, isolated
config object per request that exposes exactly the attributes the core engine
reads. Module-level constants (paths, font names) are copied from ``config.py``;
runtime fields are set explicitly.
"""

from __future__ import annotations

import os
from datetime import datetime

import config as _base_config  # src/config.py (on sys.path via web/__init__.py)
from modules.utils.userAgent import getRandomUserAgent

# Sensible bounds so a web client cannot ask the server to do something abusive.
MIN_TIMEOUT = 1
MAX_TIMEOUT = 120
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 100

DEFAULT_TIMEOUT = 30
DEFAULT_CONCURRENCY = 30


class QuietConsole:
    """No-op stand-in for ``rich.Console``.

    The CLI core prints progress/results to ``config.console``. The web layer
    derives everything from structured return values instead, so every console
    call is swallowed. Implemented permissively to accept any ``rich`` call
    shape (``print``, ``log``, ``rule`` with arbitrary args/kwargs).
    """

    def __getattr__(self, _name):  # any attribute resolves to a no-op callable
        def _noop(*_args, **_kwargs):
            return None

        return _noop


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def build_config(
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_concurrent_requests: int = DEFAULT_CONCURRENCY,
    proxy: str | None = None,
    no_nsfw: bool = False,
    verbose: bool = False,
):
    """Create an isolated config object for a single search/export request."""

    class _RequestConfig:
        pass

    cfg = _RequestConfig()

    # Copy module-level constants (UPPER_CASE): *_PATH, *_DIRECTORY, FONT_*, etc.
    for key in dir(_base_config):
        if key.isupper():
            setattr(cfg, key, getattr(_base_config, key))

    # HTTP / runtime knobs (validated/clamped).
    cfg.console = QuietConsole()
    cfg.timeout = _clamp(int(timeout), MIN_TIMEOUT, MAX_TIMEOUT)
    cfg.max_concurrent_requests = _clamp(
        int(max_concurrent_requests), MIN_CONCURRENCY, MAX_CONCURRENCY
    )
    cfg.proxy = proxy or None
    cfg.verbose = bool(verbose)
    cfg.no_nsfw = bool(no_nsfw)
    cfg.userAgent = getRandomUserAgent(cfg)

    # Feature flags OFF: the web layer performs AI analysis and exports via
    # explicit endpoints, not inline during the scan. Keeping aiModel falsy also
    # avoids the CLI's inline-AI branch that references an unimported symbol.
    cfg.ai = False
    cfg.aiModel = None
    cfg.ai_analysis = None
    cfg.dump = False
    cfg.csv = False
    cfg.pdf = False
    cfg.json = False
    cfg.filter = None

    cfg.instagram_session_id = os.getenv("INSTAGRAM_SESSION_ID") or None
    cfg.api_url = os.getenv("API_URL")

    # Per-search mutable state the core reads/writes.
    cfg.metadata_params = None
    cfg.username_sites = None
    cfg.email_sites = None
    cfg.currentUser = None
    cfg.currentEmail = None
    cfg.usernameFoundAccounts = None
    cfg.emailFoundAccounts = None
    cfg.saveDirectory = None

    cfg.dateRaw = datetime.now().strftime("%m_%d_%Y")
    cfg.datePretty = datetime.now().strftime("%B %d, %Y")

    return cfg
