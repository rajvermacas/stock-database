from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from kiteconnect.exceptions import KiteException
from stock_data.logging_config import configure_logging

from .auth import build_login_url, extract_request_token, generate_access_token
from .credentials import KiteCredentialError, load_credentials, write_access_token

LOG_DIR = Path(__file__).resolve().parent / "logs"
logger = logging.getLogger("stock_data.kite.login")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and cache a daily Kite access token."
    )
    parser.add_argument(
        "--request-token",
        help="request_token (or full redirect URL) from the Kite login redirect",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging(LOG_DIR)
    args = _parse_args(argv)
    try:
        creds = load_credentials()
        print("Open this URL, log in, and copy the request_token from the redirect:")
        print("  " + build_login_url(creds.api_key))
        raw = args.request_token or input(
            "Paste request_token (or full redirect URL): "
        )
        request_token = extract_request_token(raw)
        access_token = generate_access_token(
            creds.api_key, creds.api_secret, request_token
        )
        write_access_token(access_token)
    except (KiteCredentialError, ValueError, KiteException) as exc:
        logger.error("Login failed: %s", exc)
        return 2
    print("Access token cached. You can now place orders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
