"""Small, dependency-free sanitizers (safe to import anywhere)."""

from __future__ import annotations

import re

_UNSAFE = re.compile(r"[^A-Za-z0-9._@-]")


def safe_identifier(target: str, max_len: int = 100) -> str:
    """Collapse a search target into a filesystem-safe slug.

    Prevents path traversal when the value flows into an output file path:
    strips path separators / ``..`` and any character outside a safe set.
    """
    slug = _UNSAFE.sub("_", (target or "").strip())
    slug = slug.replace("..", "_").strip("._")
    slug = slug[:max_len]
    return slug or "result"
