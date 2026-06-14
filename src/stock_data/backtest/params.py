from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Optimizer grids (spec 5.3). 5 x 5 x 4 = 100 combos per strategy.
SL_GRID: tuple[float, ...] = (0.03, 0.04, 0.05, 0.06, 0.08)
TARGET_GRID: tuple[float, ...] = (0.06, 0.09, 0.12, 0.15, 0.20)
K_GRID: tuple[int, ...] = (5, 8, 10, 15)


@dataclass(frozen=True)
class BacktestConfig:
    """Fixed (non-optimized) engine settings."""

    capital: float = 1_000_000.0
    cost_bps_round_trip: float = 30.0   # 0.30% round trip
    max_hold_days: int = 40             # time-stop
    rel_volume_tiebreak_col: str = "relative_volume_20"

    @property
    def cost_per_leg(self) -> float:
        return (self.cost_bps_round_trip / 10_000.0) / 2.0


@dataclass(frozen=True)
class WindowSpec:
    name: str          # "train" or "test"
    start: date
    end: date


TRAIN_WINDOW = WindowSpec("train", date(2016, 1, 1), date(2022, 12, 31))
TEST_WINDOW = WindowSpec("test", date(2023, 1, 1), date(2026, 6, 12))
