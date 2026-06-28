# Kite Connect Order-Placement Script Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to carry out this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A self-contained `scripts/kite/` package with two commands — a daily login helper that caches the Kite access token, and a `place_orders` runner that validates a JSON file of orders (regular / AMO / GTT-single / GTT-OCO) and places each on Zerodha via the `kiteconnect` SDK.

**Approach:** Build small single-responsibility modules (credentials, auth, client, orders schema, placement) plus two thin `argparse` entry points run with `python -m`. Strict pydantic validation and detailed logging throughout; no dry-run or confirmation (place immediately); continue-on-error batch with exit codes 0/1/2. Every module ships mocked unit tests so nothing hits the real broker. `src/` is never modified.

**Tools / Inputs:** Python 3.12, `uv`, `kiteconnect>=5.2,<6`, `pydantic` v2, `pytest` + `pytest-mock`, `ruff`. Source spec: `docs/superpowers/specs/2026-06-28-kite-order-script-design.md`.

---

## Conventions for every task

- Run all commands from the repo root `/workspaces/stock-database`.
- Use the project venv: `.venv/bin/python`.
- Intra-package imports use **relative** form (`from .credentials import ...`); both entry points run as modules (`python -m scripts.kite.<name>`).
- Loggers are named `stock_data.kite.<module>` so they inherit handlers from the reused `configure_logging`.
- Keep every file < 800 lines and every function < 80 lines (all files here are far smaller).
- Do **not** stage or commit unrelated working-tree changes; each task's commit lists exact paths.

---

### Task 1: Project setup — dependency, gitignore, package skeleton, pytest path

**Inputs/Outputs:**
- Modify: `pyproject.toml` (add dependency + `pythonpath`)
- Modify: `.gitignore`
- Create: `scripts/kite/__init__.py`
- Done-check: `kiteconnect` imports and prints a 5.x version

- [ ] **Step 1: Add the dependency**

```bash
uv add 'kiteconnect>=5.2,<6'
```

This updates `pyproject.toml` `[project.dependencies]`, refreshes `uv.lock`, and installs into `.venv`.

- [ ] **Step 2: Verify the SDK installs on Python 3.12**

```bash
.venv/bin/python -c "import kiteconnect; print(kiteconnect.__version__)"
```
Expected: a version line like `5.2.0`. If `uv add` fails on `requires-python`, stop and report — do not pin an older major or work around it silently.

- [ ] **Step 3: Enable `scripts.*` imports for pytest**

In `pyproject.toml`, change the pytest section from:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```
to:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 4: Add .gitignore entries**

Append to `.gitignore`:
```
scripts/kite/secrets/
scripts/kite/logs/
```

- [ ] **Step 5: Create the package marker**

Create `scripts/kite/__init__.py`:
```python
"""Kite Connect order-placement package (daily login helper + batch order placer)."""
```

- [ ] **Step 6: Verify pytest still green (no regressions)**

```bash
.venv/bin/python -m pytest -q
```
Expected: the suite runs and collects (pre-existing failures noted in project memory about `.agents/skills` vs `.claude/skills` are unrelated to this work and acceptable).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore scripts/kite/__init__.py
git commit -m "chore(kite): add kiteconnect dep, gitignore, package skeleton"
```

---

### Task 2: `credentials.py` — load keys + token cache

**Inputs/Outputs:**
- Create: `scripts/kite/credentials.py`
- Create: `tests/test_kite_credentials.py`
- Done-check: `pytest tests/test_kite_credentials.py` PASS

- [ ] **Step 1: Write `scripts/kite/credentials.py`**

```python
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
        raise KiteCredentialError(
            f"Unable to read {CREDENTIALS_FILE}: {exc}"
        ) from exc
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
    logger.info("Cached access token to %s (generated_at=%s)", TOKEN_FILE, payload["generated_at"])


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
```

- [ ] **Step 2: Write `tests/test_kite_credentials.py`**

