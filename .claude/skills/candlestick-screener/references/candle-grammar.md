# Candle Grammar — Translate ANY Pattern Into a Polars Mask

This is a **grammar, not a catalog**. It gives you the candle-anatomy primitives and the
composition rules to express *any* candlestick pattern — named or described — as a single
Polars boolean expression (the "mask"). The worked examples at the end are illustrations
of the method; they are **not** the set of supported patterns. Build the mask the user's
request actually calls for.

All expressions are evaluated over the per-symbol price frame **after**
`.sort("symbol", "trade_timestamp")` (see `screen-procedure.md`). Bars are addressed by
lag: `k=0` is the bar on which the pattern *completes*, `k=1` is the prior bar, and so on.

## The lag operator (the spine of every multi-bar pattern)

```python
def L(col, k):
    # k=0 completing bar, k=1 prior bar, k=2 two bars back, ...
    return pl.col(col).shift(k).over("symbol")
```

A pattern over the last 3 bars is written purely in terms of `L("open", 0..2)`,
`L("high", 0..2)`, `L("low", 0..2)`, `L("close", 0..2)`. `shift(k).over("symbol")`
returns null for the first `k` bars of each symbol, which correctly excludes any window
without enough lookback.

## Per-bar primitives

For a bar at lag `k`, with `o,h,l,c = L("open",k), L("high",k), L("low",k), L("close",k)`:

| Primitive | Expression |
|---|---|
| body (signed) | `c - o` |
| bullish / bearish | `c > o` / `c < o` |
| total range | `h - l` |
| upper shadow | `h - pl.max_horizontal(o, c)` |
| lower shadow | `pl.min_horizontal(o, c) - l` |
| body size (abs) | `(c - o).abs()` |
| body fraction of range | `(c - o).abs() / (h - l).clip(lower_bound=1e-9)` |
| body midpoint | `(o + c) / 2` |
| gap up / down vs prior close | `o > L("close", k+1)` / `o < L("close", k+1)` |

Guard every division by range with `.clip(lower_bound=1e-9)` — a flat bar has range 0.

Helper builders (compose these; they keep masks readable):

```python
def bull(k):       return L("close", k) > L("open", k)
def bear(k):       return L("close", k) < L("open", k)
def rng(k):        return (L("high", k) - L("low", k)).clip(lower_bound=1e-9)
def body(k):       return (L("close", k) - L("open", k)).abs()
def body_frac(k):  return body(k) / rng(k)
def upper_sh(k):   return L("high", k) - pl.max_horizontal(L("open", k), L("close", k))
def lower_sh(k):   return pl.min_horizontal(L("open", k), L("close", k)) - L("low", k)
def long_body(k, frac=0.5):  return body_frac(k) >= frac          # marubozu-ish at frac~0.8
def small_body(k, frac=0.1): return body_frac(k) <= frac          # doji at frac~0.05
def near_high(k, frac=0.3):  return upper_sh(k) <= frac * rng(k)   # closes near the top
def near_low(k, frac=0.3):   return lower_sh(k) <= frac * rng(k)   # opens/closes near the bottom
```

## Multi-bar comparison idioms

```python
higher_close = lambda a, b: L("close", a) > L("close", b)          # bar a closes above bar b
higher_open  = lambda a, b: L("open", a)  > L("open", b)
opens_in_body= lambda a, b: (L("open", a) >= pl.min_horizontal(L("open", b), L("close", b))) \
                          & (L("open", a) <= pl.max_horizontal(L("open", b), L("close", b)))
bull_engulf  = lambda a, b: (L("open", a) <= L("close", b)) & (L("close", a) >= L("open", b))  # body of a swallows body of b
bear_engulf  = lambda a, b: (L("open", a) >= L("close", b)) & (L("close", a) <= L("open", b))
closes_above_mid = lambda a, b: L("close", a) > (L("open", b) + L("close", b)) / 2
```

These are conveniences — if a pattern needs a relationship not listed, write it directly
from the primitives. The grammar is open-ended by design.

## Translating a request into a mask

**Named pattern** → use its standard candlestick definition. State it explicitly. Most
canonical patterns decompose into: (1) a shape constraint per bar (bull/bear, body size,
shadow position) and (2) relationships between consecutive bars (higher/lower closes,
gaps, engulfing, opens-within-body).

**Described pattern** → parse the description into the same two layers:
1. For each candle named in the description, write its per-bar shape constraints.
2. Write the bar-to-bar relationships ("closes above the first candle's midpoint" →
   `closes_above_mid(0, 2)`).
Combine all constraints with `&`. Disclose the resulting definition in the report.

