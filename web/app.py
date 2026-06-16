"""FastAPI application for Halcon Web.

Endpoints:
  GET  /                       -> single-page UI
  GET  /api/health             -> liveness + whether the site list is present
  GET  /api/search/username    -> SSE stream of live results
  GET  /api/search/email       -> SSE stream of live results
  POST /api/refresh-list       -> (re)download the WhatsMyName username list
  POST /api/ai/analyze         -> AI profile from found site names
  POST /api/export             -> download results as PDF/CSV/JSON
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config as core_config
from modules.whatsmyname.list_operations import downloadList

from . import REPO_ROOT
from .config_factory import build_config
from .search_service import stream_email_search, stream_username_search
from .ai_service import analyze as ai_analyze
from .export_service import ExportError, export as export_results

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_QUERY_LEN = 200

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable proxy buffering so events flush live
}


def _site_list_present() -> bool:
    return os.path.isfile(core_config.USERNAME_LIST_PATH)


async def _ensure_site_list() -> None:
    """Download the username list if it is missing (best effort)."""
    if _site_list_present():
        return
    try:
        await asyncio.to_thread(downloadList, build_config())
        print("[halcon-web] Downloaded WhatsMyName username list.")
    except Exception as exc:  # network may be unavailable; keep serving
        print(f"[halcon-web] Could not download site list at startup: {exc}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _ensure_site_list()
    yield


app = FastAPI(title="Halcon Web", version="1.0.0", lifespan=lifespan)


# ----------------------------- validation helpers ----------------------------
def _clean_query(value: str, field: str = "query") -> str:
    value = (value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field} is required.")
    if len(value) > MAX_QUERY_LEN:
        raise HTTPException(status_code=400, detail=f"{field} is too long.")
    if any(ord(c) < 32 for c in value):
        raise HTTPException(
            status_code=400, detail=f"{field} contains invalid control characters."
        )
    return value


# --------------------------------- models ------------------------------------
class AIAnalyzeRequest(BaseModel):
    site_names: List[str] = Field(default_factory=list)


class ExportRequest(BaseModel):
    format: str
    kind: str
    target: str
    results: List[Dict[str, Any]] = Field(default_factory=list)
    ai_analysis: Optional[Dict[str, Any]] = None


# --------------------------------- routes -------------------------------------
@app.get("/api/health")
async def health():
    return {"status": "ok", "site_list_present": _site_list_present()}


@app.get("/api/search/username")
async def search_username(
    q: str = Query(..., description="Username to search"),
    nsfw: bool = Query(True, description="Include NSFW sites"),
    timeout: int = Query(30, ge=1, le=120),
    concurrency: int = Query(30, ge=1, le=100),
):
    target = _clean_query(q, "username")
    config = build_config(
        timeout=timeout, max_concurrent_requests=concurrency, no_nsfw=not nsfw
    )
    return StreamingResponse(
        stream_username_search(target, config),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.get("/api/search/email")
async def search_email(
    q: str = Query(..., description="Email to search"),
    nsfw: bool = Query(True, description="Include NSFW sites"),
    timeout: int = Query(30, ge=1, le=120),
    concurrency: int = Query(30, ge=1, le=100),
):
    target = _clean_query(q, "email")
    if "@" not in target:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    config = build_config(
        timeout=timeout, max_concurrent_requests=concurrency, no_nsfw=not nsfw
    )
    return StreamingResponse(
        stream_email_search(target, config),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.post("/api/refresh-list")
async def refresh_list():
    try:
        await asyncio.to_thread(downloadList, build_config())
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not download site list: {exc}"
        )
    return {"status": "ok", "site_list_present": _site_list_present()}


@app.post("/api/ai/analyze")
async def ai_analyze_route(payload: AIAnalyzeRequest):
    config = build_config()
    result = await ai_analyze(payload.site_names, config)
    return JSONResponse(result)


@app.post("/api/export")
async def export_route(payload: ExportRequest):
    try:
        file_path, download_name, media_type = await export_results(
            fmt=payload.format,
            kind=payload.kind,
            target=payload.target,
            results=payload.results,
            ai_analysis=payload.ai_analysis,
        )
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # exporter blew up unexpectedly
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}")
    return FileResponse(file_path, media_type=media_type, filename=download_name)


# --------------------------------- frontend -----------------------------------
@app.get("/")
async def index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.isfile(index_path):
        raise HTTPException(status_code=500, detail="Frontend not found.")
    return FileResponse(index_path)


# Mounted last so it doesn't shadow the API/index routes above.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