```python
from __future__ import annotations

import pytest

from scripts.kite import credentials
from scripts.kite.credentials import (
    KiteCredentialError,
    load_credentials,
    read_access_token,
    write_access_token,
)


def test_load_credentials_ok(tmp_path, monkeypatch):
    cred_file = tmp_path / "credentials.toml"
    cred_file.write_text('api_key = "k"\napi_secret = "s"\n', encoding="utf-8")
    monkeypatch.setattr(credentials, "CREDENTIALS_FILE", cred_file)
    creds = load_credentials()
    assert creds.api_key == "k"
    assert creds.api_secret == "s"


def test_load_credentials_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "CREDENTIALS_FILE", tmp_path / "nope.toml")
    with pytest.raises(KiteCredentialError):
        load_credentials()


def test_load_credentials_missing_key(tmp_path, monkeypatch):
    cred_file = tmp_path / "credentials.toml"
    cred_file.write_text('api_key = "k"\n', encoding="utf-8")
    monkeypatch.setattr(credentials, "CREDENTIALS_FILE", cred_file)
    with pytest.raises(KiteCredentialError):
        load_credentials()


def test_token_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "SECRETS_DIR", tmp_path)
    monkeypatch.setattr(credentials, "TOKEN_FILE", tmp_path / "access_token.json")
    write_access_token("tok123")
    assert read_access_token() == "tok123"


def test_read_token_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "TOKEN_FILE", tmp_path / "absent.json")
    with pytest.raises(KiteCredentialError):
        read_access_token()
```

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -m pytest tests/test_kite_credentials.py -v
```
Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add scripts/kite/credentials.py tests/test_kite_credentials.py
git commit -m "feat(kite): credentials + access-token cache loader"
```

---

### Task 3: `orders.py` — unified pydantic schema + JSON loader

**Inputs/Outputs:**
- Create: `scripts/kite/orders.py`
- Create: `tests/test_kite_orders.py`
- Done-check: `pytest tests/test_kite_orders.py` PASS

- [ ] **Step 1: Write `scripts/kite/orders.py`**

```python
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

logger = logging.getLogger("stock_data.kite.orders")

Exchange = Literal["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "BCD"]
Product = Literal["CNC", "MIS", "NRML"]
Side = Literal["BUY", "SELL"]

# order_type -> (price required?, trigger_price required?)
_PRICE_RULES = {
    "MARKET": (False, False),
    "LIMIT": (True, False),
    "SL": (True, True),
    "SL-M": (False, True),
}


class KiteOrderSpecError(ValueError):
    """Raised when the orders JSON is missing, malformed, or invalid."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RegularOrder(StrictModel):
    type: Literal["regular", "amo"]
    exchange: Exchange
    tradingsymbol: str = Field(min_length=1)
    transaction_type: Side
    quantity: int = Field(gt=0)
    product: Product
    order_type: Literal["MARKET", "LIMIT", "SL", "SL-M"]
    price: float | None = Field(default=None, gt=0)
    trigger_price: float | None = Field(default=None, gt=0)
    validity: Literal["DAY", "IOC"]
    tag: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _check_price_and_product(self) -> "RegularOrder":
        need_price, need_trigger = _PRICE_RULES[self.order_type]
        if need_price is not (self.price is not None):
            raise ValueError(
                f"{self.order_type} order: price must be "
                f"{'set' if need_price else 'omitted'}"
            )
        if need_trigger is not (self.trigger_price is not None):
            raise ValueError(
                f"{self.order_type} order: trigger_price must be "
                f"{'set' if need_trigger else 'omitted'}"
            )
        if self.product == "CNC" and self.exchange not in ("NSE", "BSE"):
            raise ValueError(f"CNC is only valid on NSE/BSE, not {self.exchange}")
        return self


class GttLeg(StrictModel):
    transaction_type: Side
    quantity: int = Field(gt=0)
    product: Product
    price: float = Field(gt=0)


class GttOrder(StrictModel):
    type: Literal["gtt"]
    trigger_type: Literal["single", "oco"]
    exchange: Exchange
    tradingsymbol: str = Field(min_length=1)
    last_price: float = Field(gt=0)
    trigger_values: list[float]
    legs: list[GttLeg]

    @model_validator(mode="after")
    def _check_cardinality(self) -> "GttOrder":
        expected = 1 if self.trigger_type == "single" else 2
        if len(self.trigger_values) != expected:
            raise ValueError(
                f"{self.trigger_type} GTT needs {expected} trigger_values, "
                f"got {len(self.trigger_values)}"
            )
        if len(self.legs) != expected:
            raise ValueError(
                f"{self.trigger_type} GTT needs {expected} legs, got {len(self.legs)}"
            )
        if any(v <= 0 for v in self.trigger_values):
            raise ValueError("trigger_values must be positive")
        if self.trigger_type == "oco" and not (
            self.trigger_values[0] < self.trigger_values[1]
        ):
            raise ValueError(
                f"OCO trigger_values must be strictly ascending, got {self.trigger_values}"
            )
        return self


Order = Annotated[Union[RegularOrder, GttOrder], Field(discriminator="type")]


class OrdersFile(StrictModel):
    orders: list[Order] = Field(min_length=1)


def load_orders(path: Path) -> list[RegularOrder | GttOrder]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KiteOrderSpecError(f"Unable to read orders file {path}: {exc}") from exc
    try:
        parsed = OrdersFile.model_validate(raw)
    except ValidationError as exc:
        raise KiteOrderSpecError(f"Invalid orders in {path}: {exc}") from exc
    logger.info("Loaded %d orders from %s", len(parsed.orders), path)
    return list(parsed.orders)
```

