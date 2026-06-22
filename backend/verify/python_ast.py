"""Python ast.parse verification (DESIGN §5.4)."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class VerifyResult:
    status: str
    level: str
    errors: list[dict]

    def to_dict(self) -> dict:
        return {"status": self.status, "level": self.level, "errors": self.errors}


def verify_python(code: str) -> VerifyResult:
    try:
        ast.parse(code)
    except SyntaxError as e:
        return VerifyResult("error", "syntax-err", [
            {"line": e.lineno or 0, "column": e.offset or 0, "message": e.msg or ""}
        ])
    return VerifyResult("ok", "syntax-ok", [])
