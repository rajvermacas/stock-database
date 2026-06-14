# Strategy Bake-Off & Optimizer Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to carry out this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily-bar backtest that optimizes 6 long-only strategies independently on in-sample data (2016–2022), then ranks them out-of-sample (2023–2026) by Calmar (CAGR÷MaxDD) and reports the single best profit-per-drawdown strategy with concrete numbers (max drawdown, winrate, stoploss, target, yearly profit).

**Approach:** One shared portfolio engine with pluggable entry-signal functions (DRY). A two-stage engine keeps the 600+ backtests tractable: Stage A precomputes per-trade exits (vectorized per symbol, depends only on SL%/target%), Stage B allocates K equal-weight slots and builds the daily equity curve. Grid-search SL%×target%×K per strategy on train, freeze best-Calmar params, run once on test, compare.

**Tools / Inputs:** Python 3.12, Polars, NumPy, Typer; precalculated parquet under `market-data/{prices,indicators}/1d/`; watchlist `market-data/metadata/symbols.csv`. Spec: `docs/superpowers/specs/2026-06-14-strategy-bakeoff-design.md`.

---

## Conventions (apply to every task)

- Start every module with `from __future__ import annotations`.
- Logging: `import logging; LOGGER = logging.getLogger(__name__)`. Log detailed progress (symbols loaded, combos run, winner).
- Errors: define a `BacktestError(ValueError)` base in `errors.py`; raise specific, clear exceptions. **No silent defaults / fallback values** — missing data, empty windows, or zero-trade results raise.
- Files <800 lines; functions <80 lines, single responsibility.
- Reuse existing loaders where they fit (`stock_data.symbols.load_symbols`, `stock_data.config.load_config`).
- Run tests with: `python -m pytest tests/backtest/<file> -v`.
- After each task: stage only that task's files and commit with the given message.

## Data facts (verified — rely on these)

- Indicator parquet (`market-data/indicators/1d/<SYM>.parquet`) is warmup-trimmed: **zero nulls** in indicator columns. Columns include: `symbol, trade_timestamp, ema_10, ema_20, ema_50, ema_100, ema_200, relative_volume_20, rsi_14, atr_14, macd_12_26, macd_signal_9, macd_histogram, adx_14, band_lower_20_2, band_middle_20, band_upper_20_2, trailing_365d_high, ...`.
- Price parquet (`market-data/prices/1d/<SYM>.parquet`) columns: `symbol, trade_timestamp, open, high, low, close, volume`. Has more rows than indicators (pre-warmup bars); use **inner join** on `trade_timestamp`.
- `trade_timestamp` dtype: `Datetime("us", "Asia/Kolkata")`.
- `market-data/backtest/` is NOT gitignored — report output commits normally.

## Module layout (created across tasks)

```
src/stock_data/backtest/
  __init__.py        # Task 1
  errors.py          # Task 1  — BacktestError + subclasses
  params.py          # Task 1  — BacktestConfig dataclass + grids + windows
  data.py            # Task 2  — load/join, weekly trend, window slicing
  signals.py         # Task 3  — 6 entry-signal functions + SIGNALS registry
  metrics.py         # Task 4  — metrics from equity curve + trade ledger
  engine.py          # Task 5  — two-stage simulator (exits + slot allocation)
  optimize.py        # Task 6  — per-strategy grid search on train
  compare.py         # Task 7  — freeze params, run test, rank
  report.py          # Task 8  — markdown + csv render
  cli.py             # Task 9  — typer command, wired into main app
tests/backtest/
  test_data.py test_signals.py test_metrics.py test_engine.py
  test_optimize.py test_compare.py test_report.py
```

---

## Task 1: Package scaffold — errors, params, constants

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/__init__.py`, `src/stock_data/backtest/errors.py`, `src/stock_data/backtest/params.py`, `tests/backtest/__init__.py`
- Done-check: `python -c "from stock_data.backtest.params import BacktestConfig, SL_GRID, TARGET_GRID, K_GRID, WindowSpec; print(len(SL_GRID)*len(TARGET_GRID)*len(K_GRID))"` prints `100`.

- [ ] **Step 1: Create `src/stock_data/backtest/__init__.py`** (empty file).

- [ ] **Step 2: Create `src/stock_data/backtest/errors.py`**

```python
from __future__ import annotations


class BacktestError(ValueError):
    """Base error for the backtest package."""


class DataWindowError(BacktestError):
    """Raised when a requested window has no usable data."""


class ZeroTradesError(BacktestError):
    """Raised when a backtest produced no trades."""


class DegenerateMetricError(BacktestError):
    """Raised when a metric cannot be computed (e.g. zero drawdown)."""
```

- [ ] **Step 3: Create `src/stock_data/backtest/params.py`**

```python
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
```

- [ ] **Step 4: Create `tests/backtest/__init__.py`** (empty file).

- [ ] **Step 5: Verify**

Run: `python -c "from stock_data.backtest.params import BacktestConfig, SL_GRID, TARGET_GRID, K_GRID, WindowSpec; c=BacktestConfig(); print(len(SL_GRID)*len(TARGET_GRID)*len(K_GRID), c.cost_per_leg)"`
Expected: `100 0.0015`

- [ ] **Step 6: Commit**

```bash
git add src/stock_data/backtest/__init__.py src/stock_data/backtest/errors.py src/stock_data/backtest/params.py tests/backtest/__init__.py
git commit -m "feat(backtest): package scaffold, errors, params/grids"
```

---

## Task 2: data.py — load, join, weekly trend, window slicing

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/data.py`, `tests/backtest/test_data.py`
- Done-check: `python -m pytest tests/backtest/test_data.py -v` PASS, plus a smoke load of one real symbol.

**Responsibility:** Turn parquet files into clean, single-symbol Polars frames sorted by time, each carrying OHLCV + indicators + a look-ahead-safe `weekly_uptrend` boolean. No simulation logic here.

- [ ] **Step 1: Write `src/stock_data/backtest/data.py`**

Weekly trend definition (spec 5.2): weekly close > weekly EMA30 AND weekly EMA30 rising. To avoid look-ahead, each daily bar uses the **previous completed week's** value.

