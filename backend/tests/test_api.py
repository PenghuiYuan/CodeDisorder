"""API + Worker integration tests.

These tests boot the FastAPI app and the Python Worker via stdio JSON-RPC.
Java/Go workers return ``language_not_supported`` per M1 spec.
"""

from __future__ import annotations

import asyncio
import base64
import io
import shutil
import zipfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def client():
    """Boot the app in import mode (no subprocess) so tests don't need venv paths."""
    import os
    os.environ["WORKER_MODE"] = "import"
    from backend.api.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Trigger startup manually (httpx ASGI doesn't fire lifespan)
        async with c.stream("GET", "/api/health") as r:
            await r.aread()
        yield c


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_presets_listing(client: AsyncClient):
    r = await client.get("/api/presets")
    assert r.status_code == 200
    data = r.json()
    assert "presets" in data
    assert any(p["id"] == "default" for p in data["presets"])


@pytest.mark.asyncio
async def test_python_round_trip(client: AsyncClient):
    src = (FIXTURES / "python_fib.py").read_text()
    r = await client.post(
        "/api/confuse",
        json={
            "language_in": "python",
            "language_out": "python",
            "preset": "default",
            "count": 1,
            "code": src,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["verify"] == "syntax-ok"
    assert "code" in body
    assert "rename" in body["applied"]


@pytest.mark.asyncio
async def test_python_batch_returns_zip_and_preview(client: AsyncClient):
    src = "def add(a, b):\n    return a + b\nprint(add(1, 2))\n"
    r = await client.post(
        "/api/confuse",
        json={
            "language_in": "python",
            "language_out": "python",
            "preset": "default",
            "count": 3,
            "code": src,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["count"] == 3
    assert body["code"]
    assert body["zip_b64"]

    raw = base64.b64decode(body["zip_b64"])
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = sorted(zf.namelist())
        assert names == ["confused_1.py", "confused_2.py", "confused_3.py"]


@pytest.mark.asyncio
async def test_cpp_round_trip(client: AsyncClient):
    if not shutil.which("g++"):
        pytest.skip("g++ not installed")
    if not (FIXTURES / "cpp_basic.cpp").exists():
        pytest.skip("fixture missing")
    src = (FIXTURES / "cpp_basic.cpp").read_text()
    r = await client.post(
        "/api/confuse",
        json={
            "language_in": "cpp",
            "language_out": "cpp",
            "preset": "default",
            "count": 1,
            "code": src,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["verify"] == "compiled"


@pytest.mark.asyncio
async def test_java_returns_language_not_supported(client: AsyncClient):
    r = await client.post(
        "/api/confuse",
        json={
            "language_in": "java",
            "language_out": "java",
            "preset": "default",
            "code": "class A {}",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert body["code"] == "language_not_supported"


@pytest.mark.asyncio
async def test_payload_too_large(client: AsyncClient):
    big = "x = 1\n" * (200 * 1024 // 4 + 100)  # ~205KB
    r = await client.post(
        "/api/confuse",
        json={
            "language_in": "python",
            "language_out": "python",
            "preset": "default",
            "code": big,
        },
    )
    assert r.status_code == 413
    body = r.json()
    assert body["code"] == "payload_too_large"


@pytest.mark.asyncio
async def test_invalid_count(client: AsyncClient):
    r = await client.post(
        "/api/confuse",
        json={
            "language_in": "python",
            "language_out": "python",
            "preset": "default",
            "count": 7,  # not in {1,3,5,10}
            "code": "x = 1",
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_mismatched_languages(client: AsyncClient):
    r = await client.post(
        "/api/confuse",
        json={
            "language_in": "python",
            "language_out": "cpp",
            "preset": "default",
            "code": "x = 1",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_target_language"


@pytest.mark.asyncio
async def test_cache_control_header(client: AsyncClient):
    r = await client.get("/api/health")
    assert r.headers.get("cache-control") == "no-store"
