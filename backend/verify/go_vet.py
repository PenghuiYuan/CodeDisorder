"""go vet verification — M2 stub.

DESIGN §6.2 / §9.1: ``go vet`` for static checks. We don't compile to a binary.
"""

from __future__ import annotations

import os
import shutil
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


def verify_go(code: str, *, timeout: float = 5.0) -> VerifyResult:
    if not shutil.which("go"):
        return VerifyResult("error", "verify", [
            {"line": 0, "column": 0, "message": "go toolchain not installed"}
        ])
    d = tempfile.mkdtemp(prefix="cf_verify_go_", dir="/tmp")
    src = os.path.join(d, "main.go")
    try:
        with open(src, "w", encoding="utf-8") as f:
            # go vet requires at least a package declaration; if user didn't
            # supply one, wrap the code in a stub package.
            if "package " not in code:
                f.write("package main\n\n")
            f.write(code)
        try:
            proc = subprocess.run(
                ["go", "vet", d], capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return VerifyResult("error", "timeout", [
                {"line": 0, "column": 0, "message": f"go vet timeout after {timeout}s"}
            ])
        if proc.returncode == 0:
            return VerifyResult("ok", "compiled", [])
        return VerifyResult("error", "verify", [
            {"line": 0, "column": 0, "message": line}
            for line in (proc.stderr or proc.stdout).splitlines()[:10]
        ])
    finally:
        shutil.rmtree(d, ignore_errors=True)