- [ ] **Step 2: Write `tests/test_kite_orders.py`**

```python
from __future__ import annotations

import json

import pytest

from scripts.kite.orders import KiteOrderSpecError, load_orders


def _write(tmp_path, payload):
    p = tmp_path / "orders.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_valid_orders_parse(tmp_path):
    payload = {
        "orders": [
            {
                "type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
                "transaction_type": "BUY", "quantity": 1, "product": "CNC",
                "order_type": "MARKET", "validity": "DAY",
            },
            {
                "type": "gtt", "trigger_type": "oco", "exchange": "NSE",
                "tradingsymbol": "HDFCBANK", "last_price": 1600.0,
                "trigger_values": [1450.0, 1750.0],
                "legs": [
                    {"transaction_type": "SELL", "quantity": 5,
                     "product": "CNC", "price": 1450.0},
                    {"transaction_type": "SELL", "quantity": 5,
                     "product": "CNC", "price": 1750.0},
                ],
            },
        ]
    }
    orders = load_orders(_write(tmp_path, payload))
    assert len(orders) == 2
    assert orders[0].type == "regular"
    assert orders[1].trigger_type == "oco"


@pytest.mark.parametrize(
    "order",
    [
        {"type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
         "transaction_type": "BUY", "quantity": 1, "product": "CNC",
         "order_type": "MARKET", "price": 100.0, "validity": "DAY"},
        {"type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
         "transaction_type": "BUY", "quantity": 1, "product": "CNC",
         "order_type": "LIMIT", "validity": "DAY"},
        {"type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
         "transaction_type": "BUY", "quantity": 0, "product": "CNC",
         "order_type": "MARKET", "validity": "DAY"},
        {"type": "regular", "exchange": "NFO", "tradingsymbol": "X",
         "transaction_type": "BUY", "quantity": 1, "product": "CNC",
         "order_type": "MARKET", "validity": "DAY"},
        {"type": "gtt", "trigger_type": "oco", "exchange": "NSE",
         "tradingsymbol": "X", "last_price": 100.0, "trigger_values": [90.0],
         "legs": [{"transaction_type": "BUY", "quantity": 1,
                   "product": "CNC", "price": 90.0}]},
        {"type": "gtt", "trigger_type": "oco", "exchange": "NSE",
         "tradingsymbol": "X", "last_price": 100.0,
         "trigger_values": [110.0, 90.0],
         "legs": [{"transaction_type": "SELL", "quantity": 1,
                   "product": "CNC", "price": 110.0},
                  {"transaction_type": "SELL", "quantity": 1,
                   "product": "CNC", "price": 90.0}]},
    ],
)
def test_invalid_orders_raise(tmp_path, order):
    with pytest.raises(KiteOrderSpecError):
        load_orders(_write(tmp_path, {"orders": [order]}))


def test_unknown_key_rejected(tmp_path):
    order = {
        "type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
        "transaction_type": "BUY", "quantity": 1, "product": "CNC",
        "order_type": "MARKET", "validity": "DAY", "bogus": 1,
    }
    with pytest.raises(KiteOrderSpecError):
        load_orders(_write(tmp_path, {"orders": [order]}))


def test_empty_orders_rejected(tmp_path):
    with pytest.raises(KiteOrderSpecError):
        load_orders(_write(tmp_path, {"orders": []}))
```

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -m pytest tests/test_kite_orders.py -v
```
Expected: all passed (1 valid + 6 invalid params + unknown-key + empty).

- [ ] **Step 4: Commit**

```bash
git add scripts/kite/orders.py tests/test_kite_orders.py
git commit -m "feat(kite): unified order schema + JSON loader"
```

---

### Task 4: `auth.py` — login URL + access-token generation

**Inputs/Outputs:**
- Create: `scripts/kite/auth.py`
- Create: `tests/test_kite_auth.py`
- Done-check: `pytest tests/test_kite_auth.py` PASS

- [ ] **Step 1: Write `scripts/kite/auth.py`**

```python
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
```

- [ ] **Step 2: Write `tests/test_kite_auth.py`**

```python
from __future__ import annotations

import pytest

