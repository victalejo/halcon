"""AI profiling service.

Wraps the same Halcon AI endpoint the CLI uses, but:
  * runs the blocking HTTP call in a thread so it never blocks the event loop;
  * returns structured data instead of the CLI's typewriter stdout effect;
  * degrades gracefully when no API key / API_URL is configured.

Only site *names* are sent to the API — never the searched username/email —
mirroring the CLI's privacy stance.
"""

from __future__ import annotations

import asyncio
import json
from typing import Dict, List

from modules.ai.client import send_prompt  # noqa: F401  (kept for parity/reference)
from modules.ai.key_manager import load_api_key_from_file
from modules.utils.http_client import do_sync_request

MIN_SITES_FOR_ANALYSIS = 3


def _analyze_sync(site_names: List[str], config) -> Dict:
    apikey = load_api_key_from_file(config)
    if not apikey:
        return {
            "available": False,
            "message": "No AI API key configured. Run the CLI once with --setup-ai.",
        }
    if not config.api_url:
        return {"available": False, "message": "API_URL is not configured."}

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "halcon-web",
        "x-api-key": apikey,
    }
    payload = json.dumps({"prompt": ", ".join(site_names)})

    try:
        response = do_sync_request(
            method="POST",
            url=config.api_url.rstrip("/") + "/analyze",
            config=config,
            customHeaders=headers,
            data=payload,
        )
    except Exception:  # network/runtime errors are surfaced, not crashed on
        return {"available": True, "ok": False, "message": "AI request failed."}

    if response is None:
        return {"available": True, "ok": False, "message": "AI request failed."}

    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError):
        data = None

    if response.status_code != 200 or not data:
        message = (data or {}).get("message", "AI service returned an error.")
        return {"available": True, "ok": False, "message": message}

    if data.get("success"):
        return {
            "available": True,
            "ok": True,
            "result": data["data"]["result"],
            "remaining_quota": data["data"].get("remaining_quota"),
        }
    return {"available": True, "ok": False, "message": "AI service returned no result."}


async def analyze(site_names: List[str], config) -> Dict:
    """Analyze found site names, off the event loop."""
    site_names = [s for s in (site_names or []) if s]
    if len(site_names) < MIN_SITES_FOR_ANALYSIS:
        return {
            "available": True,
            "ok": False,
            "message": (
                f"Need at least {MIN_SITES_FOR_ANALYSIS} found accounts for AI analysis."
            ),
        }
    return await asyncio.to_thread(_analyze_sync, site_names, config)
