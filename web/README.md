# Halcon Web

A web interface for the Halcon OSINT engine. It reuses the existing CLI core
(`src/modules`) unchanged and adds a FastAPI layer with a live, streaming UI.

> **Authorized use only.** This tool performs the same reconnaissance as the
> Halcon CLI. Use it for legitimate OSINT, security research, and accounts
> you are authorized to investigate.

## Features

- 🔎 Username **and** email search across the WhatsMyName site set (600+).
- 📡 **Live results** streamed to the browser via Server-Sent Events (SSE) with
  a real-time progress bar — no waiting for the full scan to finish.
- 🧰 Advanced options: NSFW toggle, request timeout, concurrency.
- 📄 Export found accounts to **PDF / CSV / JSON** (reuses the CLI exporters).
- ✨ Optional **AI profiling** of the found site names (requires an API key set
  up via the CLI's `--setup-ai`; degrades gracefully when absent).

## Architecture

```
web/
  __init__.py          # sys.path + cwd bootstrap so the CLI core imports cleanly
  config_factory.py    # per-request, isolated config object (no global singleton)
  events.py            # JSON-safe sanitizing + SSE framing
  search_service.py    # reuses core checkSite(); re-runs the fan-out to stream live
  ai_service.py        # gated, non-blocking AI analysis (off the event loop)
  export_service.py    # PDF/CSV/JSON via existing exporters (path-traversal safe)
  app.py               # FastAPI routes
  static/              # self-contained UI (no Node build step)
run_web.py             # uvicorn entry point
```

The core CLI is untouched: detection logic (`modules.core.*.checkSite`), filters,
list operations, and exporters are imported as-is.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-web.txt
python run_web.py
# open http://127.0.0.1:8000
```

On first start the server downloads the WhatsMyName username list
(`data/wmn-data.json`) automatically. If it cannot (offline), use the
**refresh** endpoint once you have connectivity:

```bash
curl -X POST http://127.0.0.1:8000/api/refresh-list
```

### Dev auto-reload

```bash
python run_web.py --reload
```

## Run with Docker

```bash
docker build -f Dockerfile.web -t halcon-web .
docker run --rm -p 8000:8000 halcon-web
```

## API

| Method | Path                    | Description                                   |
|--------|-------------------------|-----------------------------------------------|
| GET    | `/`                     | Single-page UI                                |
| GET    | `/api/health`           | Liveness + whether the site list is present   |
| GET    | `/api/search/username`  | SSE stream — params: `q`, `nsfw`, `timeout`, `concurrency` |
| GET    | `/api/search/email`     | SSE stream — same params                       |
| POST   | `/api/refresh-list`     | (Re)download the WhatsMyName username list    |
| POST   | `/api/ai/analyze`       | `{ "site_names": [...] }` → AI profile        |
| POST   | `/api/export`           | `{ format, kind, target, results, ai_analysis? }` → file download |

### SSE event shapes

```jsonc
{ "type": "start",    "kind": "username", "target": "johndoe", "total": 632 }
{ "type": "progress", "completed": 120, "total": 632 }
{ "type": "found",    "completed": 121, "total": 632, "result": { "name": "...", "url": "...", "category": "...", "metadata": [...] } }
{ "type": "done",     "found_count": 14, "results": [ ... ] }
{ "type": "error",    "message": "..." }
```

## AI profiling

`POST /api/ai/analyze` uses DeepSeek directly when `DEEPSEEK_API_KEY` is set;
otherwise it falls back to the hosted endpoint (`API_URL` + `.ai_key.json` from
`--setup-ai`). Only the names of the sites found are sent, never the username
or email. The answer is in Spanish with the same `result` shape either way.

| Variable | Default | Meaning |
|----------|---------|---------|
| `DEEPSEEK_API_KEY` | _(unset)_ | Enables the DeepSeek backend |
| `DEEPSEEK_MODEL` | `deepseek-chat` | Model to use |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API base URL |

## Security (auth + rate limit)

Auth is **opt-in** (open for local use). Rate limiting is **on by default**.

| Variable | Default | Meaning |
|----------|---------|---------|
| `HALCON_API_KEY` | _(unset)_ | If set, require this key on `/api/*` (except health) |
| `HALCON_BASIC_USER` | _(unset)_ | With password, enable HTTP Basic |
| `HALCON_BASIC_PASSWORD` | _(unset)_ | Pair for Basic auth |
| `HALCON_RATE_LIMIT` | `60` | Max requests per IP per window (`0` = off) |
| `HALCON_RATE_LIMIT_WINDOW` | `60` | Window length in seconds |

**API key** is accepted as:

- Header `X-API-Key: <key>`
- Header `Authorization: Bearer <key>`
- Query `?api_key=<key>` (needed for `EventSource` / SSE, which cannot set headers)

Public (no auth, no rate limit): `/`, `/api/health`, `/static/*`.

`GET /api/health` reports `auth_required`, `auth_modes`, and rate-limit settings
so the UI can show the API key field when the server is locked down.

Example production-ish env:

```bash
export HALCON_API_KEY="$(openssl rand -hex 24)"
export HALCON_RATE_LIMIT=30
export HALCON_RATE_LIMIT_WINDOW=60
python run_web.py
```

You can still put Traefik/nginx basic-auth in front; app-level auth is defense
in depth for direct exposure.

## Notes & limits

- Prefer binding to localhost or putting a reverse proxy in front for public
  deploys; enable `HALCON_API_KEY` (or Basic) whenever the service is reachable
  beyond a trusted network.
- Each search opens its own `aiohttp` session and isolated config; concurrent
  users are supported. Per-request concurrency is capped at 100.
- Exported files are written under `results/` (already git-ignored).
- One email site (Eventbrite) performs a **synchronous** pre-check request in
  the core (`perform_pre_check`). During an email search this briefly blocks the
  event loop (bounded by `timeout`). A proper fix is to make that pre-check
  async in the core; out of scope for this web v1.