from scripts.kite import auth
from scripts.kite.auth import extract_request_token, generate_access_token


def test_extract_bare_token():
    assert extract_request_token("  abc123 ") == "abc123"


def test_extract_from_url():
    url = "https://127.0.0.1/?request_token=xyz789&action=login&status=success"
    assert extract_request_token(url) == "xyz789"


def test_extract_empty_raises():
    with pytest.raises(ValueError):
        extract_request_token("   ")


def test_generate_access_token(mocker):
    fake = mocker.Mock()
    fake.generate_session.return_value = {"access_token": "AT"}
    mocker.patch.object(auth, "KiteConnect", return_value=fake)
    token = generate_access_token("k", "s", "rt")
    assert token == "AT"
    fake.generate_session.assert_called_once_with("rt", api_secret="s")
```

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -m pytest tests/test_kite_auth.py -v
```
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add scripts/kite/auth.py tests/test_kite_auth.py
git commit -m "feat(kite): login URL + access-token generation"
```

---

### Task 5: `client.py` — authenticated client + token pre-flight

**Inputs/Outputs:**
- Create: `scripts/kite/client.py`
- Create: `tests/test_kite_client.py`
- Done-check: `pytest tests/test_kite_client.py` PASS

- [ ] **Step 1: Write `scripts/kite/client.py`**

```python
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
    logger.info("Access token verified for user: %s", profile.get("user_id", "<unknown>"))
```

- [ ] **Step 2: Write `tests/test_kite_client.py`**

```python
from __future__ import annotations

import pytest
from kiteconnect.exceptions import TokenException

from scripts.kite import client
from scripts.kite.client import KiteAuthError, build_client, verify_token


def test_build_client_sets_token(mocker):
    mocker.patch.object(client, "load_credentials", return_value=mocker.Mock(api_key="k"))
    mocker.patch.object(client, "read_access_token", return_value="AT")
    fake = mocker.Mock()
    mocker.patch.object(client, "KiteConnect", return_value=fake)
    result = build_client()
    assert result is fake
    fake.set_access_token.assert_called_once_with("AT")


def test_verify_token_ok(mocker):
    kite = mocker.Mock()
    kite.profile.return_value = {"user_id": "AB1234"}
    verify_token(kite)  # must not raise


def test_verify_token_expired(mocker):
    kite = mocker.Mock()
    kite.profile.side_effect = TokenException("bad token")
    with pytest.raises(KiteAuthError):
        verify_token(kite)
```

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -m pytest tests/test_kite_client.py -v
```
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add scripts/kite/client.py tests/test_kite_client.py
git commit -m "feat(kite): authenticated client + token pre-flight"
```

---

### Task 6: `placement.py` — dispatch + batch runner + summary

**Inputs/Outputs:**
- Create: `scripts/kite/placement.py`
- Create: `tests/test_kite_placement.py`
- Done-check: `pytest tests/test_kite_placement.py` PASS

- [ ] **Step 1: Write `scripts/kite/placement.py`**

```python
from __future__ import annotations

import logging
from dataclasses import dataclass

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

from .orders import GttOrder, RegularOrder

logger = logging.getLogger("stock_data.kite.placement")

# our trigger_type label -> SDK trigger_type value
_GTT_TYPE = {"single": "single", "oco": "two-leg"}


@dataclass(frozen=True)
class OrderResult:
    index: int
    kind: str
    tradingsymbol: str
    side: str
    quantity: int
    ok: bool
    reference: str  # order_id / trigger_id on success, else error message


def _place_regular(kite: KiteConnect, order: RegularOrder) -> str:
    order_id = kite.place_order(
        variety=order.type,
        exchange=order.exchange,
        tradingsymbol=order.tradingsymbol,
        transaction_type=order.transaction_type,
        quantity=order.quantity,
        product=order.product,
        order_type=order.order_type,
        price=order.price,
        trigger_price=order.trigger_price,
        validity=order.validity,
        tag=order.tag,
    )
    return str(order_id)


def _place_gtt(kite: KiteConnect, order: GttOrder) -> str:
    legs = [
        {
            "transaction_type": leg.transaction_type,
            "quantity": leg.quantity,
            "order_type": "LIMIT",
            "product": leg.product,
            "price": leg.price,
        }
        for leg in order.legs
    ]
    result = kite.place_gtt(
        trigger_type=_GTT_TYPE[order.trigger_type],
        tradingsymbol=order.tradingsymbol,
        exchange=order.exchange,
        trigger_values=order.trigger_values,
        last_price=order.last_price,
        orders=legs,
    )
    trigger_id = result["trigger_id"] if isinstance(result, dict) else result
    return str(trigger_id)


