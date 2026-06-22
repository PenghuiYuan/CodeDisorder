"""Thin wrapper that calls a Worker (stdio or in-process) and handles the
single-shot timeout-degradation rule from DESIGN §3.2 step 5.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.api.dispatcher import WorkerHandle
from backend.workers.common.jsonrpc import WorkerError, WorkerTimeoutError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults (mirrors DESIGN §3.2)
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT_SECONDS = 10.0
DEGRADED_TIMEOUT_SECONDS = 5.0


def _strip_aggressive(params: dict) -> dict:
    """Return a copy of ``params`` with aggressive strategies disabled.

    This is the "drop flatten/junk" degradation referenced in
    DESIGN §3.2 step 5. We only touch the ``overrides`` layer so the
    Worker keeps the preset's safer defaults.
    """
    out = dict(params)
    overrides = dict(out.get("overrides") or {})
    # flatten can be bool or "off"/"simple"/"deep"
    if overrides.get("flatten") not in (None, False, "off"):
        overrides["flatten"] = "off"
    # junk can be bool or "off"/"aggressive"
    if overrides.get("junk") not in (None, False, "off"):
        overrides["junk"] = "off"
    out["overrides"] = overrides
    return out


async def call_worker(
    handle: WorkerHandle,
    method: str,
    params: dict,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Invoke ``method`` on the Worker bound to ``handle``.

    * In stdio mode the call goes through ``JSONRPCClient.call``.
    * In import mode we invoke ``handle.transformer.handle(params)`` directly
      (no async framing — Workers are sync).

    On ``WorkerTimeoutError`` we retry exactly once with aggressive strategies
    removed (DESIGN §3.2 step 5). Any other ``WorkerError`` propagates so the
    caller can translate it into an HTTP response.
    """
    degraded = False
    try:
        return await _do_call(handle, method, params, timeout=timeout)
    except WorkerTimeoutError as e:
        logger.warning(
            "worker call %s timed out (lang=%s, pid=%s) — degrading",
            method,
            handle.language,
            handle.pid,
        )
        degraded = True
        degraded_params = _strip_aggressive(params)
        try:
            return await _do_call(handle, method, degraded_params, timeout=DEGRADED_TIMEOUT_SECONDS)
        finally:
            # Tag params so callers can know degradation happened; the route
            # only uses this for logging.
            params["__degraded__"] = degraded


async def _do_call(handle: WorkerHandle, method: str, params: dict, *, timeout: float) -> Any:
    if handle.transformer is not None:
        # import mode — synchronous handler executed directly.
        # The "timeout" is best-effort: we run on the loop via to_thread so
        # a hang in the handler doesn't block the API.
        import asyncio
        result = await asyncio.get_running_loop().run_in_executor(
            None, handle.transformer.handle, params,
        )
        # Pass through; the route handler (routes_confuse._shape_response)
        # knows how to surface dict-shaped {status: error, ...} responses.
        return result

    if handle.client is None:
        raise WorkerError(f"worker handle for {handle.language} has no client")
    return await handle.client.call(method, params, timeout=timeout)


__all__ = [
    "call_worker",
    "WorkerError",
    "WorkerTimeoutError",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEGRADED_TIMEOUT_SECONDS",
]
