"""Line-delimited JSON-RPC 2.0 over stdio.

DESIGN §3.3.

- Worker side: ``serve(handlers)`` blocks reading stdin, dispatches ``method`` → handler,
  writes ``result``/``error`` JSON-RPC responses to stdout. Notifications (``id`` absent)
  are dropped silently (MVP doesn't use them).
- API side: :class:`JSONRPCClient` wraps an :class:`asyncio.subprocess.Process`, sends
  requests with monotonically increasing ids, awaits matching responses with a timeout.

The protocol is symmetric: both sides share the same wire format. Errors carry a
``code`` (JSON-RPC standard codes, or our own ints ≥ -32000) plus a human ``message``;
non-standard payloads (parse error, transform error) ride inside ``data``.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

# JSON-RPC 2.0 standard error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Application error codes (≥ -32000 per spec)
APP_ERROR = -32000  # generic transform / runtime error


Handler = Callable[[dict], Any]


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------


def _write_obj(obj: dict) -> None:
    """Write one JSON object as a single line, flushed. Used by Worker stdout."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _make_response(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def serve(handlers: dict[str, Handler]) -> None:
    """Block on stdin reading JSON-RPC requests, dispatch, write responses.

    Intended entry point: ``python -m backend.workers.python.worker`` calls ``serve({...})``
    with a method→handler map. Handlers may be sync or async (we always ``await`` the
    return value when it's awaitable). Exceptions inside a handler become an
    ``INTERNAL_ERROR`` JSON-RPC response so a buggy strategy never kills the Worker.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _write_obj(_make_error(None, PARSE_ERROR, f"parse error: {e}"))
            continue

        if not isinstance(req, dict) or req.get("jsonrpc") != "2.0":
            _write_obj(_make_error(None, INVALID_REQUEST, "invalid jsonrpc envelope"))
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        # Notification (no id): MVP drops them. SPEC §3.3 notes progress notifications
        # could be added later; we don't need them yet.
        if req_id is None:
            continue

        if not isinstance(method, str) or method not in handlers:
            _write_obj(_make_error(req_id, METHOD_NOT_FOUND, f"method not found: {method}"))
            continue

        handler = handlers[method]
        try:
            result = handler(params)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
        except SystemExit:
            # ``shutdown`` handler raises SystemExit to break out cleanly.
            _write_obj(_make_response(req_id, {"ok": True}))
            raise
        except Exception as e:  # noqa: BLE001 — broad: we *want* to absorb anything
            _write_obj(
                _make_error(
                    req_id,
                    INTERNAL_ERROR,
                    f"{type(e).__name__}: {e}",
                    data={"type": type(e).__name__},
                )
            )
            continue

        _write_obj(_make_response(req_id, result))


# ---------------------------------------------------------------------------
# API side
# ---------------------------------------------------------------------------


@dataclass
class _Pending:
    event: asyncio.Event = field(default_factory=asyncio.Event)
    response: Optional[dict] = None


class WorkerError(RuntimeError):
    """Raised when a Worker call returns a JSON-RPC error or times out."""


class WorkerTimeoutError(WorkerError):
    """Subclass for timeout, so callers can degrade (DESIGN §3.2 step 5)."""


class JSONRPCClient:
    """Async client wrapping one Worker subprocess.

    One instance per process. The Dispatcher (DESIGN §3.5) holds a pool of these.
    Concurrency: ``call()`` is safe to await from multiple coroutines on the same
    client; the read loop and pending-requests map are protected by a single lock.
    """

    def __init__(self, process: asyncio.subprocess.Process):
        self.proc = process
        self._next_id = 0
        self._pending: dict[int, _Pending] = {}
        self._lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(self._read_loop())

    @property
    def pid(self) -> int:
        return self.proc.pid

    async def call(
        self,
        method: str,
        params: dict,
        *,
        timeout: float = 10.0,
    ) -> Any:
        async with self._lock:
            self._next_id += 1
            req_id = self._next_id
            pending = _Pending()
            self._pending[req_id] = pending
        envelope = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        line = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            self.proc.stdin.write(line.encode("utf-8"))
            await self.proc.stdin.drain()
        except (ConnectionResetError, BrokenPipeError) as e:
            self._pending.pop(req_id, None)
            raise WorkerError(f"worker stdin closed: {e}") from e

        try:
            await asyncio.wait_for(pending.event.wait(), timeout=timeout)
        except asyncio.TimeoutError as e:
            self._pending.pop(req_id, None)
            raise WorkerTimeoutError(f"call {method} timed out after {timeout}s") from e

        resp = pending.response
        assert resp is not None
        if "error" in resp:
            err = resp["error"]
            raise WorkerError(f"{err.get('code')}: {err.get('message')}")
        return resp.get("result")

    async def notify(self, method: str, params: dict) -> None:
        """Fire-and-forget notification (no id)."""
        envelope = {"jsonrpc": "2.0", "method": method, "params": params}
        line = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()

    async def shutdown(self, timeout: float = 2.0) -> None:
        try:
            await self.call("shutdown", {}, timeout=timeout)
        except (WorkerError, asyncio.TimeoutError):
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        self._reader_task.cancel()
        try:
            await self._reader_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
        if self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()

    async def _read_loop(self) -> None:
        """Read stdout line-by-line, dispatch matching responses to pending waiters."""
        try:
            while True:
                raw = await self.proc.stdout.readline()
                if not raw:
                    # EOF: Worker died. Fail all in-flight requests.
                    for pending in self._pending.values():
                        pending.response = {
                            "error": {"code": INTERNAL_ERROR, "message": "worker exited"}
                        }
                        pending.event.set()
                    self._pending.clear()
                    return
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if not isinstance(msg, dict):
                    continue
                req_id = msg.get("id")
                if not isinstance(req_id, int):
                    continue  # notification or malformed
                pending = self._pending.pop(req_id, None)
                if pending is None:
                    continue  # late response after timeout
                pending.response = msg
                pending.event.set()
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            return


def make_subprocess(
    cmd: list[str], *, env: Optional[dict] = None
) -> asyncio.subprocess.Process:
    """Spawn a Worker subprocess. Convenience wrapper so the Dispatcher has one call site."""
    return asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )


def correlation_id() -> str:
    """Generate a request correlation id (UUID4 hex). Used in API logs."""
    return uuid.uuid4().hex
