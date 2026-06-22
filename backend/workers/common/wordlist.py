"""WordList loader for identifier renaming (S1).

DESIGN §7.3: mmap-load ``wordlist.txt`` once at Worker startup, group by naming
style so we can preserve the original identifier's case convention.

Styles we recognize:
- ``snake``: ``foo_bar_baz``  →  pick lowercase words
- ``camel``: ``fooBarBaz``    →  pick lowercase + capitalize after splits
- ``pascal``: ``FooBarBaz``   →  pick capitalized words
- ``upper_snake``: ``FOO_BAR`` →  pick uppercase
- ``flat``: ``foobar``         →  pick any word, leave as-is
"""

from __future__ import annotations

import mmap
import os
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "resources" / "wordlist.txt"


def _classify(name: str) -> str:
    """Return the naming style key for ``name`` (best-effort)."""
    if not name:
        return "flat"
    if "_" in name and name.upper() == name and any(c.isalpha() for c in name):
        return "upper_snake"
    if "_" in name and name == name.lower():
        return "snake"
    if name[0].isupper():
        return "pascal"
    if any(c.isupper() for c in name[1:]):
        return "camel"
    return "flat"


def _to_style(word: str, style: str) -> str:
    if style == "upper_snake":
        return word.upper()
    if style == "pascal":
        return word.capitalize()
    return word.lower()


def _split_snake(name: str) -> list[str]:
    return [p for p in name.split("_") if p]


def _split_camel(name: str) -> list[str]:
    parts: list[str] = []
    cur: list[str] = []
    for ch in name:
        if ch.isupper() and cur:
            parts.append("".join(cur))
            cur = [ch.lower()]
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p for p in parts if p]


def _style_word_count(style: str) -> int:
    """How many source words the style needs (1 for flat/upper_snake, len(splits) for others)."""
    if style in ("flat", "upper_snake"):
        return 1
    if style == "snake":
        return 2  # a_b — we want 2-word minimum so it still looks like a name
    if style in ("camel", "pascal"):
        return 2
    return 1


class WordList:
    """In-memory word list grouped by naming style."""

    def __init__(self, words: list[str]):
        self._by_style: dict[str, list[str]] = defaultdict(list)
        for w in words:
            self._by_style["lower"].append(w.lower())
        # De-dup while preserving order; ~50k entries is fine in memory
        for k, vs in self._by_style.items():
            seen: set[str] = set()
            dedup: list[str] = []
            for v in vs:
                if v not in seen:
                    seen.add(v)
                    dedup.append(v)
            self._by_style[k] = dedup

    @classmethod
    def load(cls, path: os.PathLike | str = DEFAULT_PATH) -> "WordList":
        p = Path(path)
        if not p.exists():
            # Fall back to a tiny built-in so dev/CI doesn't blow up; the
            # generate script writes a real one for production.
            return cls(_FALLBACK_WORDS)
        with open(p, "rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                data = mm.read().decode("utf-8", errors="ignore")
        words = [w.strip() for w in data.splitlines() if w.strip()]
        return cls(words)

    def pick(self, original: str, used: set[str], rng) -> str:
        """Pick a fresh name that doesn't collide with ``used``.

        ``rng`` is any object with ``.randint(a, b)`` (we accept ``random.Random``).
        Returns a name in the same naming style as ``original``.
        """
        style = _classify(original)
        pool = self._by_style.get("lower") or _FALLBACK_WORDS
        n = _style_word_count(style)
        for _ in range(64):  # bound the loop
            chunks = [pool[rng.randint(0, len(pool) - 1)] for _ in range(n)]
            candidate = _to_style("_".join(chunks), style) if style == "snake" else (
                "_".join(chunks).upper() if style == "upper_snake" else
                "".join(c.capitalize() for c in chunks) if style == "pascal" else
                chunks[0] + "".join(c.capitalize() for c in chunks[1:]) if style == "camel" else
                chunks[0]
            )
            if candidate and candidate not in used and candidate != original:
                return candidate
        # Last resort: suffix a number
        return f"{original}_x{rng.randint(0, 9999)}"

    def count(self) -> int:
        return len(self._by_style.get("lower", []))


_FALLBACK_WORDS = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "sigma", "omega", "nova", "pulse", "node",
    "bridge", "stream", "vector", "matrix", "tensor", "scalar", "kernel",
    "token", "glyph", "cipher", "echo", "frost", "ember", "spark", "lumen",
]


@lru_cache(maxsize=1)
def default_wordlist() -> WordList:
    """Process-wide default; loads once on first use."""
    return WordList.load()
