"""Pydantic models for the FastAPI layer.

Aligned with SPEC §6.1 request/response shapes and SPEC §6.1 error envelope.
Uses Pydantic v2 syntax (``model_config = ConfigDict(...)``, ``field_validator``,
``model_dump``).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Request: POST /api/confuse
# ---------------------------------------------------------------------------


class StrategyOverrides(BaseModel):
    """Optional per-strategy overrides. Each field mirrors presets.json strategy keys.

    All fields optional; missing fields fall back to the preset default.
    """

    model_config = ConfigDict(extra="allow")

    rename: Optional[bool] = None
    flatten: Optional[Any] = None  # "off" | "simple" | "deep"
    junk: Optional[Any] = None  # "off" | "aggressive"
    splitExpression: Optional[bool] = None
    splitFunction: Optional[bool] = None
    templateRandom: Optional[bool] = None
    stripComments: Optional[bool] = None
    shuffleIncludes: Optional[bool] = None


class ConfuseRequest(BaseModel):
    """SPEC §6.1 request body for ``POST /api/confuse``."""

    model_config = ConfigDict(extra="forbid")

    language_in: str = Field(..., description="c / cpp / python / java / go")
    language_out: str = Field(..., description="MVP: must equal language_in")
    preset: str = Field(..., description="Preset id (see presets.json)")
    count: int = Field(1, description="1 / 3 / 5 / 10")
    overrides: Optional[StrategyOverrides] = None
    code: str = Field(..., description="Source code, <= 200KB UTF-8")

    @field_validator("language_in", "language_out")
    @classmethod
    def _normalize_language(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Response: success (count == 1)
# ---------------------------------------------------------------------------


class ConfuseResponse(BaseModel):
    """Unified success response.

    ``count == 1``: ``code`` is populated, ``zip_b64`` / ``failed_indexes`` are None.
    ``count  > 1``: ``zip_b64`` / ``failed_indexes`` are populated, ``code`` is None.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    language_in: str
    language_out: str
    preset: str
    count: int
    applied: list[str] = Field(default_factory=list)
    code: Optional[str] = None
    verify: str = "syntax-ok"  # compiled | syntax-ok | warning
    zip_b64: Optional[str] = None
    failed_indexes: Optional[list[int]] = None


# ---------------------------------------------------------------------------
# Response: error envelope
# ---------------------------------------------------------------------------


class ErrorItem(BaseModel):
    """A single structured error (line / column / message)."""

    model_config = ConfigDict(extra="forbid")

    line: Optional[int] = None
    column: Optional[int] = None
    message: str


class ErrorResponse(BaseModel):
    """SPEC §6.1 failure envelope.

    Note: ``status`` is always the literal string ``"error"`` for failure.
    ``code`` is the business error code (SPEC §15.6).
    """

    model_config = ConfigDict(extra="forbid")

    status: str = "error"
    code: str
    stage: str  # parse | transform | verify | request
    message: str
    errors: list[ErrorItem] = Field(default_factory=list)
