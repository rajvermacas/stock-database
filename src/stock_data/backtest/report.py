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

PCT_COLS = {
    "stoploss_pct",
    "target_pct",
    "train_cagr",
    "test_cagr",
    "train_max_dd",
    "test_max_dd",
    "train_winrate",
    "test_winrate",
    "test_avg_win_pct",
    "test_avg_loss_pct",
}


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
    headers = table.columns
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in table.iter_rows(named=True):
        cells = []
        for h in headers:
            v = row[h]
            if isinstance(v, float):
                cells.append(f"{v * 100:.1f}%" if h in PCT_COLS else f"{v:.2f}")
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
