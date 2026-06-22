"""Java Worker transformer — M1 stub.

M2 will replace this with JavaParser / Eclipse JDT-backed AST transforms.
M1 just returns ``language_not_supported`` so the API surface is testable.
"""

from __future__ import annotations

from typing import Any


class ConfuseTransformer:
    def __init__(self):
        pass

    def handle(self, params: dict) -> dict:
        return {
            "status": "error",
            "code": "language_not_supported",
            "stage": "transform",
            "message": "Java 混淆将在 M2 上线(JavaParser CLI / Eclipse JDT)",
        }
