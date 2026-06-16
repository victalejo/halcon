#!/usr/bin/env python3
"""Entry point for the Halcon web server.

Usage:
    python run_web.py                 # http://127.0.0.1:8000
    HOST=0.0.0.0 PORT=8080 python run_web.py
    python run_web.py --reload        # dev auto-reload

Environment variables:
    HOST     bind address (default 127.0.0.1)
    PORT     port (default 8000)
    API_URL  Halcon AI endpoint (default from .env)
"""

import os
import sys

# Run from the repo root so config.py's os.getcwd()-relative paths resolve.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO_ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = "--reload" in sys.argv

    print(f"🛰️  Halcon Web → http://{host}:{port}")
    uvicorn.run("web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
