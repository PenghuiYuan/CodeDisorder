"""POST /api/confuse — the only stateful route in the API (DESIGN §3.2).

Flow (DESIGN §3.2 steps 1-6):

  1. language_in == language_out                     else 400
  2. count in {1, 3, 5, 10}                          else 400
  3. len(code.encode('utf-8')) <= 200 * 1024        else 413
  4. worker = dispatcher.acquire(language_in)
  5. result = await call_worker(worker, "confuse", params, timeout=10.0)
  6. dispatcher.release(worker)
  7. return ConfuseResponse(result)

Error mapping (SPEC §6.1 + §15.6):

  * ``WorkerError`` (incl. timeout that survived degradation) → 200 with
    ``status="error"`` envelope.  Parse / transform / verify errors live
    inside the Worker and come back shaped already.
  * Pydantic ``ValidationError`` → 400 with envelope.
  * Payload too large → 413 with envelope.
  * Any other exception → handled by the top-level handler in ``main.py``.
"""

from __future__ import annotations

import base64
import io
import logging
import time
import zipfile
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.api import errors as errcodes
from backend.api.dispatcher import get_dispatcher
from backend.api.schemas import (
    ConfuseRequest,
    ConfuseResponse,
    ErrorItem,
    ErrorResponse,
)
from backend.api.worker_client import (
    WorkerError,
    WorkerTimeoutError,
    call_worker,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["confuse"])

#: Hard limit (SPEC §6.3). 200 KB UTF-8.
MAX_CODE_BYTES = 200 * 1024

#: Allowed batch sizes (SPEC §6.3).
ALLOWED_COUNTS = {1, 3, 5, 10}


def _error(code: str, stage: str, message: str, *, items: list[ErrorItem] | None = None) -> dict[str, Any]:
    """Build an ``ErrorResponse`` payload (status=error)."""
    return ErrorResponse(
        status="error",
        code=code,
        stage=stage,
        message=message,
        errors=items or [],
    ).model_dump()


@router.post("/confuse")
async def confuse(req: ConfuseRequest, request: Request) -> JSONResponse:
    """SPEC §6.1 — main obfuscation entry point."""
    started = time.monotonic()
    correlation_id = request.headers.get("x-correlation-id") or ""

    # --- 1. language_in == language_out --------------------------------
    if req.language_in != req.language_out:
        logger.info(
            "confuse reject: invalid_target_language in=%s out=%s cid=%s",
            req.language_in, req.language_out, correlation_id,
        )
        body = _error(
            errcodes.INVALID_TARGET_LANGUAGE,
            "request",
            "language_in and language_out must be equal (MVP does not do cross-language translation)",
        )
        return JSONResponse(status_code=400, content=body, headers={"Cache-Control": "no-store"})

    # --- 2. count ∈ {1, 3, 5, 10} -------------------------------------
    if req.count not in ALLOWED_COUNTS:
        logger.info(
            "confuse reject: invalid_count count=%s cid=%s", req.count, correlation_id,
        )
        body = _error(
            errcodes.INVALID_COUNT,
            "request",
            f"count must be one of {sorted(ALLOWED_COUNTS)}, got {req.count}",
        )
        return JSONResponse(status_code=400, content=body, headers={"Cache-Control": "no-store"})

    # --- 3. payload size -----------------------------------------------
    code_bytes = len(req.code.encode("utf-8"))
    if code_bytes > MAX_CODE_BYTES:
        logger.info(
            "confuse reject: payload_too_large bytes=%d cid=%s", code_bytes, correlation_id,
        )
        body = _error(
            errcodes.PAYLOAD_TOO_LARGE,
            "request",
            f"code size {code_bytes} bytes exceeds 200KB limit",
        )
        return JSONResponse(status_code=413, content=body, headers={"Cache-Control": "no-store"})

    # --- 4 + 5. dispatch to worker -------------------------------------
    dispatcher = get_dispatcher()
    worker = None
    try:
        worker = await dispatcher.acquire(req.language_in)
    except RuntimeError as e:
        # unsupported language or pool timeout
        body = _error(
            errcodes.LANGUAGE_NOT_SUPPORTED,
            "request",
            str(e) or f"language {req.language_in} is not supported",
        )
        return JSONResponse(status_code=400, content=body, headers={"Cache-Control": "no-store"})

    # Build the params dict we hand to the Worker. The Worker expects the
    # SPEC §6.1 fields (language_in, language_out, preset, count,
    # overrides, code); we drop Pydantic-only stuff.
    worker_params = {
        "language_in": req.language_in,
        "language_out": req.language_out,
        "preset": req.preset,
        "count": req.count,
        "overrides": req.overrides.model_dump(exclude_none=True) if req.overrides else {},
        "code": req.code,
    }

    degraded = False
    try:
        try:
            result = await call_worker(worker, "confuse", worker_params, timeout=10.0)
        except WorkerTimeoutError as e:
            # call_worker already retried once with degraded overrides; if we
            # still get a timeout, surface it.
            logger.error(
                "worker confuse failed after degradation: lang=%s pid=%s err=%s",
                req.language_in, worker.pid, e,
            )
            body = _error(
                errcodes.INTERNAL_ERROR,
                "transform",
                f"obfuscation timed out for language {req.language_in}",
            )
            return JSONResponse(status_code=200, content=body, headers={"Cache-Control": "no-store"})
        except WorkerError as e:
            # Worker returned an error envelope (parse / transform / verify).
            logger.info(
                "worker confuse error: lang=%s pid=%s err=%s",
                req.language_in, worker.pid, e,
            )
            # Try to surface a useful message; do NOT leak stack traces.
            body = _error(
                errcodes.PARSE_ERROR,
                "parse",
                str(e) or "worker failed",
            )
            return JSONResponse(status_code=200, content=body, headers={"Cache-Control": "no-store"})

        # If worker_params was tagged during degradation, propagate that.
        degraded = bool(worker_params.get("__degraded__"))

        # --- 6. shape the response ------------------------------------
        return _shape_response(req, result, degraded=degraded, correlation_id=correlation_id, started=started)

    finally:
        if worker is not None:
            dispatcher.release(worker)


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------


