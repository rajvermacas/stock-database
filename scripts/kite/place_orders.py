from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from stock_data.logging_config import configure_logging

from .client import KiteAuthError, build_client, verify_token
from .credentials import KiteCredentialError
from .orders import KiteOrderSpecError, load_orders
from .placement import format_summary, run_batch

LOG_DIR = Path(__file__).resolve().parent / "logs"
logger = logging.getLogger("stock_data.kite.place_orders")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Place a batch of Kite orders from a JSON file."
    )
    parser.add_argument(
        "--orders", required=True, type=Path, help="path to the orders JSON file"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging(LOG_DIR)
    args = _parse_args(argv)
    try:
        kite = build_client()
        verify_token(kite)
        orders = load_orders(args.orders)
    except (KiteCredentialError, KiteAuthError, KiteOrderSpecError) as exc:
        logger.error("Setup failed, no orders placed: %s", exc)
        return 2
    results = run_batch(kite, orders)
    print(format_summary(results))
    failed = [r for r in results if not r.ok]
    if failed:
        logger.error("%d of %d orders failed.", len(failed), len(results))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
