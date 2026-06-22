"""Worker process pool manager (DESIGN §3.5).

Two operating modes (selected by the ``WORKER_MODE`` env var):

* ``stdio`` (default) — spawn one subprocess per language, talk JSON-RPC over
  stdio.  One process per language in M1 (DESIGN §3.5).
* ``import`` — for development: import ``backend.workers.<lang>.transformer``
  in-process and call its ``handle()`` directly. No subprocess, no real
  isolation, but no startup cost and easier debugging.

All ``acquire``/``release`` operations are serialised by an ``asyncio.Lock``
so concurrent requests don't race for the same Worker.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.workers.common.jsonrpc import JSONRPCClient, make_subprocess

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker handle
# ---------------------------------------------------------------------------


@dataclass
class WorkerHandle:
    """A live or in-process Worker.

    In ``stdio`` mode ``process`` and ``client`` are populated. In ``import``
    mode ``process`` is None and ``transformer`` holds the imported class
    instance.
    """

    pid: int
    language: str
    process: Optional[asyncio.subprocess.Process] = None
    busy: bool = False
    last_used: float = field(default_factory=time.monotonic)
    client: Optional[JSONRPCClient] = None
    # import-mode only
    transformer: Any = None
    # True if this handle should be killed when idle (stdio mode)
    ephemeral: bool = True


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------


#: Languages supported in M1. Extend when M2 lands Java / Go.
SUPPORTED_LANGUAGES = ("c", "cpp", "python", "java", "go")

#: Subprocess command template for stdio mode.
WORKER_CMD_TEMPLATE = [sys.executable, "-m", "backend.workers.{language}.worker"]

# Map a public language code (what the API sees) to the actual Worker module
# directory. C and C++ share one Worker (PyClang handles both).
LANGUAGE_MODULE_MAP = {
    "c": "c_cpp",
    "cpp": "c_cpp",
    "python": "python",
    "java": "java",
    "go": "go",
}


def _module_name(language: str) -> str:
    return LANGUAGE_MODULE_MAP.get(language, language)

#: How long an idle Worker may live before being killed.
IDLE_TIMEOUT_SECONDS = 60.0

#: Poll interval when waiting for a free Worker (M1 has 1 per language).
WAIT_INTERVAL_SECONDS = 0.1

#: Acquire timeout (give up if a Worker doesn't free up in this window).
ACQUIRE_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class Dispatcher:
    """Manages a small pool of Worker processes, one per language.

    Lifecycle:

    1. ``acquire(lang)`` returns a free ``WorkerHandle`` (or spawns one /
       blocks until one is free).
    2. The caller does work and calls ``release(handle)`` to return it.
    3. On ``release`` we mark it free, update ``last_used``, and schedule a
       background cleanup that kills the subprocess if it stays idle for
       ``IDLE_TIMEOUT_SECONDS``.
    """

    def __init__(self) -> None:
        self._pools: dict[str, list[WorkerHandle]] = {lang: [] for lang in SUPPORTED_LANGUAGES}
        # One lock per language so requests for different languages never
        # serialise on each other.
        self._locks: dict[str, asyncio.Lock] = {
            lang: asyncio.Lock() for lang in SUPPORTED_LANGUAGES
        }
        # Waiters blocked on a busy Worker (per language).
        self._waiters: dict[str, list[asyncio.Future]] = {lang: [] for lang in SUPPORTED_LANGUAGES}
        self._mode = os.environ.get("WORKER_MODE", "stdio").lower()
        if self._mode not in ("stdio", "import"):
            logger.warning("Unknown WORKER_MODE=%r, falling back to 'stdio'", self._mode)
            self._mode = "stdio"

    # ------------------------------------------------------------------ public

    @property
    def mode(self) -> str:
        return self._mode

    async def acquire(self, language: str, *, timeout: float = ACQUIRE_TIMEOUT_SECONDS) -> WorkerHandle:
        """Return a free ``WorkerHandle`` for ``language``, spawning if needed.

        Raises ``RuntimeError`` on unsupported language or timeout.
        """
        if language not in self._pools:
            raise RuntimeError(f"unsupported language: {language}")

        lock = self._locks[language]
        deadline = time.monotonic() + timeout
        held = False
        await lock.acquire()
        held = True
        try:
            pool = self._pools[language]
            # 1. try to grab an idle one
            for h in pool:
                if not h.busy and self._is_alive(h):
                    h.busy = True
                    h.last_used = time.monotonic()
                    return h
            # 2. spawn a new one (M1 allows 1 per language)
            if len(pool) < 1:
                handle = await self._spawn(language)
                pool.append(handle)
                handle.busy = True
                return handle
            # 3. M1 pool full (1) → wait for release()
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise RuntimeError(f"timeout waiting for {language} worker")
                # Drop the lock so release() can run; the waiter signals
                # us via a Future and we'll re-acquire below.
                lock.release()
                held = False
                try:
                    await asyncio.wait_for(
                        self._wait_for_free(language),
                        timeout=min(WAIT_INTERVAL_SECONDS, deadline - now),
                    )
                except asyncio.TimeoutError:
                    pass
                await lock.acquire()
                held = True
                # re-scan
                for h in pool:
                    if not h.busy and self._is_alive(h):
                        h.busy = True
                        h.last_used = time.monotonic()
                        return h
        finally:
            if held:
                lock.release()

    def release(self, handle: WorkerHandle) -> None:
        """Return a Worker to the pool and schedule idle cleanup if needed."""
        handle.busy = False
        handle.last_used = time.monotonic()
        # wake one waiter
        for fut in self._waiters.get(handle.language, []):
            if not fut.done():
                fut.set_result(True)
                break
        # schedule cleanup (only meaningful for stdio mode with real procs)
        if handle.process is not None and handle.ephemeral:
            asyncio.create_task(self._cleanup_if_idle(handle))

    async def shutdown(self) -> None:
        """Kill all Workers. Called on API shutdown."""
        for lang, pool in self._pools.items():
            for h in pool:
                await self._kill(h)
            pool.clear()

    # ------------------------------------------------------------------ helpers

    def _is_alive(self, handle: WorkerHandle) -> bool:
        if handle.process is not None:
            return handle.process.returncode is None
        # import-mode handles are always alive
        return handle.transformer is not None

    async def _wait_for_free(self, language: str) -> None:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._waiters[language].append(fut)
        try:
            await fut
        finally:
            try:
                self._waiters[language].remove(fut)
            except ValueError:
                pass

    async def _spawn(self, language: str) -> WorkerHandle:
        if self._mode == "import":
            return await self._spawn_import(language)
        return await self._spawn_stdio(language)

    async def _spawn_stdio(self, language: str) -> WorkerHandle:
        mod_dir = _module_name(language)
        cmd = [part.format(language=mod_dir) for part in WORKER_CMD_TEMPLATE]
        logger.info("spawning worker: %s", " ".join(cmd))
        proc = await make_subprocess(cmd)
        # JSONRPCClient takes ownership of the read loop.
        client = JSONRPCClient(proc)
        handle = WorkerHandle(
            pid=proc.pid or 0,
            language=language,
            process=proc,
            busy=False,
            client=client,
            ephemeral=True,
        )
        # Stderr drain: don't read line by line (would block the loop), but
        # at least don't let stderr fill the pipe and deadlock the Worker.
        asyncio.create_task(self._drain_stderr(proc, language))
        return handle

    async def _spawn_import(self, language: str) -> WorkerHandle:
        mod_name = f"backend.workers.{_module_name(language)}.transformer"
        logger.info("loading worker in-process: %s", mod_name)
        mod = importlib.import_module(mod_name)
        transformer = mod.ConfuseTransformer()
        return WorkerHandle(
            pid=os.getpid(),
            language=language,
            process=None,
            busy=False,
            client=None,
            transformer=transformer,
            ephemeral=False,
        )

    @staticmethod
    async def _drain_stderr(proc: asyncio.subprocess.Process, language: str) -> None:
        """Forward Worker stderr lines to the API logger.

        We never block on a full pipe and never propagate the data to the
        HTTP response.
        """
        try:
            while True:
                raw = await proc.stderr.readline()
                if not raw:
                    return
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    logger.warning("worker[%s pid=%s] stderr: %s", language, proc.pid, line)
        except Exception:  # noqa: BLE001
            return

    async def _cleanup_if_idle(self, handle: WorkerHandle) -> None:
        """Kill ``handle`` if it has been idle for ``IDLE_TIMEOUT_SECONDS``."""
        try:
            while True:
                await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
                if handle.busy:
                    continue
                if (time.monotonic() - handle.last_used) < IDLE_TIMEOUT_SECONDS:
                    continue
                # Still free and idle past the threshold → kill.
                logger.info("killing idle worker pid=%s lang=%s", handle.pid, handle.language)
                await self._kill(handle)
                # remove from pool so the next acquire() spawns a fresh one
                pool = self._pools.get(handle.language, [])
                if handle in pool:
                    pool.remove(handle)
                return
        except asyncio.CancelledError:
            return

    async def _kill(self, handle: WorkerHandle) -> None:
        if handle.client is not None:
            try:
                await handle.client.shutdown(timeout=1.0)
            except Exception:  # noqa: BLE001
                pass
        if handle.process is not None and handle.process.returncode is None:
            try:
                handle.process.terminate()
                await asyncio.wait_for(handle.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                handle.process.kill()
                await handle.process.wait()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


_dispatcher: Optional[Dispatcher] = None


def get_dispatcher() -> Dispatcher:
    """Return the process-wide ``Dispatcher`` (created lazily on first call)."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
    return _dispatcher