def place_one(kite: KiteConnect, order: RegularOrder | GttOrder) -> str:
    if isinstance(order, RegularOrder):
        return _place_regular(kite, order)
    if isinstance(order, GttOrder):
        return _place_gtt(kite, order)
    raise TypeError(f"Unknown order type: {type(order)!r}")


def _describe_side(order: RegularOrder | GttOrder) -> tuple[str, int]:
    if isinstance(order, RegularOrder):
        return order.transaction_type, order.quantity
    first = order.legs[0]
    return first.transaction_type, first.quantity


def run_batch(
    kite: KiteConnect, orders: list[RegularOrder | GttOrder]
) -> list[OrderResult]:
    results: list[OrderResult] = []
    total = len(orders)
    for index, order in enumerate(orders, start=1):
        side, qty = _describe_side(order)
        logger.info(
            "Placing %d/%d: %s %s %s x%d",
            index, total, order.type, side, order.tradingsymbol, qty,
        )
        try:
            reference = place_one(kite, order)
            logger.info("Order %d OK: %s -> %s", index, order.tradingsymbol, reference)
            ok, ref = True, reference
        except (KiteException, KeyError, ValueError, TypeError) as exc:
            logger.error("Order %d FAILED: %s -> %s", index, order.tradingsymbol, exc)
            ok, ref = False, str(exc)
        results.append(
            OrderResult(index, order.type, order.tradingsymbol, side, qty, ok, ref)
        )
    return results


def format_summary(results: list[OrderResult]) -> str:
    lines = ["", "Order placement summary:", "-" * 72]
    for r in results:
        status = "OK  " if r.ok else "FAIL"
        lines.append(
            f"  [{r.index}] {status} {r.kind:7} {r.side:4} "
            f"{r.tradingsymbol:14} x{r.quantity}  -> {r.reference}"
        )
    ok = sum(1 for r in results if r.ok)
    lines.append("-" * 72)
    lines.append(f"  {ok}/{len(results)} placed successfully")
    return "\n".join(lines)
```

- [ ] **Step 2: Write `tests/test_kite_placement.py`**

```python
from __future__ import annotations

from kiteconnect.exceptions import InputException

from scripts.kite.orders import GttOrder, RegularOrder
from scripts.kite.placement import format_summary, place_one, run_batch


def _regular(**kw):
    base = dict(
        type="regular", exchange="NSE", tradingsymbol="INFY",
        transaction_type="BUY", quantity=1, product="CNC",
        order_type="MARKET", validity="DAY",
    )
    base.update(kw)
    return RegularOrder(**base)


def _gtt_single():
    return GttOrder(
        type="gtt", trigger_type="single", exchange="NSE",
        tradingsymbol="RELIANCE", last_price=2900.0, trigger_values=[2700.0],
        legs=[{"transaction_type": "BUY", "quantity": 1,
               "product": "CNC", "price": 2700.0}],
    )


def _gtt_oco():
    return GttOrder(
        type="gtt", trigger_type="oco", exchange="NSE",
        tradingsymbol="HDFCBANK", last_price=1600.0,
        trigger_values=[1450.0, 1750.0],
        legs=[{"transaction_type": "SELL", "quantity": 5,
               "product": "CNC", "price": 1450.0},
              {"transaction_type": "SELL", "quantity": 5,
               "product": "CNC", "price": 1750.0}],
    )


def test_place_regular_amo_calls_place_order(mocker):
    kite = mocker.Mock()
    kite.place_order.return_value = "OID1"
    assert place_one(kite, _regular(type="amo")) == "OID1"
    kwargs = kite.place_order.call_args.kwargs
    assert kwargs["variety"] == "amo"
    assert kwargs["order_type"] == "MARKET"
    assert kwargs["product"] == "CNC"


def test_place_gtt_single_legs_are_limit(mocker):
    kite = mocker.Mock()
    kite.place_gtt.return_value = {"trigger_id": 555}
    assert place_one(kite, _gtt_single()) == "555"
    kwargs = kite.place_gtt.call_args.kwargs
    assert kwargs["trigger_type"] == "single"
    assert kwargs["orders"][0]["order_type"] == "LIMIT"


def test_place_gtt_oco_maps_two_leg_and_scalar_return(mocker):
    kite = mocker.Mock()
    kite.place_gtt.return_value = 777
    assert place_one(kite, _gtt_oco()) == "777"
    assert kite.place_gtt.call_args.kwargs["trigger_type"] == "two-leg"


