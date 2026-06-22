"""Comment / string aware state machine used by every language Worker.

DESIGN §4.7: shared lexer that recognizes ``/* */`` and ``//`` comments, string
literals, character literals, and raw string literals, so we can strip comments
(S8) without accidentally eating ``//`` inside a string.

Returns a pair ``(stripped_code, spans)`` where ``spans`` is a list of
``(orig_start, new_start, kind)`` tuples so callers can map offsets in the
stripped code back to offsets in the original. M1 doesn't strictly need the
spans (libclang and ``ast`` operate on token streams, not raw offsets), but
they're cheap to produce and the C++ rewriter (DESIGN §4.5) will use them when
PyClang's ``Rewriter`` falls short.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class _State(Enum):
    NORMAL = auto()
    LINE_COMMENT = auto()
    BLOCK_COMMENT = auto()
    STRING = auto()
    CHAR = auto()
    RAW_STRING = auto()       # C++11 R"(...)" with optional delimiter
    TRIPLE_STRING = auto()    # Python """...""" / '''...'''


@dataclass
class Span:
    orig_start: int   # offset in input where this token (comment/string) starts
    new_start: int    # offset in output where the same position now lives (== len(kept_so_far))
    kind: str         # "comment" | "string"


def strip_comments_and_track_spans(
    code: str, *, language: str = "cpp"
) -> tuple[str, list[Span]]:
    """Return ``(stripped, spans)``.

    The stripped output has every comment replaced with equivalent whitespace
    (so source positions for code remain stable). String contents are preserved
    verbatim — they may contain sequences that look like comments.
    """
    out: list[str] = []
    spans: list[Span] = []
    i = 0
    n = len(code)
    state = _State.NORMAL
    raw_d: str = ""  # active raw-string delimiter (e.g. ``)``, ``R"foo(``)

    # Whitespace characters used as comment fill
    NL = "\n"

    def emit_kept(ch: str) -> None:
        out.append(ch)

    def emit_replaced(ch: str) -> None:
        # Preserve newlines so line numbers in the output match the input.
        out.append(NL if ch == NL else " ")

    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""

        if state is _State.NORMAL:
            if c == "/" and nxt == "/":
                spans.append(Span(i, len("".join(out)), "comment"))
                state = _State.LINE_COMMENT
                emit_replaced(c)
                emit_replaced(nxt)
                i += 2
                continue
            if c == "/" and nxt == "*":
                spans.append(Span(i, len("".join(out)), "comment"))
                state = _State.BLOCK_COMMENT
                emit_replaced(c)
                emit_replaced(nxt)
                i += 2
                continue
            if c == '"' and language == "python" and code[i : i + 3] in ('"""',):
                spans.append(Span(i, len("".join(out)), "string"))
                state = _State.TRIPLE_STRING
                emit_kept(c)
                i += 1
                continue
            if c == '"':
                spans.append(Span(i, len("".join(out)), "string"))
                state = _State.STRING
                emit_kept(c)
                i += 1
                continue
            if c == "'":
                spans.append(Span(i, len("".join(out)), "string"))
                state = _State.CHAR
                emit_kept(c)
                i += 1
                continue
            # C++ raw string R"delim(...)delim" — handled best-effort; no MVP
            # strategy depends on it.
            if c == "R" and nxt == '"':
                spans.append(Span(i, len("".join(out)), "string"))
                state = _State.RAW_STRING
                # Try to read optional delimiter:  R"DELIM(
                j = i + 2
                delim_start = j
                while j < n and code[j] != "(":
                    j += 1
                raw_d = code[delim_start:j]  # may be ""
                emit_kept(code[i : j + 1])
                i = j + 1
                continue
            emit_kept(c)
            i += 1
            continue

        if state is _State.LINE_COMMENT:
            if c == NL:
                state = _State.NORMAL
                emit_kept(c)  # newline stays a newline
                i += 1
                continue
            emit_replaced(c)
            i += 1
            continue

        if state is _State.BLOCK_COMMENT:
            if c == "*" and nxt == "/":
                state = _State.NORMAL
                emit_replaced(c)
                emit_replaced(nxt)
                i += 2
                continue
            emit_replaced(c)
            i += 1
            continue

        if state is _State.STRING:
            if c == "\\" and nxt:
                emit_kept(c)
                emit_kept(nxt)
                i += 2
                continue
            if c == '"':
                state = _State.NORMAL
                emit_kept(c)
                i += 1
                continue
            emit_kept(c)
            i += 1
            continue

        if state is _State.CHAR:
            if c == "\\" and nxt:
                emit_kept(c)
                emit_kept(nxt)
                i += 2
                continue
            if c == "'":
                state = _State.NORMAL
                emit_kept(c)
                i += 1
                continue
            emit_kept(c)
            i += 1
            continue

        if state is _State.RAW_STRING:
            # closing token is )DELIM"
            closing = ")" + raw_d + '"'
            if code.startswith(closing, i):
                state = _State.NORMAL
                emit_kept(closing)
                i += len(closing)
                continue
            emit_kept(c)
            i += 1
            continue

        if state is _State.TRIPLE_STRING:
            if c == "\\" and nxt:
                emit_kept(c)
                emit_kept(nxt)
                i += 2
                continue
            if code.startswith('"""', i):
                state = _State.NORMAL
                emit_kept('"""')
                i += 3
                continue
            emit_kept(c)
            i += 1
            continue

    return "".join(out), spans


def preclean(code: str, *, language: str = "cpp") -> str:
    """S8-preclean: BOM strip, newline normalize, comment strip (preserving newlines)."""
    if code.startswith("\ufeff"):
        code = code[1:]
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    stripped, _ = strip_comments_and_track_spans(code, language=language)
    return stripped
