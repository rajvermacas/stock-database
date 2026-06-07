import logging
from pathlib import Path

from stock_data.logging_config import configure_logging


def test_configure_logging_creates_file_without_duplicate_handlers(tmp_path: Path) -> None:
    first = configure_logging(tmp_path)
    second = configure_logging(tmp_path)
    assert first.exists()
    assert second.exists()
    assert len(logging.getLogger("stock_data").handlers) == 2