def test_run_batch_continue_on_error(mocker):
    kite = mocker.Mock()
    kite.place_order.side_effect = ["OID1", InputException("bad")]
    results = run_batch(kite, [_regular(), _regular()])
    assert results[0].ok is True
    assert results[1].ok is False
    assert "1/2 placed successfully" in format_summary(results)
```

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -m pytest tests/test_kite_placement.py -v
```
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add scripts/kite/placement.py tests/test_kite_placement.py
git commit -m "feat(kite): order dispatch + continue-on-error batch runner"
```

---

### Task 7: `login.py` — daily login entry point

**Inputs/Outputs:**
- Create: `scripts/kite/login.py`
- Add tests to: `tests/test_kite_entrypoints.py` (created here; extended in Task 8)
- Done-check: `python -m scripts.kite.login --help` works; login test PASS

- [ ] **Step 1: Write `scripts/kite/login.py`**

```python
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
        raw = args.request_token or input("Paste request_token (or full redirect URL): ")
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
```

- [ ] **Step 2: Create `tests/test_kite_entrypoints.py` with the login test**

```python
from __future__ import annotations

from scripts.kite import login as lg


def test_login_happy_path(mocker):
    mocker.patch.object(lg, "configure_logging")
    mocker.patch.object(
        lg, "load_credentials",
        return_value=mocker.Mock(api_key="k", api_secret="s"),
    )
    mocker.patch.object(lg, "build_login_url", return_value="http://login")
    mocker.patch.object(lg, "generate_access_token", return_value="AT")
    write = mocker.patch.object(lg, "write_access_token")
    assert lg.main(["--request-token", "rt"]) == 0
    write.assert_called_once_with("AT")


def test_login_missing_credentials_returns_2(mocker):
    from scripts.kite.credentials import KiteCredentialError

    mocker.patch.object(lg, "configure_logging")
    mocker.patch.object(lg, "load_credentials", side_effect=KiteCredentialError("no creds"))
    assert lg.main(["--request-token", "rt"]) == 2
```

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -m scripts.kite.login --help
.venv/bin/python -m pytest tests/test_kite_entrypoints.py -v
```
Expected: `--help` prints usage and exits 0; both login tests pass.

- [ ] **Step 4: Commit**

```bash
git add scripts/kite/login.py tests/test_kite_entrypoints.py
git commit -m "feat(kite): daily login entry point"
```

---

### Task 8: `place_orders.py` — batch placement entry point

**Inputs/Outputs:**
- Create: `scripts/kite/place_orders.py`
- Modify: `tests/test_kite_entrypoints.py` (append place_orders tests)
- Done-check: `python -m scripts.kite.place_orders --help` works; exit-code tests PASS

- [ ] **Step 1: Write `scripts/kite/place_orders.py`**

```python
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
```

- [ ] **Step 2: Append place_orders tests to `tests/test_kite_entrypoints.py`**

Add these imports at the top (below the existing `from scripts.kite import login as lg`):
```python
from scripts.kite import place_orders as po
from scripts.kite.client import KiteAuthError
from scripts.kite.placement import OrderResult
```

