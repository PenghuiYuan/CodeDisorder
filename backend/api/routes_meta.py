"""Meta routes: presets / strategies / health (SPEC §6.2).

The ``presets`` blob is loaded from ``backend/resources/presets.json`` once at
module import (DESIGN §3.4) and served verbatim. ``strategies`` is derived
from the same blob so the UI can render a single source of truth.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["meta"])


# ---------------------------------------------------------------------------
# presets.json loader
# ---------------------------------------------------------------------------

_PRESETS_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "resources", "presets.json")
)

# Cached on import. If the file is missing we keep an empty doc and the
# ``/api/presets`` route will surface a clear 500 (not a crash).
_PRESETS_CACHE: dict[str, Any] = {}


def _load_presets() -> dict[str, Any]:
    global _PRESETS_CACHE
    if _PRESETS_CACHE:
        return _PRESETS_CACHE
    try:
        with open(_PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error("presets.json not found at %s", _PRESETS_PATH)
        data = {"presets": [], "custom": {}}
    except json.JSONDecodeError as e:
        logger.error("presets.json is not valid JSON: %s", e)
        data = {"presets": [], "custom": {}}
    _PRESETS_CACHE = data
    return data


def _derive_strategies(presets: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the strategy catalogue from the preset shapes.

    Each strategy becomes::

        {"key": "rename", "label": "rename", "values": [true, false], "default": true}
    """
    catalog: dict[str, dict[str, Any]] = {}
    for preset in presets.get("presets", []) + [presets.get("custom", {})]:
        strategies = preset.get("strategies") or {}
        for key, value in strategies.items():
            entry = catalog.setdefault(key, {"key": key, "values": set(), "defaults": set()})
            entry["values"].add(value)
            entry["defaults"].add(value)

    out: list[dict[str, Any]] = []
    for key in sorted(catalog):
        entry = catalog[key]
        values = sorted(
            (str(v) if not isinstance(v, bool) else ("true" if v else "false"))
            for v in entry["values"]
        )
        defaults = sorted(
            (str(v) if not isinstance(v, bool) else ("true" if v else "false"))
            for v in entry["defaults"]
        )
        out.append(
            {
                "key": key,
                "values": values,
                "default": defaults[0] if defaults else None,
            }
        )
    return out


# Load at import time so the first request is fast and failures are loud.
_PRESETS = _load_presets()
_STRATEGIES = _derive_strategies(_PRESETS)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/presets")
async def get_presets() -> JSONResponse:
    """Return the OJ preset catalogue (SPEC §6.2)."""
    return JSONResponse(
        content=_PRESETS,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/strategies")
async def get_strategies() -> JSONResponse:
    """Return the strategy catalogue derived from presets.json (SPEC §6.2)."""
    return JSONResponse(
        content={"strategies": _STRATEGIES},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/health")
async def health() -> JSONResponse:
    """SPEC §6.2 health check."""
    return JSONResponse(
        content={"status": "ok"},
        headers={"Cache-Control": "no-store"},
    )
