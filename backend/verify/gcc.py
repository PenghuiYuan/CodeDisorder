"""gcc / g++ syntax-only verification (DESIGN §9.1).

Returns ``{status, level, errors}`` with line/column parsed from stderr. Uses
``tempfile.NamedTemporaryFile(delete=False)`` so we can compile a path-based
tool; unlinked in ``finally``.

Note: ``-fsyntax-only`` skips codegen and linking, so the subprocess finishes
fast even on big files. We do *not* run the executable — SPEC §3.5 / §5.3
makes it explicit that we never run user code.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional


@dataclass
class VerifyResult:
    status: str            # "ok" | "error"
    level: str             # "compiled" | "warning" | "syntax-err" | "verify" | "timeout"
    errors: list[dict]     # [{line, column, message}]

    def to_dict(self) -> dict:
        return {"status": self.status, "level": self.level, "errors": self.errors}


# gcc / clang line:col: message   e.g.  src.c:12:5: error: ...
_ERR_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?:\w+):\s*(?P<msg>.*)$"
)


def _parse_stderr(stderr: str) -> list[dict]:
    out: list[dict] = []
    for line in stderr.splitlines():
        m = _ERR_RE.match(line.strip())
        if m:
            out.append(
                {
                    "line": int(m["line"]),
                    "column": int(m["col"]),
                    "message": m["msg"].strip(),
                }
            )
    # If the regex didn't match anything but we have stderr, surface the first
    # 5 lines as a single error so the user isn't left staring at a blank page.
    if not out and stderr.strip():
        for chunk in stderr.strip().splitlines()[:5]:
            out.append({"line": 0, "column": 0, "message": chunk.strip()})
    return out


def verify_cpp(code: str, *, language: str = "cpp", timeout: float = 5.0) -> VerifyResult:
    """Run gcc/clang -fsyntax-only on ``code`` (M1 spec: don't link, don't run).

    Tries gcc first, then clang; if both unavailable returns a clear error.
    """
    if language == "cpp":
        compilers: list[list[str]] = [
            ["g++", "-std=c++17", "-fsyntax-only", "-w"],
            ["clang++", "-std=c++17", "-fsyntax-only", "-w"],
        ]
        suffix = ".cpp"
    elif language == "c":
        compilers = [
            ["gcc", "-std=c11", "-fsyntax-only", "-w"],
            ["clang", "-std=c11", "-fsyntax-only", "-w"],
        ]
        suffix = ".c"
    else:
        return VerifyResult("error", "verify", [
            {"line": 0, "column": 0, "message": f"unsupported language: {language}"}
        ])

    fd, path = tempfile.mkstemp(suffix=suffix, prefix="cf_verify_", dir="/tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)

        for prefix in compilers:
            cmd = prefix + [path]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout
                )
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                return VerifyResult("error", "timeout", [
                    {"line": 0, "column": 0, "message": f"{prefix[0]} timeout after {timeout}s"}
                ])
            if proc.returncode == 0:
                return VerifyResult("ok", "compiled", [])
            return VerifyResult("error", "verify", _parse_stderr(proc.stderr))

        return VerifyResult("error", "verify", [
            {"line": 0, "column": 0, "message": "no compiler (gcc/g++ or clang/clang++) found"}
        ])
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
