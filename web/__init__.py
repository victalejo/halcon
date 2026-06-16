"""Halcon Web — a FastAPI layer on top of the existing OSINT engine.

This package reuses the CLI core (``src/modules``) unchanged. To make those
modules importable and to keep the ``os.getcwd()``-relative paths in
``src/config.py`` valid, we set up ``sys.path`` and the working directory here,
at import time, before any ``web.*`` submodule imports the core.
"""

import os
import sys

# Repo root = parent of this package directory.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")

# Make `import config` and `from modules... import ...` resolve to the CLI core.
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# src/config.py builds data/asset/log paths from os.getcwd(); the CLI assumes it
# is run from the repo root. Mirror that so readList()/downloadList()/exports and
# asset lookups resolve correctly regardless of how uvicorn was launched.
try:
    os.chdir(REPO_ROOT)
except OSError:  # pragma: no cover - extremely unusual (e.g. deleted dir)
    pass

__all__ = ["REPO_ROOT", "SRC_DIR"]
