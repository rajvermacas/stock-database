from __future__ import annotations

import json
import logging
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("stock_data.kite.credentials")

SECRETS_DIR = Path(__file__).resolve().parent / "secrets"
CREDENTIALS_FILE = SECRETS_DIR / "credentials.toml"
TOKEN_FILE = SECRETS_DIR / "access_token.json"


class KiteCredentialError(RuntimeError):
    """Raised when Kite credentials or the cached access token are unavailable."""


@dataclass(frozen=True)
class Credentials:
    api_key: str
    api_secret: str


def load_credentials() -> Credentials:
    if not CREDENTIALS_FILE.exists():
        raise KiteCredentialError(
            f"Credentials file not found: {CREDENTIALS_FILE}. "
            "Create it with api_key and api_secret."
        )
    try:
        raw = tomllib.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise KiteCredentialError(f"Unable to read {CREDENTIALS_FILE}: {exc}") from exc
    api_key = raw.get("api_key")
    api_secret = raw.get("api_secret")
    if not api_key or not api_secret:
        raise KiteCredentialError(
            f"{CREDENTIALS_FILE} must define non-empty api_key and api_secret."
        )
    return Credentials(api_key=api_key, api_secret=api_secret)


def write_access_token(access_token: str) -> None:
    if not access_token:
        raise KiteCredentialError("Refusing to cache an empty access token.")
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": access_token,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    TOKEN_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(
        "Cached access token to %s (generated_at=%s)",
        TOKEN_FILE,
        payload["generated_at"],
    )


def read_access_token() -> str:
    if not TOKEN_FILE.exists():
        raise KiteCredentialError(
            f"No cached access token at {TOKEN_FILE}. Run: python -m scripts.kite.login"
        )
    try:
        payload = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KiteCredentialError(f"Unable to read {TOKEN_FILE}: {exc}") from exc
    access_token = payload.get("access_token")
    if not access_token:
        raise KiteCredentialError(f"{TOKEN_FILE} has no access_token; re-run login.")
    return access_token