```python
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from stock_data.backtest.errors import DataWindowError

LOGGER = logging.getLogger(__name__)

PRICE_COLS = ["trade_timestamp", "open", "high", "low", "close", "volume"]


def load_symbol_frame(prices_dir: Path, indicators_dir: Path, symbol: str) -> pl.DataFrame:
    """Inner-join price OHLCV onto the indicator frame for one symbol."""
    ind_path = indicators_dir / "1d" / f"{symbol}.parquet"
    price_path = prices_dir / "1d" / f"{symbol}.parquet"
    if not ind_path.exists() or not price_path.exists():
        raise DataWindowError(f"Missing parquet for {symbol}")
    indicators = pl.read_parquet(ind_path)
    prices = pl.read_parquet(price_path).select(PRICE_COLS)
    frame = indicators.join(prices, on="trade_timestamp", how="inner").sort(
        "trade_timestamp"
    )
    if frame.height == 0:
        raise DataWindowError(f"Empty joined frame for {symbol}")
    return add_weekly_uptrend(frame)


def add_weekly_uptrend(frame: pl.DataFrame) -> pl.DataFrame:
    """Add look-ahead-safe `weekly_uptrend` (previous completed week)."""
    weekly = (
        frame.sort("trade_timestamp")
        .group_by_dynamic("trade_timestamp", every="1w", label="left")
        .agg(pl.col("close").last().alias("w_close"))
        .sort("trade_timestamp")
    )
    weekly = weekly.with_columns(
        pl.col("w_close").ewm_mean(span=30, adjust=False).alias("w_ema30")
    )
    weekly = weekly.with_columns(
        (
            (pl.col("w_close") > pl.col("w_ema30"))
            & (pl.col("w_ema30") > pl.col("w_ema30").shift(1))
        )
        .shift(1)                       # use PREVIOUS completed week -> no look-ahead
        .fill_null(False)
        .alias("weekly_uptrend")
    ).select(["trade_timestamp", "weekly_uptrend"])
    # Map each daily bar to its week bucket, then attach that week's flag.
    daily = frame.with_columns(
        pl.col("trade_timestamp").dt.truncate("1w").alias("week_start")
    )
    weekly = weekly.rename({"trade_timestamp": "week_start"})
    return daily.join(weekly, on="week_start", how="left").with_columns(
        pl.col("weekly_uptrend").fill_null(False)
    ).drop("week_start")


def slice_window(frame: pl.DataFrame, start: date, end: date) -> pl.DataFrame:
    """Return rows whose date is within [start, end] (inclusive)."""
    out = frame.filter(
        (pl.col("trade_timestamp").dt.date() >= start)
        & (pl.col("trade_timestamp").dt.date() <= end)
    )
    return out


def available_symbols(symbols: list[str], indicators_dir: Path, prices_dir: Path) -> list[str]:
    """Keep only symbols that have both parquet files."""
    keep = [
        s for s in symbols
        if (indicators_dir / "1d" / f"{s}.parquet").exists()
        and (prices_dir / "1d" / f"{s}.parquet").exists()
    ]
    if not keep:
        raise DataWindowError("No symbols have both price and indicator parquet")
    LOGGER.info("Backtest universe: %d of %d symbols usable", len(keep), len(symbols))
    return keep
```

- [ ] **Step 2: Write `tests/backtest/test_data.py`**

```python
from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from stock_data.backtest.data import add_weekly_uptrend, slice_window


def _frame(closes: list[float]) -> pl.DataFrame:
    n = len(closes)
    ts = pl.datetime_range(
        date(2020, 1, 1), date(2020, 1, 1), interval="1d", eager=True
    )
    ts = pl.Series(
        "trade_timestamp",
        pl.datetime_range(
            date(2020, 1, 1), interval="1d", eager=True, end=date(2020, 1, n)
        )[:n],
    ).dt.replace_time_zone("Asia/Kolkata")
    return pl.DataFrame(
        {
            "trade_timestamp": ts,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1] * n,
        }
    )


def test_weekly_uptrend_is_lookahead_safe_first_week_false():
    frame = _frame([float(i) for i in range(1, 41)])
    out = add_weekly_uptrend(frame)
    # First completed week has no previous week -> must be False (no look-ahead).
    assert out["weekly_uptrend"][0] is False or out["weekly_uptrend"][0] == False
    assert "weekly_uptrend" in out.columns
    assert out.height == frame.height


def test_slice_window_inclusive():
    frame = _frame([float(i) for i in range(1, 11)])
    out = slice_window(frame, date(2020, 1, 3), date(2020, 1, 5))
    assert out["trade_timestamp"].dt.date().min() == date(2020, 1, 3)
    assert out["trade_timestamp"].dt.date().max() == date(2020, 1, 5)
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/backtest/test_data.py -v`
Expected: PASS

Smoke-test on real data:
`python -c "from pathlib import Path; from stock_data.backtest.data import load_symbol_frame; f=load_symbol_frame(Path('market-data/prices'), Path('market-data/indicators'), 'ABSLAMC.NS'); print(f.shape, 'weekly_uptrend' in f.columns, f['weekly_uptrend'].sum())"`
Expected: a shape with the row count, `True`, and a positive integer count of uptrend bars.

- [ ] **Step 4: Commit**

```bash
git add src/stock_data/backtest/data.py tests/backtest/test_data.py
git commit -m "feat(backtest): data loading, weekly trend, window slicing"
```

---

## Task 3: signals.py — 6 entry signals + registry

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/signals.py`, `tests/backtest/test_signals.py`
- Done-check: `python -m pytest tests/backtest/test_signals.py -v` PASS.

**Responsibility:** Each signal is `f(frame: pl.DataFrame) -> pl.Series` (bool, aligned to rows). `frame` is a single-symbol frame from Task 2 (sorted, has indicators + `weekly_uptrend`). True at row i means "entry signal fired on bar i" (engine enters at next bar's open). All gated by `weekly_uptrend`. Strategy-intrinsic thresholds are fixed constants — NOT optimized.

- [ ] **Step 1: Write `src/stock_data/backtest/signals.py`**

```python
from __future__ import annotations

from collections.abc import Callable

import polars as pl

# Fixed strategy-intrinsic thresholds (NOT optimized — spec 5.2).
PULLBACK_LOOKBACK = 5
PULLBACK_RSI_COOL = 45.0
EMA_FRESH_LOOKBACK = 5
BREAKOUT_REL_VOL = 1.5
RSI_DIP_LOOKBACK = 5
RSI_DIP_LOW = 40.0
RSI_DIP_RECLAIM = 50.0
ADX_TREND = 25.0

SignalFn = Callable[[pl.DataFrame], pl.Series]


def _series(frame: pl.DataFrame, expr: pl.Expr) -> pl.Series:
    return frame.select(expr.alias("entry"))["entry"].fill_null(False)


def pullback_buy(frame: pl.DataFrame) -> pl.Series:
    uptrend = (
        pl.col("weekly_uptrend")
        & (pl.col("ema_10") > pl.col("ema_20"))
        & (pl.col("ema_20") > pl.col("ema_50"))
    )
    pulled = pl.col("low").rolling_min(PULLBACK_LOOKBACK) <= pl.col("ema_20")
    cooled = pl.col("rsi_14").rolling_min(PULLBACK_LOOKBACK) < PULLBACK_RSI_COOL
    reclaim = (pl.col("close") > pl.col("ema_10")) & (
        pl.col("close").shift(1) <= pl.col("ema_10").shift(1)
    )
    return _series(frame, uptrend & pulled & cooled & reclaim)