Append these tests to the end of the file:
```python
def _patch_setup(mocker):
    mocker.patch.object(po, "configure_logging")
    mocker.patch.object(po, "build_client", return_value=mocker.Mock())
    mocker.patch.object(po, "verify_token")
    mocker.patch.object(po, "load_orders", return_value=["o1"])


def test_place_orders_all_ok(mocker, tmp_path):
    _patch_setup(mocker)
    mocker.patch.object(
        po, "run_batch",
        return_value=[OrderResult(1, "regular", "INFY", "BUY", 1, True, "OID1")],
    )
    assert po.main(["--orders", str(tmp_path / "o.json")]) == 0


def test_place_orders_partial_failure(mocker, tmp_path):
    _patch_setup(mocker)
    mocker.patch.object(
        po, "run_batch",
        return_value=[OrderResult(1, "regular", "INFY", "BUY", 1, False, "err")],
    )
    assert po.main(["--orders", str(tmp_path / "o.json")]) == 1


def test_place_orders_setup_failure(mocker, tmp_path):
    mocker.patch.object(po, "configure_logging")
    mocker.patch.object(po, "build_client", side_effect=KiteAuthError("no token"))
    assert po.main(["--orders", str(tmp_path / "o.json")]) == 2
```

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -m scripts.kite.place_orders --help
.venv/bin/python -m pytest tests/test_kite_entrypoints.py -v
```
Expected: `--help` prints usage; all 5 entry-point tests pass (2 login + 3 place_orders).

- [ ] **Step 4: Commit**

```bash
git add scripts/kite/place_orders.py tests/test_kite_entrypoints.py
git commit -m "feat(kite): batch order-placement entry point"
```

---

### Task 9: Example orders file + `COMMANDS.md`

**Inputs/Outputs:**
- Create: `scripts/kite/examples/orders.sample.json`
- Create: `scripts/kite/COMMANDS.md`
- Done-check: `load_orders` parses the sample → 4 orders

- [ ] **Step 1: Create `scripts/kite/examples/orders.sample.json`**

```json
{
  "orders": [
    {
      "type": "regular",
      "exchange": "NSE",
      "tradingsymbol": "INFY",
      "transaction_type": "BUY",
      "quantity": 1,
      "product": "CNC",
      "order_type": "MARKET",
      "validity": "DAY",
      "tag": "delivery-buy"
    },
    {
      "type": "amo",
      "exchange": "NSE",
      "tradingsymbol": "TCS",
      "transaction_type": "BUY",
      "quantity": 2,
      "product": "CNC",
      "order_type": "LIMIT",
      "price": 3500.0,
      "validity": "DAY"
    },
    {
      "type": "gtt",
      "trigger_type": "single",
      "exchange": "NSE",
      "tradingsymbol": "RELIANCE",
      "last_price": 2900.0,
      "trigger_values": [2700.0],
      "legs": [
        {"transaction_type": "BUY", "quantity": 1, "product": "CNC", "price": 2700.0}
      ]
    },
    {
      "type": "gtt",
      "trigger_type": "oco",
      "exchange": "NSE",
      "tradingsymbol": "HDFCBANK",
      "last_price": 1600.0,
      "trigger_values": [1450.0, 1750.0],
      "legs": [
        {"transaction_type": "SELL", "quantity": 5, "product": "CNC", "price": 1450.0},
        {"transaction_type": "SELL", "quantity": 5, "product": "CNC", "price": 1750.0}
      ]
    }
  ]
}
```

- [ ] **Step 2: Create `scripts/kite/COMMANDS.md`**

````markdown
# Kite Order Scripts — Commands

Two commands under `scripts/kite/`. Run them as modules from the repository root
so the package's internal imports resolve.

**Prerequisites**
- A Zerodha Kite Connect app (`api_key` + `api_secret`).
- A gitignored `scripts/kite/secrets/credentials.toml`:
  ```toml
  api_key = "your_api_key"
  api_secret = "your_api_secret"
  ```

## 1. `login` — mint the daily access token

Kite access tokens expire every morning; run this once per trading day.

```bash
.venv/bin/python -m scripts.kite.login
# non-interactive (bare token or full redirect URL):
.venv/bin/python -m scripts.kite.login --request-token "https://127.0.0.1/?request_token=abc123&action=login&status=success"
```

Sample output:
```
Open this URL, log in, and copy the request_token from the redirect:
  https://kite.zerodha.com/connect/login?api_key=xxxx&v=3
Paste request_token (or full redirect URL): abc123
Access token cached. You can now place orders.
```

Exit codes: `0` token cached · `2` credentials missing/invalid or login failed.

## 2. `place_orders` — place a batch of orders

```bash
.venv/bin/python -m scripts.kite.place_orders --orders scripts/kite/examples/orders.sample.json
```

`--orders` is required and points to a JSON file shaped like
`scripts/kite/examples/orders.sample.json`. Order kinds:

- `regular` / `amo` — `product: "CNC"` is a delivery order; `order_type: "MARKET"`
  is a market order; `LIMIT`/`SL`/`SL-M` need `price`/`trigger_price` per the rules.
- `gtt` — `trigger_type: "single"` (1 trigger, 1 leg) or `"oco"` (2 ascending
  triggers, 2 legs). GTT legs are always LIMIT.

Sample output:
```
INFO: Loaded 4 orders from scripts/kite/examples/orders.sample.json

Order placement summary:
------------------------------------------------------------------------
  [1] OK   regular BUY  INFY           x1  -> 250628000000001
  [2] OK   amo     BUY  TCS            x2  -> 250628000000002
  [3] OK   gtt     BUY  RELIANCE       x1  -> 123456
  [4] FAIL gtt     SELL HDFCBANK       x5  -> InputException: ...
------------------------------------------------------------------------
  3/4 placed successfully
