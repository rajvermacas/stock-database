from __future__ import annotations


class PullbackError(ValueError):
    """Base error for adaptive pullback analysis."""


class PullbackDataError(PullbackError):
    """Raised when source data is structurally invalid."""


class InsufficientEvidenceError(PullbackError):
    """Raised when a stock cannot support a learned decision."""


class LearningError(PullbackError):
    """Raised when stock-specific parameter learning fails."""