def _shape_response(
    req: ConfuseRequest,
    result: Any,
    *,
    degraded: bool,
    correlation_id: str,
    started: float,
) -> JSONResponse:
    """Translate a Worker result dict into a ``ConfuseResponse`` JSON."""
    if not isinstance(result, dict):
        body = _error(
            errcodes.INTERNAL_ERROR,
            "transform",
            "worker returned a non-dict result",
        )
        return JSONResponse(status_code=200, content=body, headers={"Cache-Control": "no-store"})

    # Pass-through error envelope
    if result.get("status") == "error":
        body = ErrorResponse(
            status="error",
            code=result.get("code") or errcodes.INTERNAL_ERROR,
            stage=result.get("stage") or "transform",
            message=result.get("message") or "worker reported an error",
            errors=[ErrorItem(**e) for e in result.get("errors", []) if isinstance(e, dict)],
        ).model_dump()
        return JSONResponse(status_code=200, content=body, headers={"Cache-Control": "no-store"})

    # Success path
    applied = result.get("applied") or []
    verify = result.get("verify") or "syntax-ok"
    if degraded and verify == "compiled":
        # Surface that we had to drop aggressive strategies.
        verify = "warning"

    if req.count == 1:
        code_str = result.get("code") or ""
        payload = ConfuseResponse(
            status="ok",
            language_in=req.language_in,
            language_out=req.language_out,
            preset=req.preset,
            count=1,
            applied=applied,
            code=code_str,
            verify=verify,
        ).model_dump()
    else:
        results = result.get("results") or []
        failed_indexes = result.get("failed_indexes") or []
        zip_b64 = result.get("zip_b64")
        if zip_b64 is None and isinstance(results, list):
            zip_b64 = _build_zip_b64(results, req.language_in, failed_indexes)
        payload = ConfuseResponse(
            status="ok",
            language_in=req.language_in,
            language_out=req.language_out,
            preset=req.preset,
            count=req.count,
            applied=applied,
            code=results[0] if results else None,
            verify=verify,
            zip_b64=zip_b64,
            failed_indexes=failed_indexes,
        ).model_dump()

    elapsed_ms = int((time.monotonic() - started) * 1000)
    # SPEC §8.4: log only meta — never log code content.
    logger.info(
        "confuse ok lang=%s count=%d preset=%s bytes=%d verify=%s degraded=%s elapsed_ms=%d cid=%s",
        req.language_in,
        req.count,
        req.preset,
        len(req.code.encode("utf-8")),
        verify,
        degraded,
        elapsed_ms,
        correlation_id,
    )
    return JSONResponse(status_code=200, content=payload, headers={"Cache-Control": "no-store"})


def _build_zip_b64(results: list[Any], language: str, failed_indexes: list[int]) -> str:
    """Pack successful batch variants into a base64-encoded zip archive."""
    suffix = {
        "c": "c",
        "cpp": "cpp",
        "python": "py",
        "java": "java",
        "go": "go",
    }.get(language, "txt")
    failed = set(failed_indexes)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, code in enumerate(results, start=1):
            if idx in failed or not isinstance(code, str):
                continue
            zf.writestr(f"confused_{idx}.{suffix}", code)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# Pydantic-level validation handler — turns body errors into our envelope
# ---------------------------------------------------------------------------


async def _validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    body = _error(
        errcodes.INVALID_COUNT,  # generic "bad request" code
        "request",
        f"request body failed validation: {exc}" if isinstance(exc, ValidationError) else "bad request",
    )
    return JSONResponse(status_code=400, content=body, headers={"Cache-Control": "no-store"})


__all__ = ["router", "confuse", "_validation_exception_handler", "MAX_CODE_BYTES", "ALLOWED_COUNTS"]
