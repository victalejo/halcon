"""Export service — turn a result set into a downloadable PDF/CSV/JSON file.

Reuses the existing exporters (``saveToCsv``/``saveToJson``/``saveToPdf``) and
their ``results/`` directory convention. The searched target is sanitized into a
filesystem-safe identifier to prevent path traversal, since it flows into the
output file path via ``generateName``.
"""

from __future__ import annotations

import asyncio
import os
from typing import Dict, List, Optional, Tuple

from modules.export.csv import saveToCsv
from modules.export.json import saveToJson
from modules.export.pdf import saveToPdf
from modules.export.file_operations import createSaveDirectory, generateName

from .config_factory import build_config
from .sanitize import safe_identifier

VALID_FORMATS = ("pdf", "csv", "json")
VALID_KINDS = ("username", "email")

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "csv": "text/csv",
    "json": "application/json",
}


class ExportError(RuntimeError):
    pass


def _build_export(
    fmt: str,
    kind: str,
    target: str,
    results: List[Dict],
    ai_analysis: Optional[Dict],
) -> Tuple[str, str, str]:
    if fmt not in VALID_FORMATS:
        raise ExportError(f"Unsupported format: {fmt!r}")
    if kind not in VALID_KINDS:
        raise ExportError(f"Unsupported kind: {kind!r}")
    if not results:
        raise ExportError("No results to export.")

    identifier = safe_identifier(target)

    config = build_config()
    config.pdf = fmt == "pdf"
    config.csv = fmt == "csv"
    config.json = fmt == "json"
    config.ai_analysis = ai_analysis or None
    if kind == "username":
        config.currentUser = identifier
    else:
        config.currentEmail = identifier

    createSaveDirectory(config)

    if fmt == "csv":
        ok = saveToCsv(results, config)
    elif fmt == "json":
        ok = saveToJson(results, config)
    else:
        ok = saveToPdf(results, kind, config)

    if not ok:
        raise ExportError("Exporter failed to write the file.")

    file_name = generateName(config, fmt)
    file_path = os.path.join(config.saveDirectory, file_name)
    if not os.path.isfile(file_path):
        raise ExportError("Export file was not created.")

    download_name = f"{identifier}_{config.dateRaw}_halcon.{fmt}"
    return file_path, download_name, _MEDIA_TYPES[fmt]


async def export(
    fmt: str,
    kind: str,
    target: str,
    results: List[Dict],
    ai_analysis: Optional[Dict] = None,
) -> Tuple[str, str, str]:
    """Async wrapper; file writing (and PDF rendering) runs off the event loop.

    Returns ``(file_path, download_name, media_type)``.
    """
    return await asyncio.to_thread(
        _build_export, fmt, kind, target, results, ai_analysis
    )
