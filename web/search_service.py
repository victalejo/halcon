"""Streaming search service.

Reuses the CLI detection logic (``modules.core.*.checkSite``) unchanged, but
reimplements the fan-out loop so each completed site check can be streamed to
the browser in real time via Server-Sent Events. The original ``fetchResults``
only returns once every site is checked, which would make a live progress bar
impossible without touching the core.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Dict, List

import aiohttp

from modules.core.username import checkSite as username_check_site
from modules.core.email import checkSite as email_check_site
from modules.utils.filter import filterNSFW
from modules.utils.input import processInput
from modules.whatsmyname.list_operations import readList

from .events import sse, serialize_result


class ListNotReadyError(RuntimeError):
    """Raised when a site list file is missing (not downloaded yet)."""


def _load_sites(kind: str, config) -> List[Dict]:
    try:
        data = readList(kind, config)
    except FileNotFoundError as exc:
        raise ListNotReadyError(str(exc)) from exc
    sites = (data or {}).get("sites", [])
    if config.no_nsfw:
        sites = [s for s in sites if filterNSFW(s)]
    return sites


async def _drain(pending: List[asyncio.Future]) -> None:
    """Cancel any still-running checks (e.g. on client disconnect)."""
    for fut in pending:
        if not fut.done():
            fut.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _stream(kind: str, target: str, config, build_check) -> AsyncGenerator[str, None]:
    """Shared streaming loop for username/email searches."""
    try:
        sites = _load_sites(kind, config)
    except ListNotReadyError:
        yield sse(
            {
                "type": "error",
                "message": "Site list not available yet. Refresh it via POST /api/refresh-list.",
            }
        )
        return

    total = len(sites)
    yield sse({"type": "start", "kind": kind, "target": target, "total": total})

    if total == 0:
        yield sse({"type": "done", "found_count": 0, "results": []})
        return

    semaphore = asyncio.Semaphore(config.max_concurrent_requests)
    found: List[Dict] = []
    completed = 0

    async with aiohttp.ClientSession() as session:
        pending = [
            asyncio.ensure_future(build_check(site, session, semaphore))
            for site in sites
        ]
        try:
            for future in asyncio.as_completed(pending):
                result = await future
                completed += 1
                if result and result.get("status") == "FOUND":
                    serialized = serialize_result(result)
                    found.append(serialized)
                    yield sse(
                        {
                            "type": "found",
                            "completed": completed,
                            "total": total,
                            "result": serialized,
                        }
                    )
                else:
                    yield sse(
                        {"type": "progress", "completed": completed, "total": total}
                    )
        except asyncio.CancelledError:
            await _drain(pending)
            raise
        finally:
            await _drain(pending)

    found.sort(key=lambda r: (r.get("name") or "").lower())
    yield sse({"type": "done", "found_count": len(found), "results": found})


async def stream_username_search(target: str, config) -> AsyncGenerator[str, None]:
    # checkSite (username) reads config.metadata_params["sites"].
    try:
        config.metadata_params = readList("metadata", config)
    except FileNotFoundError:
        config.metadata_params = {"sites": {}}
    config.currentUser = target

    async def build_check(site, session, semaphore):
        url = site["uri_check"].replace("{account}", target)
        return await username_check_site(
            site=site,
            method="GET",
            url=url,
            session=session,
            semaphore=semaphore,
            config=config,
        )

    async for chunk in _stream("username", target, config, build_check):
        yield chunk


async def stream_email_search(target: str, config) -> AsyncGenerator[str, None]:
    config.currentEmail = target

    async def build_check(site, session, semaphore):
        if site.get("input_operation") is not None:
            processed = processInput(target, site["input_operation"], config)
        else:
            processed = target
        url = site["uri_check"].replace("{account}", processed)
        data = site["data"].replace("{account}", processed) if site.get("data") else None
        headers = site["headers"] if site.get("headers") else None
        return await email_check_site(
            site=site,
            method=site["method"],
            url=url,
            session=session,
            semaphore=semaphore,
            config=config,
            data=data,
            headers=headers,
        )

    async for chunk in _stream("email", target, config, build_check):
        yield chunk
