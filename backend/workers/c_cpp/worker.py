"""C / C++ Worker entry point.

Run as: ``python -m backend.workers.c_cpp.worker``
"""

from __future__ import annotations

from backend.workers.common.jsonrpc import serve
from backend.workers.c_cpp.transformer import ConfuseTransformer


def main() -> int:
    transformer = ConfuseTransformer()

    def ping(_: dict) -> dict:
        return {"ok": True, "language": "c_cpp"}

    def confuse(params: dict) -> dict:
        return transformer.handle(params)

    def shutdown(_: dict) -> dict:
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
