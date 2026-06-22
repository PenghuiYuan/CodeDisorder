"""C / C++ Worker transformer (DESIGN §4).

M1 scope: S1 (rename user-defined identifiers), S8 (strip comments via preclean),
S9 (shuffle include directives).

Implementation notes:
- We use libclang's ``CursorKind`` to identify user-defined decls and avoid
  touching system symbols. ``Cursor.location.file.name == input_path`` is the
  M1 heuristic for "user symbol" (DESIGN §4.4).
- PyClang's ``Rewriter`` API is incomplete; we instead walk all Cursors,
  collect a ``[(orig_offset, length, new_text)]`` list of edits, then sort by
  descending offset and splice into the original source string. This is
  DESIGN §4.5's "Token + offset splice" fallback.
- libclang on macOS needs ``Config.set_library_file`` pointed at
  ``/opt/homebrew/opt/llvm/lib/libclang.dylib``; we set it lazily here so the
  rest of the code doesn't have to know.
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import clang.cindex
from clang.cindex import CursorKind

from backend.workers.common.lexer import preclean
from backend.workers.common.seed import seed_for
from backend.workers.common.wordlist import WordList, default_wordlist

# Lazy libclang configuration. PyClang defaults to a ctypes.find_library lookup
# that often returns None on macOS. We point it at Homebrew llvm's dylib if
# the user hasn't already set it. ``LIBCLANG_LIBRARY_PATH`` env var overrides.
_DEFAULT_LIBCLANG = "/opt/homebrew/opt/llvm/lib/libclang.dylib"
_FORCED_RESERVED_SYMBOLS = {
    "main",
    "operator",
}
_INT_LITERAL_RE = re.compile(
    r"(?<![\w.])(?P<value>(?:0|[1-9][0-9]*))(?P<suffix>[uUlL]{0,4})(?![\w.])"
)


def _ensure_libclang() -> None:
    if clang.cindex.Config.library_file:
        return
    env = os.environ.get("LIBCLANG_LIBRARY_PATH")
    if env and Path(env).exists():
        clang.cindex.Config.set_library_file(env)
        return
    if Path(_DEFAULT_LIBCLANG).exists():
        clang.cindex.Config.set_library_file(_DEFAULT_LIBCLANG)


def _detect_sysroot() -> Optional[str]:
    """Return the active macOS SDK path (Xcode CLT or full Xcode)."""
    try:
        out = subprocess.run(
            ["xcrun", "--show-sdk-path", "--sdk", "macosx"],
            capture_output=True, text=True, timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _detect_resource_dir() -> Optional[str]:
    """Return clang's resource dir so libclang can find builtin headers."""
    env = os.environ.get("LIBCLANG_RESOURCE_DIR")
    if env and (Path(env) / "include" / "stdarg.h").exists():
        return env

    for clang_bin in (
        "/opt/homebrew/opt/llvm/bin/clang",
        "clang",
    ):
        try:
            out = subprocess.run(
                [clang_bin, "-print-resource-dir"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        resource_dir = out.stdout.strip()
        if out.returncode == 0 and (Path(resource_dir) / "include" / "stdarg.h").exists():
            return resource_dir

    candidates = [
        "/opt/homebrew/opt/llvm/lib/clang",
        "/Library/Developer/CommandLineTools/usr/lib/clang",
    ]
    for base in candidates:
        base_path = Path(base)
        if not base_path.exists():
            continue
        versions = sorted(base_path.iterdir(), key=lambda p: p.name, reverse=True)
        for version_dir in versions:
            if (version_dir / "include" / "stdarg.h").exists():
                return str(version_dir)
    return None


@dataclass
class _Edit:
    start: int   # byte offset in cleaned source
    length: int  # bytes to replace
    new_text: str  # replacement

    def __lt__(self, other: "_Edit") -> bool:
        # Sort by *descending* start offset, so applying right-to-left keeps
        # earlier offsets stable. Caller is expected to do the reverse.
        return self.start > other.start


class ConfuseError(Exception):
    def __init__(self, code: str, stage: str, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.errors = errors or []


class ConfuseTransformer:
    def __init__(self, wordlist: WordList | None = None):
        self.wordlist = wordlist or default_wordlist()
        self._settings_cache: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    def handle(self, params: dict) -> dict:
        try:
            return self._handle(params)
        except ConfuseError as e:
            return self._err(e.code, e.stage, e.message, e.errors)
        except Exception as e:  # noqa: BLE001 — last-resort safety net
            return self._err("internal_error", "transform", f"{type(e).__name__}: {e}")

    def _handle(self, params: dict) -> dict:
        _ensure_libclang()
        code = params.get("code", "")
        language = params.get("language_in")
        if language not in ("c", "cpp"):
            return self._err(
                "invalid_target_language", "parse", f"language_in must be 'c' or 'cpp', got {language!r}"
            )

        preset_id = params.get("preset", "default")
        count = int(params.get("count", 1))
        overrides = params.get("overrides") or {}

        # S8: preclean comments before parse (preserves newlines)
        try:
            clean = preclean(code, language=language)
        except Exception as e:  # noqa: BLE001
            return self._err("preclean_error", "preclean", str(e))

        # Parse via libclang. We feed the source via unsaved_files so no temp
        # file is created (SPEC §7.1: don't write user code to disk).
        ext = "cpp" if language == "cpp" else "c"
        std = "-std=c++17" if language == "cpp" else "-std=c11"
        # macOS: clang needs an explicit -isysroot to find system headers
        # (Xcode SDK). On Linux this is a no-op.
        sysroot = os.environ.get("LIBCLANG_SYSROOT") or _detect_sysroot()
        resource_dir = _detect_resource_dir()
        args = [std, "-fsyntax-only", "-w", "-fparse-all-comments"]
        if sysroot:
            args.extend(["-isysroot", sysroot])
        if resource_dir:
            args.extend(["-resource-dir", resource_dir])
        idx = clang.cindex.Index.create()
        virtual_path = f"input.{ext}"
        try:
            tu = idx.parse(
                virtual_path,
                unsaved_files=[(virtual_path, clean)],
                args=args,
                options=clang.cindex.TranslationUnit.PARSE_INCOMPLETE
                | clang.cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
            )
        except Exception as e:  # noqa: BLE001
            return self._err("parse_error", "parse", f"libclang crashed: {e}")

        errors: list[dict] = []
        for d in tu.diagnostics:
            if d.severity >= clang.cindex.Diagnostic.Error:
                errors.append(
                    {
                        "line": d.location.line or 0,
                        "column": d.location.column or 0,
                        "message": d.spelling,
                    }
                )
        if errors:
            return self._err("parse_error", "parse", "syntax errors in source", errors)

        strategies = _select_strategies(preset_id, overrides)
        settings = self._load_settings(language)
        reserved = set(settings.get("reserved", []))

        results: list[str] = []
        applied: list[str] = []

        for i in range(count):
            seed = seed_for(clean, preset_id, i)
            rng = random.Random(seed)
            new_code = self._transform(clean, tu, virtual_path, strategies, reserved, rng)
            results.append(new_code)
            applied = _collect_applied(strategies)

        # Verify via gcc/clang subprocess (DESIGN §9.1)
        from backend.verify.gcc import verify_cpp
        ok_idx: list[int] = []
        failed: list[int] = []
        for idx_r, r in enumerate(results, start=1):
            v = verify_cpp(r, language=language)
            if v.status == "ok":
                ok_idx.append(idx_r)
            else:
                failed.append(idx_r)
        if not ok_idx:
            return self._err(
                "verify_error",
                "verify",
                "all variants failed syntax verification",
                results[0] and [{"message": "see original source"}],
            )
        verify_status = "compiled" if not failed else "warning"

        if count == 1:
            return {
                "status": "ok",
                "code": results[0],
                "applied": applied,
                "verify": verify_status,
            }
        return {
            "status": "ok",
            "results": results,
            "applied": applied,
            "verify": verify_status,
            "failed_indexes": failed,
        }

    # ------------------------------------------------------------------
    # Transform
    # ------------------------------------------------------------------

    def _transform(
        self,
        clean_code: str,
        tu: clang.cindex.TranslationUnit,
        input_path: str,
        strategies: dict,
        reserved: set[str],
        rng: random.Random,
    ) -> str:
        edits: list[_Edit] = []
        applied: list[str] = []

        if strategies.get("rename"):
            renames = self._collect_renames(tu, input_path, reserved, rng)
            if renames:
                # Replace at every *reference* / *identifier* token, not the
                # whole extent of the Decl. PyClang's VAR_DECL extent spans
                # ``static int g_counter``; replacing that nukes the type and
                # is wrong. We instead use the spelling's exact offset range.
                for c in tu.cursor.walk_preorder():
                    if not c.spelling or c.spelling not in renames:
                        continue
                    if not (c.location.file and c.location.file.name == input_path):
                        continue
                    if c.extent.start.file is None or c.extent.start.file.name != input_path:
                        continue
                    new_text = renames[c.spelling]
                    name_len = len(c.spelling.encode("utf-8"))
                    # The spelling is the name. Find its position by scanning
                    # the source from extent.start.offset for a byte run that
                    # matches the spelling. We rely on cursor spelling being
                    # contiguous ASCII in practice; for unicode identifiers
                    # this would need Cursor.get_tokens().
                    pos = self._locate_spelling(clean_code, c.extent.start.offset, c.spelling)
                    if pos is None:
                        continue
                    edits.append(_Edit(pos, name_len, new_text))
            applied.append("rename")

        if strategies.get("shuffleIncludes"):
            inc_edits = self._shuffle_includes(clean_code, rng)
            edits.extend(inc_edits)
            applied.append("shuffleIncludes")

        if strategies.get("literalRewrite"):
            edits.extend(self._rewrite_integer_literals(clean_code, edits, rng))
            applied.append("literalRewrite")

        return _apply_edits(clean_code, edits)

    @staticmethod
    def _locate_spelling(code: str, start_offset: int, spelling: str) -> int | None:
        """Return byte offset of ``spelling`` in ``code`` starting search at
        ``start_offset``. Identifiers are contiguous ASCII in 99% of OJ code;
        we use a simple forward scan up to 64 bytes.
        """
        if not spelling:
            return None
        # Bound the search to a small window from the cursor start
        for delta in range(0, 64):
            i = start_offset + delta
            if i + len(spelling) > len(code):
                return None
            if code[i : i + len(spelling)] == spelling:
                # Boundary check: char before/after should not be alphanumeric
                # or underscore (to avoid matching the middle of a longer
                # identifier).
                before = code[i - 1] if i > 0 else " "
                after = code[i + len(spelling)] if i + len(spelling) < len(code) else " "
                if (before.isalnum() or before == "_") or (after.isalnum() or after == "_"):
                    continue
                return i
        return None

    def _collect_renames(
        self,
        tu: clang.cindex.TranslationUnit,
        input_path: str,
        reserved: set[str],
        rng: random.Random,
    ) -> dict[str, str]:
        """Walk the AST and return {original_spelling → new_spelling}."""
        rename_targets = {
            CursorKind.VAR_DECL,
            CursorKind.FUNCTION_DECL,
            CursorKind.CXX_METHOD,
            CursorKind.FIELD_DECL,
            CursorKind.PARM_DECL,
            CursorKind.TYPEDEF_DECL,
            CursorKind.STRUCT_DECL,
            CursorKind.CLASS_DECL,
            CursorKind.ENUM_CONSTANT_DECL,
            CursorKind.NAMESPACE,
            CursorKind.CONSTRUCTOR,
            CursorKind.DESTRUCTOR,
        }
        original_names: set[str] = set()
        for c in tu.cursor.walk_preorder():
            if c.kind in rename_targets and c.spelling:
                # Filter to user symbols only
                loc = c.location
                if loc.file and loc.file.name == input_path:
                    original_names.add(c.spelling)

        used: set[str] = set(reserved)
        mapping: dict[str, str] = {}
        for orig in sorted(original_names):
            if (
                orig in reserved
                or orig in _FORCED_RESERVED_SYMBOLS
                or orig.startswith("operator")
                or (orig.startswith("__") and orig.endswith("__"))
            ):
                continue
            new = self.wordlist.pick(orig, used, rng)
            mapping[orig] = new
            used.add(new)
        return mapping

    def _rewrite_integer_literals(
        self,
        clean_code: str,
        existing_edits: list[_Edit],
        rng: random.Random,
    ) -> list[_Edit]:
        """Rewrite safe decimal integer literals to equivalent expressions.

        This intentionally avoids preprocessor lines, strings/chars, member
        access, ranges, and existing edit spans. It is a conservative M1 token
        pass rather than a full typed literal strategy.
        """
        occupied = [(e.start, e.start + e.length) for e in existing_edits]
        line_starts = _line_start_offsets(clean_code)
        edits: list[_Edit] = []

        for match in _INT_LITERAL_RE.finditer(clean_code):
            start, end = match.span()
            if _overlaps_any(start, end, occupied):
                continue
            if _is_in_preprocessor_line(clean_code, start, line_starts):
                continue
            if _is_inside_string_or_char(clean_code, start):
                continue

            value_text = match.group("value")
            suffix = match.group("suffix") or ""
            if suffix and not re.fullmatch(r"[uUlL]+", suffix):
                continue
            try:
                value = int(value_text, 10)
            except ValueError:
                continue
            if value < 2 or value > 1_000_000_000:
                continue
            if rng.random() > 0.65:
                continue

            replacement = _equivalent_int_expr(value, suffix, rng)
            if replacement == match.group(0):
                continue
            edits.append(_Edit(start, end - start, replacement))
        return edits

    def _shuffle_includes(self, clean_code: str, rng: random.Random) -> list[_Edit]:
        """Find contiguous top-of-file include directives, shuffle them.

        M1 keeps the body untouched; only the include block at the top is
        re-ordered. This is what we mean by "include random": not within the
        whole file, just the first contiguous block.
        """
        lines = clean_code.split("\n")
        n = 0
        # Allow leading blank lines and comments (already stripped by preclean,
        # but be defensive)
        inc_re = re.compile(r"^\s*#\s*include\b")
        while n < len(lines) and (lines[n].strip() == "" or inc_re.match(lines[n])):
            n += 1
        if n < 2:
            return []
        # The block is [0, n). Shuffle it.
        block = lines[:n]
        original_block = list(block)
        # Re-shuffle until we get a different order (so the user sees a change
        # in at least the seed=0 case; with no observable change, S9 looks
        # like a no-op).
        for _ in range(8):
            rng.shuffle(block)
            if block != original_block:
                break
        if block == original_block:
            return []
        new_text = "\n".join(block) + "\n"
        return [_Edit(0, len("\n".join(original_block)) + 1, new_text)]

    # ------------------------------------------------------------------
    # Settings loader
    # ------------------------------------------------------------------

    def _load_settings(self, language: str) -> dict:
        if language in self._settings_cache:
            return self._settings_cache[language]
        p = (
            Path(__file__).resolve().parents[2]
            / "resources"
            / "language_settings"
            / f"{language}.json"
        )
        try:
            data = json.loads(p.read_text())
        except FileNotFoundError:
            data = {}
        self._settings_cache[language] = data
        return data

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _err(code: str, stage: str, message: str, errors: list[dict] | None = None) -> dict:
        return {
            "status": "error",
            "code": code,
            "stage": stage,
            "message": message,
            "errors": errors or [],
        }


# ---------------------------------------------------------------------------
# Free helpers
# ---------------------------------------------------------------------------


def _apply_edits(code: str, edits: list[_Edit]) -> str:
    """Apply edits right-to-left so earlier offsets stay valid."""
    if not edits:
        return code
    # Deduplicate (multiple cursors can target the same source range)
    seen: set[tuple[int, int]] = set()
    unique: list[_Edit] = []
    for e in edits:
        key = (e.start, e.length)
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    # Sort by start descending
    unique.sort(key=lambda x: x.start, reverse=True)
    out = code
    for e in unique:
        s = max(0, e.start)
        t = min(len(out), e.start + e.length)
        out = out[:s] + e.new_text + out[t:]
    return out


def _line_start_offsets(code: str) -> list[int]:
    starts = [0]
    for idx, ch in enumerate(code):
        if ch == "\n":
            starts.append(idx + 1)
    return starts


def _is_in_preprocessor_line(code: str, offset: int, line_starts: list[int]) -> bool:
    line_start = 0
    for start in line_starts:
        if start > offset:
            break
        line_start = start
    return code[line_start:offset].lstrip().startswith("#")


def _overlaps_any(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


def _is_inside_string_or_char(code: str, offset: int) -> bool:
    """Best-effort lexical check for whether offset is inside a C/C++ literal."""
    state = "normal"
    quote = ""
    escape = False
    i = 0
    while i < offset:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < len(code) else ""

        if state == "normal":
            if ch == "/" and nxt == "/":
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            if ch in {"'", '"'}:
                state = "quote"
                quote = ch
                escape = False
            i += 1
            continue

        if state == "line_comment":
            if ch == "\n":
                state = "normal"
            i += 1
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "normal"
                i += 2
                continue
            i += 1
            continue

        if state == "quote":
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                state = "normal"
            i += 1
            continue

    return state == "quote"


def _equivalent_int_expr(value: int, suffix: str, rng: random.Random) -> str:
    token = f"{value}{suffix}"
    if value <= 3:
        return token

    if rng.random() < 0.5:
        left = rng.randint(1, value - 1)
        right = value - left
        return f"({left}{suffix} + {right}{suffix})"

    mask = rng.randint(1, min(255, max(1, value * 2)))
    encoded = value ^ mask
    return f"({encoded}{suffix} ^ {mask}{suffix})"


def _select_strategies(preset_id: str, overrides: dict) -> dict:
    presets_path = (
        Path(__file__).resolve().parents[2] / "resources" / "presets.json"
    )
    base: dict = {}
    try:
        data = json.loads(presets_path.read_text())
        for preset in data.get("presets", []):
            if preset["id"] == preset_id:
                base = dict(preset.get("strategies", {}))
                break
    except FileNotFoundError:
        pass
    if not base:
        base = {
            "rename": True,
            "flatten": "off",
            "junk": "off",
            "splitExpression": False,
            "literalRewrite": True,
            "splitFunction": False,
            "templateRandom": False,
            "stripComments": True,
            "shuffleIncludes": True,
        }
    base.update(overrides)
    return base


def _collect_applied(strategies: dict) -> list[str]:
    out: list[str] = []
    if strategies.get("rename"):
        out.append("rename")
    if strategies.get("splitExpression"):
        out.append("splitExpression")
    if strategies.get("literalRewrite"):
        out.append("literalRewrite")
    if strategies.get("shuffleIncludes"):
        out.append("shuffleIncludes")
    return out