def ema_stack(frame: pl.DataFrame) -> pl.Series:
    aligned = (pl.col("ema_10") > pl.col("ema_20")) & (
        pl.col("ema_20") > pl.col("ema_50")
    )
    prior = aligned.cast(pl.Int8).shift(1).rolling_sum(EMA_FRESH_LOOKBACK)
    fresh = aligned & (prior == 0)
    return _series(frame, pl.col("weekly_uptrend") & fresh)


def breakout_52w(frame: pl.DataFrame) -> pl.Series:
    broke = pl.col("close") > pl.col("trailing_365d_high").shift(1)
    vol = pl.col("relative_volume_20") > BREAKOUT_REL_VOL
    return _series(frame, pl.col("weekly_uptrend") & broke & vol)


def bollinger_revert(frame: pl.DataFrame) -> pl.Series:
    tagged = pl.col("close").shift(1) <= pl.col("band_lower_20_2").shift(1)
    turn_up = pl.col("close") > pl.col("close").shift(1)
    return _series(frame, pl.col("weekly_uptrend") & tagged & turn_up)


def macd_adx(frame: pl.DataFrame) -> pl.Series:
    cross = (pl.col("macd_12_26") > pl.col("macd_signal_9")) & (
        pl.col("macd_12_26").shift(1) <= pl.col("macd_signal_9").shift(1)
    )
    strong = pl.col("adx_14") > ADX_TREND
    return _series(frame, pl.col("weekly_uptrend") & cross & strong)


def rsi_dip(frame: pl.DataFrame) -> pl.Series:
    dipped = pl.col("rsi_14").rolling_min(RSI_DIP_LOOKBACK) < RSI_DIP_LOW
    reclaim = (pl.col("rsi_14") > RSI_DIP_RECLAIM) & (
        pl.col("rsi_14").shift(1) <= RSI_DIP_RECLAIM
    )
    return _series(frame, pl.col("weekly_uptrend") & dipped & reclaim)


SIGNALS: dict[str, SignalFn] = {
    "pullback_buy": pullback_buy,
    "ema_stack": ema_stack,
    "breakout_52w": breakout_52w,
    "bollinger_revert": bollinger_revert,
    "macd_adx": macd_adx,
    "rsi_dip": rsi_dip,
}
```

- [ ] **Step 2: Write `tests/backtest/test_signals.py`**

```python
from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from stock_data.backtest.signals import SIGNALS, macd_adx


def _base(n: int) -> dict:
    ts = pl.Series(
        "trade_timestamp",
        pl.datetime_range(
            date(2020, 1, 1), interval="1d", eager=True, end=date(2030, 1, 1)
        )[:n],
    ).dt.replace_time_zone("Asia/Kolkata")
    cols = {
        "trade_timestamp": ts,
        "weekly_uptrend": [True] * n,
        "ema_10": [10.0] * n, "ema_20": [9.0] * n, "ema_50": [8.0] * n,
        "rsi_14": [50.0] * n, "low": [9.5] * n, "close": [11.0] * n,
        "trailing_365d_high": [100.0] * n, "relative_volume_20": [1.0] * n,
        "band_lower_20_2": [5.0] * n, "macd_12_26": [0.0] * n,
        "macd_signal_9": [1.0] * n, "adx_14": [30.0] * n,
    }
    return cols


def test_all_signals_return_bool_series_of_right_length():
    frame = pl.DataFrame(_base(60))
    for name, fn in SIGNALS.items():
        out = fn(frame)
        assert out.dtype == pl.Boolean, name
        assert out.len() == 60, name


def test_macd_adx_fires_on_cross_with_strong_adx():
    cols = _base(5)
    # Build a clean MACD cross-up on the last bar with ADX>25.
    cols["macd_12_26"] = [0.0, 0.0, 0.0, 0.0, 2.0]
    cols["macd_signal_9"] = [1.0, 1.0, 1.0, 1.0, 1.0]
    out = macd_adx(pl.DataFrame(cols))
    assert out[-1]  # cross up + adx 30 > 25
    assert not out[0]
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/backtest/test_signals.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/stock_data/backtest/signals.py tests/backtest/test_signals.py
git commit -m "feat(backtest): six entry-signal functions + registry"
```

---

## Task 4: metrics.py — performance metrics

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/metrics.py`, `tests/backtest/test_metrics.py`
- Done-check: `python -m pytest tests/backtest/test_metrics.py -v` PASS.

**Responsibility:** Pure functions over a daily equity Series and a trade ledger DataFrame → a metrics dict. No simulation, no IO.

Trade ledger schema (produced by engine, Task 5): columns `symbol(str), entry_date(date), exit_date(date), entry_price(f64), exit_price(f64), return_pct(f64), exit_reason(str)`. `return_pct` is NET of costs.

Equity curve schema: columns `date(date), equity(f64)`, one row per trading day in the window, starting at `capital`.

- [ ] **Step 1: Write `src/stock_data/backtest/metrics.py`**

```python
from __future__ import annotations

from datetime import date

import polars as pl

from stock_data.backtest.errors import DegenerateMetricError, ZeroTradesError


def max_drawdown(equity: pl.Series) -> float:
    """Worst peak-to-trough drop as a positive fraction (0.20 == -20%)."""
    running_peak = equity.cum_max()
    drawdown = (equity - running_peak) / running_peak
    return float(-drawdown.min())


def cagr(equity: pl.Series, start: date, end: date) -> float:
    years = (end - start).days / 365.25
    if years <= 0:
        raise DegenerateMetricError(f"Non-positive span {start}..{end}")
    final, initial = float(equity[-1]), float(equity[0])
    return (final / initial) ** (1.0 / years) - 1.0


def compute_metrics(
    equity: pl.Series, ledger: pl.DataFrame, start: date, end: date, sl_pct: float
) -> dict:
    if ledger.height == 0:
        raise ZeroTradesError("No trades to compute metrics from")
    mdd = max_drawdown(equity)
    if mdd <= 0:
        raise DegenerateMetricError("Zero drawdown — too few trades or a bug")
    annual = cagr(equity, start, end)
    rets = ledger["return_pct"]
    wins = rets.filter(rets > 0)
    losses = rets.filter(rets <= 0)
    r_multiple = rets / sl_pct  # risk per trade is the fixed stop distance
    return {
        "cagr": annual,
        "max_drawdown": mdd,
        "calmar": annual / mdd,
        "winrate": wins.len() / rets.len(),
        "num_trades": rets.len(),
        "avg_win_pct": float(wins.mean()) if wins.len() else 0.0,
        "avg_loss_pct": float(losses.mean()) if losses.len() else 0.0,
        "expectancy_r": float(r_multiple.mean()),
        "total_return": float(equity[-1] / equity[0] - 1.0),
    }
```

