from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path


class LoggingConfigError(OSError):
    """Raised when application logging cannot be initialized."""


def configure_logging(log_dir: Path) -> Path:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"stock-data-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.log"
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError as exc:
        raise LoggingConfigError(f"Unable to initialize logs in {log_dir}: {exc}") from exc
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger = logging.getLogger("stock_data")
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return log_path

