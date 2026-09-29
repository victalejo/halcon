"""Application-level auth and rate limiting for Halcon Web.

Auth is **opt-in** via environment variables so local use stays open:

  HALCON_API_KEY              If set, require this key (header / bearer / query).
  HALCON_BASIC_USER           With HALCON_BASIC_PASSWORD, accept HTTP Basic.
  HALCON_BASIC_PASSWORD

Rate limiting is **on by default** (disable with HALCON_RATE_LIMIT=0):

  HALCON_RATE_LIMIT           Max requests per window per client (default 60).
  HALCON_RATE_LIMIT_WINDOW    Window length in seconds (default 60).

Public paths (no auth, no rate limit): ``/``, ``/api/health``, ``/static/*``.
Health still reports whether auth is required so the UI can prompt for a key.
"""

from __future__ import annotations

import base64
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Paths that stay reachable without credentials (health checks, SPA shell, assets).
_PUBLIC_EXACT = frozenset({"/", "/api/health"})
_PUBLIC_PREFIXES = ("/static/",)


@dataclass(frozen=True)
class SecurityConfig:
    api_key: Optional[str] = None
    basic_user: Optional[str] = None
    basic_password: Optional[str] = None
    rate_limit: int = 60
    rate_window: int = 60

    @classmethod
    def from_env(cls) -> "SecurityConfig":
        api_key = (os.getenv("HALCON_API_KEY") or "").strip() or None
        basic_user = (os.getenv("HALCON_BASIC_USER") or "").strip() or None
        basic_password = os.getenv("HALCON_BASIC_PASSWORD")
        if basic_password is not None:
            basic_password = basic_password if basic_password != "" else None
        # Empty user alone does not enable basic auth.
        if not basic_user or basic_password is None:
            basic_user = None
            basic_password = None

        try:
            rate_limit = int(os.getenv("HALCON_RATE_LIMIT", "60"))
        except ValueError:
            rate_limit = 60
        try:
            rate_window = int(os.getenv("HALCON_RATE_LIMIT_WINDOW", "60"))
        except ValueError:
            rate_window = 60
        rate_limit = max(0, rate_limit)
        rate_window = max(1, rate_window)

        return cls(
            api_key=api_key,
            basic_user=basic_user,
            basic_password=basic_password,
            rate_limit=rate_limit,
            rate_window=rate_window,
        )

    @property
    def auth_required(self) -> bool:
        return bool(self.api_key) or (
            self.basic_user is not None and self.basic_password is not None
        )

    @property
    def auth_modes(self) -> List[str]:
        modes: List[str] = []
        if self.api_key:
            modes.append("api_key")
        if self.basic_user is not None and self.basic_password is not None:
            modes.append("basic")
        return modes

    @property
    def rate_limit_enabled(self) -> bool:
        return self.rate_limit > 0


class RateLimiter:
    """Thread-safe fixed-window counter (requests per client key)."""

    def __init__(self, limit: int, window: int) -> None:
        self.limit = limit
        self.window = window
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            return max(0, self.limit - len(q))

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Process-wide limiter; recreated when limit/window change (e.g. tests).
_limiter: Optional[RateLimiter] = None
_limiter_key: Optional[Tuple[int, int]] = None
_limiter_lock = threading.Lock()


def get_rate_limiter(cfg: SecurityConfig) -> Optional[RateLimiter]:
    global _limiter, _limiter_key
    if not cfg.rate_limit_enabled:
        return None
    key = (cfg.rate_limit, cfg.rate_window)
    with _limiter_lock:
        if _limiter is None or _limiter_key != key:
            _limiter = RateLimiter(cfg.rate_limit, cfg.rate_window)
            _limiter_key = key
        return _limiter


def reset_rate_limiter() -> None:
    """Clear rate-limit state (tests)."""
    global _limiter, _limiter_key
    with _limiter_lock:
        if _limiter is not None:
            _limiter.reset()
        _limiter = None
        _limiter_key = None


def is_public_path(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def client_ip(request: Request) -> str:
    """Best-effort client IP (honours first X-Forwarded-For hop)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Left-most is the original client when behind a trusted proxy.
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def extract_api_key(request: Request) -> Optional[str]:
    header = (request.headers.get("x-api-key") or "").strip()
    if header:
        return header

    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token

    # EventSource cannot set headers; allow query param for SSE streams.
    key = (request.query_params.get("api_key") or "").strip()
    return key or None


def _check_basic(request: Request, user: str, password: str) -> bool:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(auth[6:].strip(), validate=True).decode("utf-8")
    except Exception:
        return False
    if ":" not in raw:
        return False
    u, p = raw.split(":", 1)
    return secrets.compare_digest(u, user) and secrets.compare_digest(p, password)


def authenticate(request: Request, cfg: SecurityConfig) -> bool:
    """Return True if the request satisfies configured auth (or none is required)."""
    if not cfg.auth_required:
        return True

    if cfg.api_key:
        provided = extract_api_key(request)
        if provided and secrets.compare_digest(provided, cfg.api_key):
            return True

    if cfg.basic_user is not None and cfg.basic_password is not None:
        if _check_basic(request, cfg.basic_user, cfg.basic_password):
            return True

    return False


def unauthorized_response(cfg: SecurityConfig) -> JSONResponse:
    headers = {}
    # Advertise schemes so browsers can prompt for Basic when configured.
    schemes = []
    if cfg.basic_user is not None:
        schemes.append('Basic realm="Halcon Web"')
    if cfg.api_key:
        schemes.append("Bearer")
    if schemes:
        headers["WWW-Authenticate"] = ", ".join(schemes)
    return JSONResponse(
        status_code=401,
        content={
            "detail": "Authentication required.",
            "auth_modes": cfg.auth_modes,
        },
        headers=headers,
    )


def rate_limited_response(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": str(max(1, retry_after))},
    )


class SecurityMiddleware:
    """ASGI middleware: rate limit then authenticate non-public paths."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path
        cfg = SecurityConfig.from_env()

        if is_public_path(path):
            await self.app(scope, receive, send)
            return

        limiter = get_rate_limiter(cfg)
        if limiter is not None:
            ip = client_ip(request)
            if not limiter.allow(ip):
                response = rate_limited_response(cfg.rate_window)
                await response(scope, receive, send)
                return

        if not authenticate(request, cfg):
            response = unauthorized_response(cfg)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def security_status() -> dict:
    """Snapshot for /api/health (no secrets)."""
    cfg = SecurityConfig.from_env()
    return {
        "auth_required": cfg.auth_required,
        "auth_modes": cfg.auth_modes,
        "rate_limit": cfg.rate_limit if cfg.rate_limit_enabled else 0,
        "rate_limit_window": cfg.rate_window if cfg.rate_limit_enabled else 0,
    }
