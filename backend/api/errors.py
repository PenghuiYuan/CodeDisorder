"""Business error codes for the API layer (SPEC §15.6).

These are string constants emitted in ``ErrorResponse.code`` so the frontend
can branch on a stable identifier (SPEC §15.4 #2 says: do not branch on
``message`` text).  The values match SPEC §15.6 verbatim.
"""

from __future__ import annotations

# --- SPEC §15.6 business error codes -------------------------------------

PARSE_ERROR = "parse_error"  # source has a syntax error
VERIFY_ERROR = "verify_error"  # compile / syntax validation failed
TRANSFORM_ERROR = "transform_error"  # internal transform crashed
QUOTA_EXCEEDED = "quota_exceeded"  # quota exhausted (M5)
AUTH_REQUIRED = "auth_required"  # login needed (M5)
RATE_LIMITED = "rate_limited"  # per-IP throttling
PAYLOAD_TOO_LARGE = "payload_too_large"  # > 200KB
INTERNAL_ERROR = "internal_error"  # fallback
LANGUAGE_NOT_SUPPORTED = "language_not_supported"

# --- MVP-internal validation codes (not in §15.6 list but referenced by
# DESIGN §3.2; the frontend treats them as the same family and surfaces a
# friendly 400/413. Keeping them stable per SPEC §15.4 #2.) --------------

INVALID_TARGET_LANGUAGE = "invalid_target_language"  # language_in != language_out
INVALID_COUNT = "invalid_count"  # count not in {1, 3, 5, 10}