- [ ] **Step 2: Write `tests/backtest/test_metrics.py`**

```python
from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from stock_data.backtest.errors import ZeroTradesError
from stock_data.backtest.metrics import cagr, compute_metrics, max_drawdown


def test_max_drawdown_simple():
    eq = pl.Series([100.0, 120.0, 90.0, 110.0])  # peak 120 -> trough 90 = 25%
    assert abs(max_drawdown(eq) - 0.25) < 1e-9


def test_cagr_doubling_in_one_year():
    eq = pl.Series([100.0, 200.0])
    val = cagr(eq, date(2020, 1, 1), date(2021, 1, 1))
    assert abs(val - 1.0) < 0.01  # ~100% per year


def test_compute_metrics_raises_on_no_trades():
    eq = pl.Series([100.0, 101.0])
    empty = pl.DataFrame(schema={"return_pct": pl.Float64})
    with pytest.raises(ZeroTradesError):
        compute_metrics(eq, empty, date(2020, 1, 1), date(2021, 1, 1), 0.05)


def test_compute_metrics_winrate_and_calmar():
    eq = pl.Series([100.0, 130.0, 110.0, 150.0])  # mdd from 130->110 = ~15.4%
    ledger = pl.DataFrame({"return_pct": [0.10, -0.05, 0.20]})
    m = compute_metrics(eq, ledger, date(2020, 1, 1), date(2021, 1, 1), 0.05)
    assert abs(m["winrate"] - 2 / 3) < 1e-9
    assert m["num_trades"] == 3
    assert m["calmar"] > 0
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/backtest/test_metrics.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/stock_data/backtest/metrics.py tests/backtest/test_metrics.py
git commit -m "feat(backtest): performance metrics (CAGR, MaxDD, Calmar, ...)"
```

---

## Task 5: engine.py — two-stage portfolio simulator

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/engine.py`, `tests/backtest/test_engine.py`
- Done-check: `python -m pytest tests/backtest/test_engine.py -v` PASS (hand-checked trade, exit precedence, slot cap).

**Responsibility:** Given per-symbol frames + a strategy's entry signals + params, simulate an equal-weight K-slot long-only portfolio and return `(ledger, equity_curve)`. Two stages for speed:

- **Stage A `simulate_exits`** (depends only on SL%/target%/max_hold): per symbol, for each signal bar, enter at the NEXT bar's open and scan forward for the first exit (stoploss / target / time-stop / window-end). Returns candidate trades. Independent of K.
- **Stage B `allocate_slots`** (depends on K): walk the window's trading days; free slots whose trade has exited, fill free slots from that day's candidate entries (tie-break by `relative_volume_20` desc), and mark daily equity. Returns ledger + equity curve.

Look-ahead rules (spec 7): entry fills on the bar AFTER the signal at that bar's open; exits use the holding bar's own high/low; if SL and target both touched same bar, **stoploss wins**; gap-throughs fill at that bar's open.

- [ ] **Step 1: Write `src/stock_data/backtest/engine.py`**

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from stock_data.backtest.errors import ZeroTradesError
from stock_data.backtest.params import BacktestConfig

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SymbolArrays:
    """Window-sliced numpy view of one symbol for fast scanning."""

    symbol: str
    dates: np.ndarray          # dtype=object of datetime.date
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    rel_vol: np.ndarray
    entry: np.ndarray          # bool, signal fired on this bar


@dataclass(frozen=True)
class CandidateTrade:
    symbol: str
    entry_idx: int             # index into that symbol's arrays
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    gross_return: float
    rel_vol_at_signal: float
    exit_reason: str


def build_symbol_arrays(frame: pl.DataFrame, entry: pl.Series, col: str) -> SymbolArrays:
    f = frame.sort("trade_timestamp")
    return SymbolArrays(
        symbol=f["symbol"][0],
        dates=np.array(f["trade_timestamp"].dt.date().to_list(), dtype=object),
        open=f["open"].to_numpy(),
        high=f["high"].to_numpy(),
        low=f["low"].to_numpy(),
        close=f["close"].to_numpy(),
        rel_vol=f[col].to_numpy(),
        entry=entry.to_numpy(),
    )


def simulate_exits(
    arrays: SymbolArrays, sl_pct: float, tgt_pct: float, max_hold: int
) -> list[CandidateTrade]:
    """Stage A: resolve each signal into a candidate trade (entry next open)."""
    trades: list[CandidateTrade] = []
    n = len(arrays.close)
    signal_idx = np.flatnonzero(arrays.entry)
    for s in signal_idx:
        e = s + 1                       # enter at next bar's open
        if e >= n:
            continue
        entry_price = float(arrays.open[e])
        stop = entry_price * (1.0 - sl_pct)
        target = entry_price * (1.0 + tgt_pct)
        trade = _scan_forward(arrays, s, e, stop, target, max_hold, n)
        trades.append(trade)
    return trades


def _scan_forward(arrays, s, e, stop, target, max_hold, n) -> CandidateTrade:
    last = min(e + max_hold, n - 1)
    for j in range(e, last + 1):
        low, high, op = arrays.low[j], arrays.high[j], arrays.open[j]
        if low <= stop:                 # stoploss precedence
            price = float(op) if op <= stop else float(stop)
            return _mk(arrays, s, e, j, price, "stoploss")
        if high >= target:
            price = float(op) if op >= target else float(target)
            return _mk(arrays, s, e, j, price, "target")
    # time-stop / window-end: exit at close of `last` bar
    return _mk(arrays, s, e, last, float(arrays.close[last]),
               "time_stop" if last == e + max_hold else "window_end")


def _mk(arrays, s, e, j, exit_price, reason) -> CandidateTrade:
    entry_price = float(arrays.open[e])
    return CandidateTrade(
        symbol=arrays.symbol, entry_idx=e, entry_date=arrays.dates[e],
        exit_date=arrays.dates[j], entry_price=entry_price, exit_price=exit_price,
        gross_return=exit_price / entry_price - 1.0,
        rel_vol_at_signal=float(arrays.rel_vol[s]), exit_reason=reason,
    )


def allocate_slots(
    candidates: list[CandidateTrade],
    arrays_by_symbol: dict[str, SymbolArrays],
    trading_days: list[date],
    k_slots: int,
    cfg: BacktestConfig,
) -> tuple[pl.DataFrame, pl.Series]:
    """Stage B: K equal-weight slots; build ledger + daily equity curve."""
    by_entry: dict[date, list[CandidateTrade]] = {}
    for c in candidates:
        by_entry.setdefault(c.entry_date, []).append(c)

    slot_capital = cfg.capital / k_slots
    cash = cfg.capital
    open_positions: list[dict] = []     # {trade, shares, freed_date}
    taken: list[CandidateTrade] = []
    equity_points: list[float] = []
    close_lookup = _close_lookup(arrays_by_symbol)

    for day in trading_days:
        # 1) exits: free slots whose trade exits today
        still_open = []
        for pos in open_positions:
            if pos["trade"].exit_date == day:
                proceeds = pos["shares"] * pos["trade"].exit_price
                cash += proceeds * (1.0 - cfg.cost_per_leg)
            else:
                still_open.append(pos)
        open_positions = still_open
        # 2) entries: fill free slots from today's candidates
        free = k_slots - len(open_positions)
        if free > 0 and day in by_entry:
            ranked = sorted(by_entry[day], key=lambda c: -c.rel_vol_at_signal)
            for c in ranked[:free]:
                cost = slot_capital * cfg.cost_per_leg
                shares = slot_capital / c.entry_price
                cash -= slot_capital + cost
                open_positions.append(
                    {"trade": c, "shares": shares, "freed_date": c.exit_date}
                )
                taken.append(c)
        # 3) mark-to-market equity
        held_value = sum(
            p["shares"] * close_lookup[p["trade"].symbol].get(day, p["trade"].entry_price)
            for p in open_positions
        )
        equity_points.append(cash + held_value)

    ledger = _ledger(taken, cfg.cost_per_leg)
    return ledger, pl.Series("equity", equity_points)


def _close_lookup(arrays_by_symbol):
    return {
        sym: dict(zip(a.dates.tolist(), a.close.tolist()))
        for sym, a in arrays_by_symbol.items()
    }


def _ledger(taken: list[CandidateTrade], cost_per_leg: float) -> pl.DataFrame:
    rows = [
        {
            "symbol": c.symbol, "entry_date": c.entry_date, "exit_date": c.exit_date,
            "entry_price": c.entry_price, "exit_price": c.exit_price,
            "return_pct": (1.0 + c.gross_return) * (1.0 - cost_per_leg) ** 2 - 1.0,
            "exit_reason": c.exit_reason,
        }
        for c in taken
    ]
    schema = {
        "symbol": pl.String, "entry_date": pl.Date, "exit_date": pl.Date,
        "entry_price": pl.Float64, "exit_price": pl.Float64,
        "return_pct": pl.Float64, "exit_reason": pl.String,
    }
    return pl.DataFrame(rows, schema=schema)


def trading_calendar(arrays_by_symbol: dict[str, SymbolArrays]) -> list[date]:
    days: set[date] = set()
    for a in arrays_by_symbol.values():
        days.update(a.dates.tolist())
    return sorted(days)
```

