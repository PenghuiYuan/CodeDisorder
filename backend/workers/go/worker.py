"""Go Worker entry point.

Run as: ``python -m backend.workers.go.worker``

Speaks JSON-RPC 2.0 over stdio (DESIGN §3.3).
"""

from __future__ import annotations

import sys

from backend.workers.common.jsonrpc import serve


def main() -> int:
    def ping(_: dict) -> dict:
        return {"ok": True, "language": "go"}

    def confuse(params: dict) -> dict:
        # M1: Go混淆将在M2实现(go ast tool)
        return {
            "status": "error",
            "code": "language_not_supported",
            "stage": "transform",
            "message": "Go 混淆将在 M2 上线(go ast tool)"
        }

    def shutdown(_: dict) -> dict:
        # Raising SystemExit breaks out of serve()'s stdin loop.
        raise SystemExit(0)

    serve(
        handlers={
            "ping": ping,
            "confuse": confuse,
            "shutdown": shutdown,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
