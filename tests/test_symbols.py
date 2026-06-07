from pathlib import Path

import pytest

from stock_data.symbols import SymbolFileError, load_symbols


def test_load_symbols_strips_and_preserves_order(tmp_path: Path) -> None:
    path = tmp_path / "symbols.csv"
    path.write_text("symbol\n RELIANCE.NS \nTCS.NS\n", encoding="utf-8")
    assert load_symbols(path) == ["RELIANCE.NS", "TCS.NS"]


@pytest.mark.parametrize(
    "content", ["ticker\nTCS.NS\n", "symbol\n\n", "symbol\nTCS.NS\nTCS.NS\n"]
)
def test_load_symbols_rejects_invalid_file(tmp_path: Path, content: str) -> None:
    path = tmp_path / "symbols.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SymbolFileError):
        load_symbols(path)