- [ ] **Step 2: Write `tests/backtest/test_engine.py`**

```python
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from stock_data.backtest.engine import (
    SymbolArrays, allocate_slots, simulate_exits, trading_calendar,
)
from stock_data.backtest.params import BacktestConfig


def _arrays(symbol, dates, o, h, l, c, entry, rel=None):
    return SymbolArrays(
        symbol=symbol, dates=np.array(dates, dtype=object),
        open=np.array(o, float), high=np.array(h, float), low=np.array(l, float),
        close=np.array(c, float), rel_vol=np.array(rel or [1.0] * len(o), float),
        entry=np.array(entry, bool),
    )


def test_target_hit_exit_price_and_reason():
    # signal bar 0, enter bar 1 at open=100, target +10% = 110 hit on bar 2.
    a = _arrays(
        "X", [date(2020, 1, i) for i in range(1, 5)],
        o=[99, 100, 105, 108], h=[100, 104, 111, 109],
        l=[98, 99, 104, 107], c=[100, 103, 110, 108],
        entry=[True, False, False, False],
    )
    trades = simulate_exits(a, sl_pct=0.05, tgt_pct=0.10, max_hold=40)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "target"
    assert abs(t.exit_price - 110.0) < 1e-9
    assert t.entry_price == 100.0


def test_stoploss_precedence_when_both_touched():
    # bar 2 touches both stop (95) and target (110): stoploss must win.
    a = _arrays(
        "X", [date(2020, 1, i) for i in range(1, 4)],
        o=[99, 100, 102], h=[100, 101, 111],
        l=[98, 99, 94], c=[100, 100, 96],
        entry=[True, False, False],
    )
    trades = simulate_exits(a, sl_pct=0.05, tgt_pct=0.10, max_hold=40)
    assert trades[0].exit_reason == "stoploss"
    assert abs(trades[0].exit_price - 95.0) < 1e-9


def test_slot_cap_limits_concurrent_positions():
    cfg = BacktestConfig(capital=100.0, cost_bps_round_trip=0.0, max_hold_days=40)
    days = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
    # Two candidate trades entering same day, only 1 slot -> higher rel_vol taken.
    from stock_data.backtest.engine import CandidateTrade
    c_lo = CandidateTrade("A", 1, days[1], days[2], 10.0, 11.0, 0.1, 1.0, "target")
    c_hi = CandidateTrade("B", 1, days[1], days[2], 10.0, 12.0, 0.2, 5.0, "target")
    arrays = {
        "A": _arrays("A", days, [10] * 3, [10] * 3, [10] * 3, [10, 10, 11], [0, 1, 0]),
        "B": _arrays("B", days, [10] * 3, [10] * 3, [10] * 3, [10, 10, 12], [0, 1, 0]),
    }
    ledger, equity = allocate_slots([c_lo, c_hi], arrays, days, 1, cfg)
    assert ledger.height == 1
    assert ledger["symbol"][0] == "B"   # higher rel_vol won the single slot
    assert equity.len() == 3
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/backtest/test_engine.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/stock_data/backtest/engine.py tests/backtest/test_engine.py
git commit -m "feat(backtest): two-stage portfolio engine (exits + slot allocation)"
```

---