```

Exit codes: `0` all placed · `1` ≥1 order failed · `2` setup failure
(bad credentials, expired token, or invalid orders JSON — nothing attempted).

There is no dry-run and no confirmation prompt: a valid file is placed immediately.
Logs are written under `scripts/kite/logs/`.
````

- [ ] **Step 3: Verify the sample parses**

```bash
.venv/bin/python -c "from scripts.kite.orders import load_orders; print(len(load_orders('scripts/kite/examples/orders.sample.json')))"
```
Expected: `4`

- [ ] **Step 4: Commit**

```bash
git add scripts/kite/examples/orders.sample.json scripts/kite/COMMANDS.md
git commit -m "docs(kite): sample orders file + COMMANDS.md"
```

---

### Task 10: Full verification — tests + lint + import smoke

**Inputs/Outputs:**
- Modify (if ruff reformats): files under `scripts/kite/` and `tests/test_kite_*.py`
- Done-check: full kite test suite green; ruff clean; both entry points import

- [ ] **Step 1: Run the full kite test suite**

```bash
.venv/bin/python -m pytest tests/test_kite_credentials.py tests/test_kite_orders.py tests/test_kite_auth.py tests/test_kite_client.py tests/test_kite_placement.py tests/test_kite_entrypoints.py -v
```
Expected: all pass (≈25 tests).

- [ ] **Step 2: Lint + format the new code**

```bash
.venv/bin/python -m ruff format scripts/kite tests/test_kite_credentials.py tests/test_kite_orders.py tests/test_kite_auth.py tests/test_kite_client.py tests/test_kite_placement.py tests/test_kite_entrypoints.py
.venv/bin/python -m ruff check scripts/kite tests/test_kite_credentials.py tests/test_kite_orders.py tests/test_kite_auth.py tests/test_kite_client.py tests/test_kite_placement.py tests/test_kite_entrypoints.py
```
Expected: format makes no/whitespace-only changes; `ruff check` reports `All checks passed!`. If `ruff check` flags an issue, fix it and re-run.

- [ ] **Step 3: Import smoke test for both entry points**

```bash
.venv/bin/python -m scripts.kite.login --help
.venv/bin/python -m scripts.kite.place_orders --help
```
Expected: both print usage and exit 0 (proves package imports resolve under `-m`).

- [ ] **Step 4: Confirm no full suite regression**

```bash
.venv/bin/python -m pytest -q
```
Expected: no NEW failures vs the Task 1 baseline (pre-existing skill-path failures remain, unrelated).

- [ ] **Step 5: Commit any formatting fixes**

```bash
git add scripts/kite tests/test_kite_credentials.py tests/test_kite_orders.py tests/test_kite_auth.py tests/test_kite_client.py tests/test_kite_placement.py tests/test_kite_entrypoints.py
git commit -m "chore(kite): ruff format/lint pass" || echo "nothing to commit"
```

---

## Manual end-to-end (user-run, optional, places REAL orders)

Not part of automated verification — there is no Kite sandbox, so this fires real
orders. Do at your discretion:

1. Put real `api_key`/`api_secret` in `scripts/kite/secrets/credentials.toml`.
2. `.venv/bin/python -m scripts.kite.login` and complete the Zerodha login.
3. Copy `orders.sample.json`, edit to a single tiny real order, and run
   `.venv/bin/python -m scripts.kite.place_orders --orders <your_file>.json`.
4. Confirm the order ID / trigger ID in the Kite web/app order book.

---

## Plan self-review

- **Spec coverage:** §4 layout → Tasks 1–9 (every file). §5 auth/credentials → Tasks 2 (credentials), 4 (auth), 5 (client pre-flight), 7 (login). §6 schema → Task 3. §7 placement/batch → Task 6. §8 logging/exit codes → Tasks 7–8 (reuse `configure_logging`, codes 0/1/2). §9 deps/gitignore → Task 1. §10 CLI + COMMANDS.md → Tasks 8–9. §11 tests → per-module tasks + Task 10. §12 out-of-scope → nothing built. §13 SDK reference → consumed in Tasks 4/5/6. No gaps.
- **Placeholder scan:** no TBD/TODO; every step has concrete content and a concrete done-check with expected output.
- **Naming/output consistency:** `KiteCredentialError`, `KiteAuthError`, `KiteOrderSpecError`, `OrderResult`, `RegularOrder`, `GttOrder`, `GttLeg`, `load_orders`, `build_client`, `verify_token`, `place_one`, `run_batch`, `format_summary`, `_GTT_TYPE`, and `LOG_DIR` are defined once and referenced identically across modules and tests. Token cache file `access_token.json` and `credentials.toml` names match across `credentials.py`, tests, and `COMMANDS.md`. The sample file path `scripts/kite/examples/orders.sample.json` is identical in Tasks 9 and the COMMANDS doc.
```