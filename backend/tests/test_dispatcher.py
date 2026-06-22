"""Dispatcher / Worker client tests (without spinning up full app)."""

from __future__ import annotations

import asyncio
import sys
import os
from pathlib import Path

import pytest

from backend.workers.common.jsonrpc import JSONRPCClient, WorkerError, make_subprocess


@pytest.mark.asyncio
async def test_python_worker_ping():
    """Round-trip: spawn Python worker, ping it, shut down."""
    cmd = [sys.executable, "-m", "backend.workers.python.worker"]
    proc = await make_subprocess(cmd)
    client = JSONRPCClient(proc)
    try:
        result = await client.call("ping", {}, timeout=3.0)
        assert result == {"ok": True, "language": "python"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_python_worker_confuse():
    cmd = [sys.executable, "-m", "backend.workers.python.worker"]
    proc = await make_subprocess(cmd)
    client = JSONRPCClient(proc)
    try:
        result = await client.call(
            "confuse",
            {"language_in": "python", "preset": "default", "count": 1,
             "code": "def add(a, b):\n    return a + b\n"},
            timeout=5.0,
        )
        assert result["status"] == "ok"
        assert "rename" in result["applied"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_java_worker_returns_language_not_supported():
    """Java worker is M1 stub: confuse() returns a normal JSON-RPC success
    whose ``result`` carries ``{status: error, code: language_not_supported}``."""
    cmd = [sys.executable, "-m", "backend.workers.java.worker"]
    proc = await make_subprocess(cmd)
    client = JSONRPCClient(proc)
    try:
        result = await client.call("confuse", {"code": "class A {}"}, timeout=3.0)
        assert result["status"] == "error"
        assert result["code"] == "language_not_supported"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_method_not_found_returns_error():
    cmd = [sys.executable, "-m", "backend.workers.python.worker"]
    proc = await make_subprocess(cmd)
    client = JSONRPCClient(proc)
    try:
        with pytest.raises(WorkerError):
            await client.call("nonexistent_method", {}, timeout=3.0)
    finally:
        await client.close()
