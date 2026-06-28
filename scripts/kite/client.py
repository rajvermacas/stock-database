from __future__ import annotations

import logging

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException, TokenException

from .credentials import load_credentials, read_access_token

logger = logging.getLogger("stock_data.kite.client")


class KiteAuthError(RuntimeError):
    """Raised when the cached access token is missing or rejected by Kite."""


def build_client() -> KiteConnect:
    creds = load_credentials()
    access_token = read_access_token()
    kite = KiteConnect(api_key=creds.api_key)
    kite.set_access_token(access_token)
    return kite


def verify_token(kite: KiteConnect) -> None:
    try:
        profile = kite.profile()
    except TokenException as exc:
        raise KiteAuthError(
            "Cached access token is expired/invalid. "
            "Re-run: python -m scripts.kite.login"
        ) from exc
    except KiteException as exc:
        raise KiteAuthError(f"Could not verify token with Kite: {exc}") from exc
    logger.info(
        "Access token verified for user: %s", profile.get("user_id", "<unknown>")
    )
