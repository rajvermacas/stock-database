from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from kiteconnect import KiteConnect

logger = logging.getLogger("stock_data.kite.auth")


def build_login_url(api_key: str) -> str:
    return KiteConnect(api_key=api_key).login_url()


def extract_request_token(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("Empty request token / redirect URL.")
    if "request_token=" in raw:
        tokens = parse_qs(urlparse(raw).query).get("request_token")
        if not tokens:
            raise ValueError(f"No request_token found in: {raw}")
        return tokens[0]
    return raw


def generate_access_token(api_key: str, api_secret: str, request_token: str) -> str:
    kite = KiteConnect(api_key=api_key)
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("generate_session returned no access_token.")
    logger.info("Generated new access token via generate_session.")
    return access_token
