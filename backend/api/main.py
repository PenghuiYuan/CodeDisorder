"""FastAPI app entry point.

Run with: ``uvicorn backend.api.main:app --host 0.0.0.0 --port 8000``

This module **does not** call ``uvicorn.run``; the user starts the server
themselves. We only construct the ``app`` object.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from backend.api import errors as errcodes
from backend.api.dispatcher import get_dispatcher
from backend.api.routes_confuse import _error
from backend.api.routes_confuse import router as confuse_router
from backend.api.routes_meta import router as meta_router

logger = logging.getLogger(__name__)

# Where the built React app lives (Dockerfile stage 2 copies it here).
# In dev we typically run Vite on :5173 and don't have this directory; the
# ``check_dir=False`` argument keeps the API usable either way.
_FRONTEND_DIST = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)


# ---------------------------------------------------------------------------
# Lifespan: warm the dispatcher (so WORKER_MODE is logged at startup) and
# shut it down cleanly.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    dispatcher = get_dispatcher()
    logger.info("API running on http://0.0.0.0:8000")
    logger.info("dispatcher mode: %s", dispatcher.mode)
    try:
        yield
    finally:
        logger.info("shutting down dispatcher")
        try:
            await dispatcher.shutdown()
        except Exception:  # noqa: BLE001
            logger.exception("error during dispatcher shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CodeConfuse.Web API",
    version="0.1.0",
    description="AST-level source code obfuscation (SPEC §6).",
    lifespan=_lifespan,
)

# CORS — the dev frontend is Vite on :5173 (SPEC §14.2). CORS preflight is
# needed for POST /api/confuse.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    max_age=600,
)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(meta_router)
app.include_router(confuse_router)

# Serve the built React app at "/" if the dist directory exists (Docker image
# and local `npm run build` workflow). Dev mode (Vite on :5173) just hits the
# API directly and the mount is skipped.
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
    logger.info("serving frontend from %s", _FRONTEND_DIST)
else:
    logger.info("frontend dist not found at %s; API-only mode", _FRONTEND_DIST)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@app.exception_handler(ValidationError)
async def _on_validation_error(request: Request, exc: ValidationError) -> JSONResponse:
    """Pydantic body validation → 400 with our envelope."""
    body = _error(
        errcodes.INVALID_COUNT,  # generic "bad request" code, see SPEC §15.4
        "request",
        "request body failed validation",
    )
    return JSONResponse(status_code=400, content=body, headers={"Cache-Control": "no-store"})


@app.exception_handler(Exception)
async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler. Never expose Python traceback (SPEC §15.4 #2)."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    body = _error(
        errcodes.INTERNAL_ERROR,
        "request",
        "internal server error",
    )
    return JSONResponse(status_code=500, content=body, headers={"Cache-Control": "no-store"})


__all__ = ["app"]
