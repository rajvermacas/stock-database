from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum

from stock_data.pullback.models import ScreenResult, StockDecision


def render_json(value: ScreenResult | StockDecision) -> str:
    return json.dumps(asdict(value), default=_json_default, sort_keys=True)


def render_markdown(result: ScreenResult) -> str:
    lines = [
        f"# Adaptive Pullback Screen ({result.as_of.isoformat()})",
        "",
        "Every setup is learned per stock. Executed entries use the next-bar open "
        "with a fixed 3% stop.",
        "",
    ]
    for decision in result.ranked:
        lines.append(_decision_line(decision))
    if not result.ranked:
        lines.append("No stock-specific setup beat abstention.")
    lines.extend(
        [
            "",
            f"Excluded: {len(result.excluded)}",
            f"Prefilter rejected: {len(result.prefilter_rejections)}",
            f"Abstained: {len(result.abstained)}",
        ]
    )
    return "\n".join(lines)


def _decision_line(decision: StockDecision) -> str:
    parameter = decision.parameter_set
    horizon = parameter.horizon_bars if parameter else "n/a"
    target = parameter.target if parameter else "n/a"
    return (
        f"- **{decision.symbol} — {decision.decision.value.upper()}**: "
        f"{decision.reason}; learned horizon {horizon}, learned target {target}; "
        f"entry {'pending next-bar open' if decision.entry_price is None else decision.entry_price}"
    )


def _json_default(value):
    if isinstance(value, (datetime, Enum)):
        return value.isoformat() if isinstance(value, datetime) else value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")