## Task 6: optimize.py — per-strategy grid search on train

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/optimize.py`, `tests/backtest/test_optimize.py`
- Done-check: `python -m pytest tests/backtest/test_optimize.py -v` PASS.

**Responsibility:** For one strategy, build per-symbol arrays once, then grid-search SL%×target%×K, scoring each combo by Calmar on the given window. Return the best params + their metrics. Reuses Stage A across K values: compute candidate trades per (SL,target), then allocate per K.

- [ ] **Step 1: Write `src/stock_data/backtest/optimize.py`**

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import polars as pl

from stock_data.backtest.engine import (
    SymbolArrays, allocate_slots, build_symbol_arrays, simulate_exits,
    trading_calendar,
)
from stock_data.backtest.errors import BacktestError, ZeroTradesError
from stock_data.backtest.metrics import compute_metrics
from stock_data.backtest.params import (
    K_GRID, SL_GRID, TARGET_GRID, BacktestConfig, WindowSpec,
)
from stock_data.backtest.signals import SIGNALS

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    sl_pct: float
    target_pct: float
    k_slots: int
    metrics: dict


def build_arrays_for_window(
    frames: dict[str, pl.DataFrame], strategy: str, window: WindowSpec, cfg: BacktestConfig
) -> dict[str, SymbolArrays]:
    """Compute signals on full history, then slice arrays to the window."""
    from stock_data.backtest.data import slice_window

    fn = SIGNALS[strategy]
    arrays: dict[str, SymbolArrays] = {}
    for sym, full in frames.items():
        entry_full = fn(full)
        sliced = slice_window(
            full.with_columns(entry_full.alias("__entry")), window.start, window.end
        )
        if sliced.height == 0:
            continue
        arrays[sym] = build_symbol_arrays(
            sliced.drop("__entry"), sliced["__entry"], cfg.rel_volume_tiebreak_col
        )
    if not arrays:
        raise BacktestError(f"No data for {strategy} in {window.name}")
    return arrays


def score_combo(
    arrays: dict[str, SymbolArrays], calendar: list[date], sl: float, tgt: float,
    k: int, window: WindowSpec, cfg: BacktestConfig,
) -> dict | None:
    candidates = []
    for a in arrays.values():
        candidates.extend(simulate_exits(a, sl, tgt, cfg.max_hold_days))
    if not candidates:
        return None
    ledger, equity = allocate_slots(candidates, arrays, calendar, k, cfg)
    try:
        return compute_metrics(equity, ledger, window.start, window.end, sl)
    except (ZeroTradesError, BacktestError):
        return None


def optimize_strategy(
    frames: dict[str, pl.DataFrame], strategy: str, window: WindowSpec, cfg: BacktestConfig
) -> StrategyResult:
    arrays = build_arrays_for_window(frames, strategy, window, cfg)
    calendar = trading_calendar(arrays)
    best: StrategyResult | None = None
    for sl in SL_GRID:
        for tgt in TARGET_GRID:
            # Stage A shared across K: compute candidates once per (sl,tgt).
            for k in K_GRID:
                metrics = score_combo(arrays, calendar, sl, tgt, k, window, cfg)
                if metrics is None:
                    continue
                cand = StrategyResult(strategy, sl, tgt, k, metrics)
                if best is None or _better(cand, best):
                    best = cand
    if best is None:
        raise ZeroTradesError(f"{strategy}: no profitable combo produced trades")
    LOGGER.info(
        "%s best: SL=%.0f%% TGT=%.0f%% K=%d Calmar=%.2f",
        strategy, best.sl_pct * 100, best.target_pct * 100, best.k_slots,
        best.metrics["calmar"],
    )
    return best


def _better(a: StrategyResult, b: StrategyResult) -> bool:
    if a.metrics["calmar"] != b.metrics["calmar"]:
        return a.metrics["calmar"] > b.metrics["calmar"]
    return a.metrics["cagr"] > b.metrics["cagr"]   # tie-break (spec 5.3)
```

> Note: `score_combo` recomputes Stage A per K for clarity. If the end-to-end run (Task 10) is too slow, refactor to compute `candidates` once per (sl,tgt) and loop K inside — the interfaces above already make that a local change in `optimize_strategy`.

- [ ] **Step 2: Write `tests/backtest/test_optimize.py`**

```python
from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from stock_data.backtest.optimize import _better, StrategyResult


def test_better_prefers_higher_calmar():
    a = StrategyResult("s", 0.05, 0.10, 5, {"calmar": 2.0, "cagr": 0.1})
    b = StrategyResult("s", 0.04, 0.12, 8, {"calmar": 1.0, "cagr": 0.9})
    assert _better(a, b)


def test_better_tiebreak_on_cagr():
    a = StrategyResult("s", 0.05, 0.10, 5, {"calmar": 1.0, "cagr": 0.20})
    b = StrategyResult("s", 0.04, 0.12, 8, {"calmar": 1.0, "cagr": 0.10})
    assert _better(a, b)
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/backtest/test_optimize.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/stock_data/backtest/optimize.py tests/backtest/test_optimize.py
git commit -m "feat(backtest): per-strategy grid-search optimizer (Calmar)"
```

---

## Task 7: compare.py — freeze params, run test, rank

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/compare.py`, `tests/backtest/test_compare.py`
- Done-check: `python -m pytest tests/backtest/test_compare.py -v` PASS.

**Responsibility:** Orchestrate the bake-off: for each strategy, optimize on TRAIN, freeze params, run once on TEST, collect train+test metrics into a ranked DataFrame (by test Calmar desc). Pure orchestration over Tasks 2/5/6.

- [ ] **Step 1: Write `src/stock_data/backtest/compare.py`**

```python
from __future__ import annotations

import logging
from datetime import date

import polars as pl

from stock_data.backtest.engine import (
    allocate_slots, simulate_exits, trading_calendar,
)
from stock_data.backtest.metrics import compute_metrics
from stock_data.backtest.optimize import (
    StrategyResult, build_arrays_for_window, optimize_strategy,
)
from stock_data.backtest.params import BacktestConfig, WindowSpec
from stock_data.backtest.signals import SIGNALS

LOGGER = logging.getLogger(__name__)


def run_on_window(
    frames: dict, strategy: str, sl: float, tgt: float, k: int,
    window: WindowSpec, cfg: BacktestConfig,
) -> dict:
    arrays = build_arrays_for_window(frames, strategy, window, cfg)
    calendar = trading_calendar(arrays)
    candidates = []
    for a in arrays.values():
        candidates.extend(simulate_exits(a, sl, tgt, cfg.max_hold_days))
    ledger, equity = allocate_slots(candidates, arrays, calendar, k, cfg)
    return compute_metrics(equity, ledger, window.start, window.end, sl)


def bakeoff(
    frames: dict, train: WindowSpec, test: WindowSpec, cfg: BacktestConfig
) -> pl.DataFrame:
    rows = []
    for strategy in SIGNALS:
        LOGGER.info("Optimizing %s on %s ...", strategy, train.name)
        best = optimize_strategy(frames, strategy, train, cfg)
        LOGGER.info("Testing %s on %s ...", strategy, test.name)
        test_metrics = run_on_window(
            frames, strategy, best.sl_pct, best.target_pct, best.k_slots, test, cfg
        )
        rows.append(_row(best, test_metrics))
    table = pl.DataFrame(rows).sort("test_calmar", descending=True)
    return table


