from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

STOP_LOSS_FRACTION = 0.03


class Decision(StrEnum):
    BUY = "buy"
    WATCH = "watch"
    AVOID = "avoid"
    ABSTAIN = "abstain"


class OutcomeStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CENSORED = "censored"
    UNKNOWN = "unknown"
    PENDING = "pending"


@dataclass(frozen=True)
class FeatureBand:
    name: str
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("feature band requires a name")
        if self.lower > self.upper:
            raise ValueError("feature band lower exceeds upper")


@dataclass(frozen=True)
class ParameterSet:
    feature_bands: tuple[FeatureBand, ...]
    dip_band: tuple[float, float]
    swing_reversal_fraction: float
    regime_distance_limit: float
    sequence_length_bars: int
    setup_distance_limit: float
    lookback_bars: int
    horizon_bars: int
    target: float

    def __post_init__(self) -> None:
        if not self.feature_bands:
            raise ValueError("parameter set requires feature bands")
        if self.dip_band[0] > self.dip_band[1]:
            raise ValueError("dip band lower exceeds upper")
        counts = (self.sequence_length_bars, self.lookback_bars, self.horizon_bars)
        if min(counts) < 1:
            raise ValueError("learned bar counts must be positive")


@dataclass(frozen=True)
class QualityIssue:
    symbol: str
    code: str
    message: str


@dataclass(frozen=True)
class QualityResult:
    symbol: str
    rows: int
    first_timestamp: datetime
    last_timestamp: datetime
    cadence_seconds: float | None
    issues: tuple[QualityIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class Regime:
    start_index: int
    end_index: int
    weight: float


@dataclass(frozen=True)
class Opportunity:
    detection_index: int
    prior_high: float
    drawdown_fraction: float
    regime_end_index: int | None


@dataclass(frozen=True)
class TradePath:
    entry_index: int
    entry_price: float
    stop_price: float

    def __post_init__(self) -> None:
        expected = self.entry_price * (1 - STOP_LOSS_FRACTION)
        if abs(self.stop_price - expected) > max(abs(expected), 1.0) * 1e-12:
            raise ValueError("stop price must be exactly 3% below entry")


@dataclass(frozen=True)
class TradeOutcome:
    status: OutcomeStatus
    path: TradePath | None
    mfe_fraction: float | None
    mae_fraction: float | None
    bars_to_prior_high: int | None
    bars_to_stop: int | None
    bars_to_mfe: int | None


@dataclass(frozen=True)
class FoldScore:
    expected_return: float
    recovery_probability: float
    instability: float
    uncertainty: float
    resolved: int
    censored: int


@dataclass(frozen=True)
class StockDecision:
    symbol: str
    decision: Decision
    reason: str
    detection_timestamp: datetime | None
    entry_price: float | None
    stop_price: float | None
    parameter_set: ParameterSet | None
    expected_return: float | None
    adjusted_expected_return: float | None
    recovery_probability: float | None


@dataclass(frozen=True)
class ScreenResult:
    as_of: datetime
    ranked: tuple[StockDecision, ...]
    excluded: tuple[QualityIssue, ...]
    prefilter_rejections: tuple[str, ...]
    abstained: tuple[StockDecision, ...]
