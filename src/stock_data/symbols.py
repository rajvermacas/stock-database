from __future__ import annotations

import csv
from pathlib import Path


class SymbolFileError(ValueError):
    """Raised when a symbol CSV is invalid."""


def load_symbols(path: Path) -> list[str]:
    try:
        with path.open(encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None or "symbol" not in reader.fieldnames:
                raise SymbolFileError(f"{path} must contain a 'symbol' column")
            symbols = [_read_symbol(row, path) for row in reader]
    except OSError as exc:
        raise SymbolFileError(f"Unable to read symbol file {path}: {exc}") from exc
    if not symbols:
        raise SymbolFileError(f"{path} contains no symbols")
    if len(symbols) != len(set(symbols)):
        raise SymbolFileError(f"{path} contains duplicate symbols")
    return symbols


def _read_symbol(row: dict[str, str | None], path: Path) -> str:
    symbol = (row.get("symbol") or "").strip()
    if not symbol:
        raise SymbolFileError(f"{path} contains a blank symbol")
    return symbol