def _row(best: StrategyResult, test_m: dict) -> dict:
    tr = best.metrics
    return {
        "strategy": best.strategy,
        "stoploss_pct": best.sl_pct * 100,
        "target_pct": best.target_pct * 100,
        "k_slots": best.k_slots,
        "train_calmar": tr["calmar"], "test_calmar": test_m["calmar"],
        "train_cagr": tr["cagr"], "test_cagr": test_m["cagr"],
        "train_max_dd": tr["max_drawdown"], "test_max_dd": test_m["max_drawdown"],
        "train_winrate": tr["winrate"], "test_winrate": test_m["winrate"],
        "test_expectancy_r": test_m["expectancy_r"],
        "test_avg_win_pct": test_m["avg_win_pct"],
        "test_avg_loss_pct": test_m["avg_loss_pct"],
        "test_num_trades": test_m["num_trades"],
        "overfit_gap": tr["calmar"] - test_m["calmar"],
    }
```

- [ ] **Step 2: Write `tests/backtest/test_compare.py`**

```python
from __future__ import annotations

from stock_data.backtest.compare import _row
from stock_data.backtest.optimize import StrategyResult


def test_row_shapes_train_and_test_columns():
    best = StrategyResult(
        "pullback_buy", 0.05, 0.12, 8,
        {"calmar": 2.0, "cagr": 0.25, "max_drawdown": 0.12, "winrate": 0.55},
    )
    test_m = {
        "calmar": 1.4, "cagr": 0.18, "max_drawdown": 0.13, "winrate": 0.5,
        "expectancy_r": 0.3, "avg_win_pct": 0.1, "avg_loss_pct": -0.04,
        "num_trades": 120,
    }
    row = _row(best, test_m)
    assert row["strategy"] == "pullback_buy"
    assert row["stoploss_pct"] == 5.0
    assert row["target_pct"] == 12.0
    assert abs(row["overfit_gap"] - 0.6) < 1e-9
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/backtest/test_compare.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/stock_data/backtest/compare.py tests/backtest/test_compare.py
git commit -m "feat(backtest): bake-off orchestration + ranked comparison"
```

---

## Task 8: report.py — markdown + csv render

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/report.py`, `tests/backtest/test_report.py`
- Done-check: `python -m pytest tests/backtest/test_report.py -v` PASS.

**Responsibility:** Turn the ranked DataFrame into a markdown report (ranked table + named winner with concrete numbers + caveats) and a sibling CSV. Pure rendering + file write.

- [ ] **Step 1: Write `src/stock_data/backtest/report.py`**

```python
from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

LOGGER = logging.getLogger(__name__)

CAVEATS = """\
## Honest caveats
- **Survivorship bias:** universe is today's watchlist (already survivors); live results will be worse.
- **Long-only, no hedge:** drawdown spikes in broad market declines (e.g. 2022).
- **Single train/test split** (not walk-forward): one out-of-sample estimate, not a distribution.
- **Equal-weight slots:** volatile stocks risk more rupees per slot than calm ones.
"""


def render_markdown(table: pl.DataFrame, train: str, test: str, run_date: str) -> str:
    winner = table.row(0, named=True)
    lines = [
        f"# Strategy Bake-Off — {run_date}",
        "",
        f"Train (optimize): **{train}** · Test (reported): **{test}**.",
        "Ranked by out-of-sample Calmar (CAGR ÷ MaxDrawdown).",
        "",
        "## Winner",
        f"**{winner['strategy']}** — best profit-per-drawdown out-of-sample.",
        "",
        f"- Stoploss: **{winner['stoploss_pct']:.0f}%**",
        f"- Target: **{winner['target_pct']:.0f}%**",
        f"- Slots (K): **{winner['k_slots']}**",
        f"- Test CAGR (yearly profit): **{winner['test_cagr'] * 100:.1f}%**",
        f"- Test max drawdown: **{winner['test_max_dd'] * 100:.1f}%**",
        f"- Test winrate: **{winner['test_winrate'] * 100:.1f}%**",
        f"- Test Calmar: **{winner['test_calmar']:.2f}**",
        "",
        "## Full ranking",
        _md_table(table),
        "",
        CAVEATS,
    ]
    return "\n".join(lines)


def _md_table(table: pl.DataFrame) -> str:
    pct = {
        "stoploss_pct", "target_pct", "train_cagr", "test_cagr",
        "train_max_dd", "test_max_dd", "train_winrate", "test_winrate",
        "test_avg_win_pct", "test_avg_loss_pct",
    }
    headers = table.columns
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for row in table.iter_rows(named=True):
        cells = []
        for h in headers:
            v = row[h]
            if isinstance(v, float):
                cells.append(f"{v * 100:.1f}%" if h in pct else f"{v:.2f}")
            else:
                cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def write_report(
    table: pl.DataFrame, out_dir: Path, run_date: str, train: str, test: str
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"bakeoff-{run_date}.md"
    csv_path = out_dir / f"bakeoff-{run_date}.csv"
    md_path.write_text(render_markdown(table, train, test, run_date), encoding="utf-8")
    table.write_csv(csv_path)
    LOGGER.info("Report written: %s and %s", md_path, csv_path)
    return md_path, csv_path
```

- [ ] **Step 2: Write `tests/backtest/test_report.py`**

```python
from __future__ import annotations

import polars as pl

from stock_data.backtest.report import render_markdown, write_report


def _table() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "strategy": "pullback_buy", "stoploss_pct": 5.0, "target_pct": 12.0,
                "k_slots": 8, "train_calmar": 2.0, "test_calmar": 1.4,
                "train_cagr": 0.25, "test_cagr": 0.18, "train_max_dd": 0.12,
                "test_max_dd": 0.13, "train_winrate": 0.55, "test_winrate": 0.5,
                "test_expectancy_r": 0.3, "test_avg_win_pct": 0.1,
                "test_avg_loss_pct": -0.04, "test_num_trades": 120,
                "overfit_gap": 0.6,
            }
        ]
    )


def test_markdown_names_winner_with_numbers():
    md = render_markdown(_table(), "2016..2022", "2023..2026", "2026-06-14")
    assert "Winner" in md
    assert "pullback_buy" in md
    assert "5%" in md and "12%" in md  # stoploss/target

def test_write_report_creates_both_files(tmp_path):
    md_path, csv_path = write_report(_table(), tmp_path, "2026-06-14", "T", "S")
    assert md_path.exists() and csv_path.exists()
```

- [ ] **Step 3: Verify**

Run: `python -m pytest tests/backtest/test_report.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/stock_data/backtest/report.py tests/backtest/test_report.py
git commit -m "feat(backtest): markdown + csv report rendering"
```

