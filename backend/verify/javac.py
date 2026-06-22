"""javac verification — M2 stub, but the wrapper is here so SPEC §6 schemas
can import it.

DESIGN §6.1 / §9.1: ``javac -proc:none``. We don't link, don't run.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass
class VerifyResult:
    status: str
    level: str
    errors: list[dict]

    def to_dict(self) -> dict:
        return {"status": self.status, "level": self.level, "errors": self.errors}


def verify_java(code: str, *, timeout: float = 5.0) -> VerifyResult:
    fd, path = tempfile.mkstemp(suffix=".java", prefix="cf_verify_", dir="/tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            proc = subprocess.run(
                ["javac", "-proc:none", "-Xlint:none", path],
                capture_output=True, text=True, timeout=timeout,
            )
        except FileNotFoundError:
            return VerifyResult("error", "verify", [
                {"line": 0, "column": 0, "message": "javac not installed"}
            ])
        except subprocess.TimeoutExpired:
            return VerifyResult("error", "timeout", [
                {"line": 0, "column": 0, "message": f"javac timeout after {timeout}s"}
            ])
        if proc.returncode == 0:
            return VerifyResult("ok", "compiled", [])
        return VerifyResult("error", "verify", [
            {"line": 0, "column": 0, "message": line}
            for line in proc.stderr.splitlines()[:10]
        ])
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        # javac leaves a .class beside the source
        cls = path[:-5] + ".class"
        try:
            os.unlink(cls)
        except FileNotFoundError:
            pass
