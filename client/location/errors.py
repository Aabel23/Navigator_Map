"""Result / rejection-reason conventions for the location subsystem.

Rejections are data, not exceptions: a single malformed GPS measurement
must never crash the caller. ``LocationProcessor.process`` returns
``None`` on rejection and records the reason for observability instead
of raising.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RejectionReason(str, Enum):
    """Why a raw measurement was not accepted as a valid position."""

    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_COORDINATE = "INVALID_COORDINATE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    STALE_POSITION = "STALE_POSITION"
    LOW_ACCURACY = "LOW_ACCURACY"
    IMPOSSIBLE_JUMP = "IMPOSSIBLE_JUMP"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a single ``RawPosition``.

    ``is_valid`` is True only when the measurement may proceed to
    filtering and be emitted as a ``PositionUpdate``. ``reason`` is set
    whenever ``is_valid`` is False.
    """

    is_valid: bool
    reason: Optional[RejectionReason] = None
    detail: str = ""

    @staticmethod
    def ok() -> "ValidationResult":
        return ValidationResult(is_valid=True)

    @staticmethod
    def reject(reason: RejectionReason, detail: str = "") -> "ValidationResult":
        return ValidationResult(is_valid=False, reason=reason, detail=detail)