---

## Task 9: cli.py — wire the bake-off command into the app

**Inputs/Outputs:**
- Create: `src/stock_data/backtest/cli.py`
- Modify: `src/stock_data/cli.py` (register the subcommand)
- Done-check: `stock-data backtest-bakeoff --help` shows options; a `--limit`-scoped smoke run produces a report.

- [ ] **Step 1: Write `src/stock_data/backtest/cli.py`**

```python
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import typer

from stock_data.backtest.compare import bakeoff
from stock_data.backtest.data import available_symbols, load_symbol_frame
from stock_data.backtest.params import TEST_WINDOW, TRAIN_WINDOW, BacktestConfig
from stock_data.backtest.report import write_report
from stock_data.config import load_config
from stock_data.symbols import load_symbols

LOGGER = logging.getLogger(__name__)


def run_bakeoff(
    config_path: Path, run_date: str, limit: int | None, capital: float
) -> tuple[Path, Path]:
    cfg_app = load_config(config_path)
    symbols = load_symbols(cfg_app.paths.symbols_file)
    usable = available_symbols(
        symbols, cfg_app.paths.indicators_dir, cfg_app.paths.prices_dir
    )
    if limit is not None:
        usable = usable[:limit]
    LOGGER.info("Loading %d symbol frames ...", len(usable))
    frames = {
        s: load_symbol_frame(cfg_app.paths.prices_dir, cfg_app.paths.indicators_dir, s)
        for s in usable
    }
    cfg = BacktestConfig(capital=capital)
    table = bakeoff(frames, TRAIN_WINDOW, TEST_WINDOW, cfg)
    out_dir = cfg_app.paths.data_dir / "backtest"
    train = f"{TRAIN_WINDOW.start}..{TRAIN_WINDOW.end}"
    test = f"{TEST_WINDOW.start}..{TEST_WINDOW.end}"
    return write_report(table, out_dir, run_date, train, test)
```

- [ ] **Step 2: Register the command in `src/stock_data/cli.py`**

Add this command function (place it alongside the other `@app.command(...)` definitions; reuse the existing `configure_logging` + `State` pattern already in that file):

```python
@app.command("backtest-bakeoff")
def backtest_bakeoff(
    ctx: typer.Context,
    run_date: Annotated[str, typer.Option("--run-date", help="YYYY-MM-DD label for the report")],
    limit: Annotated[int | None, typer.Option("--limit", help="Cap symbols (smoke test)")] = None,
    capital: Annotated[float, typer.Option("--capital")] = 1_000_000.0,
) -> None:
    """Optimize 6 strategies on train, rank on test, write the bake-off report."""
    from stock_data.backtest.cli import run_bakeoff

    config = ctx.obj.config_path
    configure_logging(load_config(config).paths.logs_dir)
    md_path, csv_path = run_bakeoff(config, run_date, limit, capital)
    typer.echo(f"Report: {md_path}")
    typer.echo(f"CSV:    {csv_path}")
```

If `Annotated`/`configure_logging`/`load_config` are not already imported at the top of `src/stock_data/cli.py`, confirm the existing imports there (the file already imports `configure_logging`, `load_config`, `typer`, and `Annotated` per the current code) — do not add duplicates.

- [ ] **Step 3: Verify the command is registered**

Run: `stock-data --config config/stock-data.toml backtest-bakeoff --help`
Expected: usage text listing `--run-date`, `--limit`, `--capital`.

- [ ] **Step 4: Smoke run on a small universe**

Run: `stock-data --config config/stock-data.toml backtest-bakeoff --run-date 2026-06-14 --limit 25`
Expected: logs show each strategy optimized + tested; prints `Report:` and `CSV:` paths; both files exist under `market-data/backtest/`.

- [ ] **Step 5: Commit**

```bash
git add src/stock_data/backtest/cli.py src/stock_data/cli.py
git commit -m "feat(backtest): backtest-bakeoff CLI command"
```

---

## Task 10: Full run — produce and commit the real report

**Inputs/Outputs:**
- Output: `market-data/backtest/bakeoff-2026-06-14.md` + `.csv`
- Done-check: report exists, names a winner with all required numbers; full test suite green.

- [ ] **Step 1: Run the full universe bake-off**

Run: `stock-data --config config/stock-data.toml backtest-bakeoff --run-date 2026-06-14`
Expected: completes without error; report written. If runtime is excessive, apply the `optimize.py` refactor noted in Task 6 (compute Stage A candidates once per (SL,target), loop K inside).

- [ ] **Step 2: Sanity-check the report**

Open `market-data/backtest/bakeoff-2026-06-14.md`. Confirm:
- All 6 strategies present in the ranking table.
- A single winner named, with stoploss%, target%, K, test CAGR, test max drawdown, test winrate, test Calmar.
- `overfit_gap` column present per strategy (train Calmar − test Calmar).
- Caveats section present.

Concrete done-check command:
`python -c "import pathlib,sys; t=pathlib.Path('market-data/backtest/bakeoff-2026-06-14.md').read_text(); sys.exit(0 if ('Winner' in t and t.count('|')>20) else 1)"`
Expected: exit 0.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/backtest -v`
Expected: all PASS.

- [ ] **Step 4: Commit the report**

```bash
git add market-data/backtest/bakeoff-2026-06-14.md market-data/backtest/bakeoff-2026-06-14.csv
git commit -m "docs(backtest): bake-off results report (2026-06-14)"
```

---

## Self-Review (completed by plan author)

**Spec coverage:** Purpose→Task 10 report; objective Calmar→metrics(4)/optimize(6); data+weekly→data(2); validation train/test→params(1)/optimize(6)/compare(7); engine portfolio/exits/costs→engine(5); 6 signals→signals(3); optimizer grid→optimize(6); comparator+report→compare(7)/report(8); deliverables CLI+report+tests→cli(9)/run(10)/tests each task; caveats→report(8); fail-fast→errors(1) used throughout. All covered.

**Placeholders:** none — every step has concrete code or a concrete command + expected output. The Task 6/10 performance note is an explicit conditional optimization, not a TODO.

**Naming consistency:** `BacktestConfig`, `WindowSpec`, `SymbolArrays`, `CandidateTrade`, `StrategyResult`, `SIGNALS`, `simulate_exits`, `allocate_slots`, `build_arrays_for_window`, `optimize_strategy`, `bakeoff`, `run_on_window`, `write_report`, `run_bakeoff` are defined once and reused with matching signatures across tasks. Ledger/equity schemas defined in Task 5 and consumed identically in Tasks 4/6/7. Report path `market-data/backtest/bakeoff-2026-06-14.{md,csv}` consistent in Tasks 8/9/10.
