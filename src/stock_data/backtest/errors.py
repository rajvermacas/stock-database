from __future__ import annotations


class BacktestError(ValueError):
    """Base error for the backtest package."""


class DataWindowError(BacktestError):
    """Raised when a requested window has no usable data."""


class ZeroTradesError(BacktestError):
    """Raised when a backtest produced no trades."""


class DegenerateMetricError(BacktestError):
    """Raised when a metric cannot be computed (e.g. zero drawdown)."""
