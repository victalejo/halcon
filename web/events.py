"""Event helpers: JSON-safe result sanitizing and SSE framing."""

from __future__ import annotations

import json
from typing import Any, Dict

_PRIMITIVES = (str, int, float, bool, type(None))


def json_safe(obj: Any) -> Any:
    """Recursively coerce arbitrary core output into JSON-serializable data.

    Site metadata can contain unexpected types (e.g. aiohttp header objects).
    Anything that is not a primitive / list / dict is stringified so a single
    bad value never breaks the stream.
    """
    if isinstance(obj, _PRIMITIVES):
        return obj
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    return str(obj)


def serialize_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Project a core result dict to the fields the frontend needs."""
    return {
        "name": result.get("name"),
        "url": result.get("url"),
        "category": result.get("category"),
        "metadata": json_safe(result.get("metadata")),
    }


def sse(event: Dict[str, Any]) -> str:
    """Frame a dict as a Server-Sent Event line. The event ``type`` lives in the
    JSON payload so the client only needs a single ``onmessage`` handler."""
    return f"data: {json.dumps(json_safe(event), ensure_ascii=False)}\n\n"
