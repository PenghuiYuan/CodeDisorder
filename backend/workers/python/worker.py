"""Python Worker entry point.

Run as: ``python -m backend.workers.python.worker``

Speaks JSON-RPC 2.0 over stdio (DESIGN §3.3).
"""

from __future__ import annotations

import sys

from backend.workers.common.jsonrpc import serve
from backend.workers.python.transformer import ConfuseTransformer


def main() -> int:
    transformer = ConfuseTransformer()

    def ping(_: dict) -> dict:
        return {"ok": True, "language": "python"}

    def confuse(params: dict) -> dict:
        return transformer.handle(params)

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