**Directional intent** decides what counts as a "win" in the screen:
- bullish pattern (reversal-up or bullish continuation) → win = next bar **up** → `WIN_DIR = 1`
- bearish pattern → win = next bar **down** → `WIN_DIR = -1`
If a name is directionally neutral (e.g. a bare doji), default `WIN_DIR = 1` and say so.

## The strictness ladder (the most important judgment)

Faithful textbook definitions (long bodies + tiny shadows + opens-within-body) are
**rare** — often too rare for any single stock to accumulate a rankable sample. Empirically
on this universe, strict three-white-soldiers yields no stock with even 10 occurrences.
So translate at a **disclosed** strictness, and be ready to relax:

1. **Strict** — every textbook clause (shape + sequence + body + shadow). Most faithful,
   fewest hits; frequently pooled-only.
2. **Standard** — shape + core sequence + the defining structural clause (e.g.
   opens-within-prior-body), but no hard body/shadow thresholds. Usually gives rankable
   per-stock samples.
3. **Relaxed** — the core sequence only (e.g. "three rising bullish bars"). Largest
   sample, weakest fidelity; watch that its edge over baseline hasn't vanished.

Default to **Standard**. If it is too rare to rank, drop to Relaxed *and disclose it*; if
the user asked for the textbook pattern, present **Strict pooled stats** plus a Standard
ranking, and explain the trade-off. Never silently widen or narrow a definition.

## Worked examples (method illustrations — not a fixed list)

### Three White Soldiers (3-bar, bullish) — the validated anchor
Definition: three consecutive bullish bars, each closing higher and opening higher than
the last, each opening within the prior bar's real body (no gap above prior close).

```python
staircase = (
    bull(0) & bull(1) & bull(2)
    & higher_close(0, 1) & higher_close(1, 2)
    & higher_open(0, 1)  & higher_open(1, 2)
)
within   = (L("open", 0) <= L("close", 1)) & (L("open", 1) <= L("close", 2))
mask_standard = staircase & within                                  # "Standard" rung
mask_strict   = mask_standard & long_body(0, 1/3) & long_body(1, 1/3) & long_body(2, 1/3)
WIN_DIR = 1
```
Regression anchor (run on `1d`, horizon 1, as of mid-2026, 177 symbols): universe baseline
next-day up ≈ **47.6%**. `mask_standard` ≈ **1793** signals, pooled win ≈ **50.6%**, ~**89**
stocks with ≥10 occurrences, ranking led by **ADANIENSOL.NS 73.1% (19/26)**. `mask_strict`
≈ **727** signals, pooled win ≈ **53.6%**, led by **ADANIENSOL.NS 92.9% (13/14)**. A fresh
run should reproduce these closely (small drift as new bars arrive). The bearish mirror,
**Three Black Crows**, is the same with `bull→bear`, `higher→lower`, `WIN_DIR = -1`.

### Bullish Engulfing (2-bar, bullish)
A bearish bar, then a bullish bar whose body engulfs it.
```python
mask = bear(1) & bull(0) & bull_engulf(0, 1)
WIN_DIR = 1
```

### Hammer (1-bar, bullish reversal)
Small body near the top, long lower shadow (≥2× body), little upper shadow.
```python
mask = (lower_sh(0) >= 2 * body(0)) & (upper_sh(0) <= body(0)) & (body_frac(0) <= 0.4)
WIN_DIR = 1
```

### Doji (1-bar, neutral)
Open ≈ close (tiny body relative to range).
```python
mask = small_body(0, 0.05)
WIN_DIR = 1   # neutral; disclose the assumption
```

### Morning Star (3-bar, bullish reversal)
Long bearish bar; a small-bodied middle bar gapping below it; a bullish bar closing back
above the first bar's midpoint.
```python
mask = (
    bear(2) & long_body(2, 0.5)
    & small_body(1, 0.3) & (pl.max_horizontal(L("open",1), L("close",1)) < L("close",2))
    & bull(0) & closes_above_mid(0, 2)
)
WIN_DIR = 1
```

### A described / custom pattern (shows the method)
Request: *"two red candles, then a big green candle that opens below the prior close and
closes above the open of the first red candle."*
```python
mask = (
    bear(2) & bear(1)
    & bull(0) & long_body(0, 0.5)
    & (L("open", 0) < L("close", 1))            # opens below prior close
    & (L("close", 0) > L("open", 2))            # closes above the first red's open
)
WIN_DIR = 1
```

Whatever the request, the recipe is the same: per-bar shape constraints `&` bar-to-bar
relationships, built from the primitives above, at a disclosed strictness. Hand the
finished `mask` and `WIN_DIR` to `screen-procedure.md`.
