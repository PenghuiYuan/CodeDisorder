"""Generate ``backend/resources/wordlist.txt`` from a system dictionary.

DESIGN §7.1: 30k-50k words, length 4-12, all-ASCII letters, sorted, de-duped.
We default to ``/usr/share/dict/words`` (macOS ships it once Xcode CLT or
``brew install words`` is in place). Output is the union of lowercase tokens
(so the worker's style classifier can capitalize as needed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MIN_LEN = 4
MAX_LEN = 12
TARGET_MIN = 30_000
TARGET_MAX = 50_000


def generate(src: Path) -> list[str]:
    out: set[str] = set()
    with src.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            w = line.strip()
            if not w:
                continue
            if not w.isascii() or not w.isalpha():
                continue
            if not (MIN_LEN <= len(w) <= MAX_LEN):
                continue
            out.add(w.lower())
    words = sorted(out)
    return words


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--src",
        type=Path,
        default=Path("/usr/share/dict/words"),
        help="source dictionary (one word per line)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "resources" / "wordlist.txt",
        help="output path",
    )
    p.add_argument("--print-stats", action="store_true")
    args = p.parse_args()

    if not args.src.exists():
        print(f"source dictionary not found: {args.src}", file=sys.stderr)
        print("on macOS: try installing Xcode Command Line Tools, or", file=sys.stderr)
        print("           point --src at any word list you have.", file=sys.stderr)
        return 1

    words = generate(args.src)
    if not (TARGET_MIN <= len(words) <= TARGET_MAX):
        # Not fatal; we accept any count, but warn.
        print(
            f"warning: produced {len(words)} words; target is {TARGET_MIN}-{TARGET_MAX}.",
            file=sys.stderr,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Always write a trailing newline so mmap-readers don't miss the last line.
    with args.out.open("w", encoding="utf-8") as f:
        f.write("\n".join(words))
        f.write("\n")

    if args.print_stats:
        print(f"wrote {len(words)} words to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
