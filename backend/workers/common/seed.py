"""Reproducible per-variant seed.

DESIGN §8.2: same code + same preset + same variant_idx ⇒ same seed, so the
"reproducibility" risk in SPEC §10 is mitigated.
"""

from __future__ import annotations

import hashlib


def seed_for(code: str, preset: str, variant_idx: int) -> int:
    """Deterministic 64-bit seed derived from the request.

    ``variant_idx`` is 0-based; callers that want 1-based should pass ``i - 1``.
    """
    h = hashlib.sha256()
    h.update(code.encode("utf-8"))
    h.update(b"|")
    h.update(preset.encode("utf-8"))
    h.update(b"|")
    h.update(variant_idx.to_bytes(4, "big"))
    digest = h.digest()
    return int.from_bytes(digest[:8], "big")
