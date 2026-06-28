# Kite Connect Order-Placement Script — Design Spec

- **Date:** 2026-06-28
- **Branch:** `feature/kite-order-script`
- **Status:** approved design, pre-implementation
- **Scope:** new self-contained package `scripts/kite/`; adds the `kiteconnect`
  dependency to `pyproject.toml`, `.gitignore` entries, and mocked tests under
  `tests/`. **`src/` is not touched.**

## 1. Problem / context

The repository is read-only market-data tooling (Yahoo → Parquet + TA-Lib
indicators). There is **no brokerage / order-placement capability and no secrets
handling at all** (no env vars, no credential file). The user wants to place
real orders on their own Zerodha account through the official Kite Connect 3 API
(`kiteconnect` Python SDK), driven from a script in `scripts/`:

1. Place orders of several kinds — after-market (AMO), GTT single, GTT OCO,
   market, and delivery (CNC).
2. Place **multiple** orders in one run.

This is the user's own account; Kite Connect is the sanctioned API for
automating it. The work moves the repo from read-only analytics into placing
real-money trades, so authentication, strict input validation, and detailed
logging are first-class concerns.

## 2. Goal / non-goals

**Goal:** two command-line entry points under a new `scripts/kite/` package —
one to mint the daily access token, one to read a JSON file of orders, validate
them strictly, and place each on Kite (regular / AMO / GTT-single / GTT-OCO,
covering market & delivery as parameter combinations), reporting per-order
results and a meaningful exit code.

**Non-goals (explicitly deferred):** modify/cancel orders, list/cancel GTTs,
order-status polling, positions/holdings/P&L, cover orders (CO), iceberg, TTL
validity, and any concurrency. **Place-only.** No dry-run preview and no
confirmation prompt (user decision — see §3). No changes to `src/` or the
existing `stock-data` CLI.

## 3. Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Auth model | **Separate login helper** caches the daily token; order script reads it | User pick — keeps each script single-purpose |
| Order input | **One JSON file**, `{ "orders": [ … ] }`, pydantic-validated | User pick — handles nested GTT/OCO legs cleanly |
| Order schema | **Unified** discriminated-union schema (full params) | User pick — DRY-er than 5 special-cased templates; covers MARKET/LIMIT/SL too |
| Guardrails | **None** — no dry-run, no confirmation; just place | User pick |
| Strict validation + detailed logging | **Kept** | Correctness / fail-fast (global rules) — not a "guardrail" |
| Code location | **New `scripts/kite/` package**, `src/` untouched | User pick |
| Batch failure policy | **Continue-on-error**, exit 1 on partial failure | Matches existing downloader precedent (README) |
| Credentials source | Gitignored `scripts/kite/secrets/credentials.toml` | Login helper needs `api_secret` repeatedly; file is simplest |
| Run style | `python -m scripts.kite.<entry>` | Correct way to run a multi-module package |
| Docs | New `scripts/kite/COMMANDS.md` | User pick; mirrors top-level `COMMANDS.md` |

## 4. File layout

```
scripts/kite/
  __init__.py
  credentials.py     # load api_key/api_secret + read/write cached access_token (fail-fast)
  auth.py            # build login URL; exchange request_token -> access_token (generate_session)
  client.py          # build an authenticated KiteConnect client; token pre-flight check
  orders.py          # pydantic order schema (unified) + load_orders(json_path)
  placement.py       # dispatch one order (place_order / place_gtt) + batch runner + summary
  login.py           # ENTRY: daily interactive login -> writes token cache
  place_orders.py    # ENTRY: load+validate JSON -> place batch -> summary -> exit code
  COMMANDS.md        # documents both commands (sample input/output/exit codes)
  examples/
    orders.sample.json   # committed sample: regular + AMO + GTT-single + GTT-OCO
  secrets/           # GITIGNORED: credentials.toml + access_token.json
  logs/              # GITIGNORED: run logs
```

Every file stays well under 800 lines; every function under 80 with a single
responsibility. Modules import each other via the package (relative imports);
both entry points are run with `python -m`.

## 5. Authentication & credentials

### 5.1 Credentials (`credentials.py`)

- Reads a **gitignored** `scripts/kite/secrets/credentials.toml`:

  ```toml
  api_key = "xxxxxxxx"
  api_secret = "yyyyyyyy"
  ```

- Both keys **required**; a missing file or missing/empty key raises a clear
  `KiteCredentialError` (no defaults, no fallback to env).
- Token cache helpers: `write_access_token(token: str)` and
  `read_access_token() -> str`. Cache file is gitignored
  `scripts/kite/secrets/access_token.json`:

  ```json
  { "access_token": "…", "generated_at": "2026-06-28T03:55:00+00:00" }
  ```

  `read_access_token` raises `KiteCredentialError` if the file is absent or
  malformed ("run `python -m scripts.kite.login` first").

### 5.2 Daily login (`auth.py` + `login.py`)

1. `login.py` loads `api_key`, builds `KiteConnect(api_key=…)`, prints
   `kite.login_url()`.
2. User opens the URL, logs into Zerodha, and is redirected to the app's
   registered redirect URL carrying `request_token=…`.
3. User supplies the request token — via `--request-token <tok>` **or** an
   interactive prompt (the prompt also accepts the full pasted redirect URL and
   extracts the `request_token` query param).
4. `auth.generate_access_token(api_key, api_secret, request_token)` calls
   `kite.generate_session(request_token, api_secret=api_secret)` and returns
   `data["access_token"]`.
5. `login.py` writes it via `write_access_token(...)` and logs success (token
   value itself is **not** logged).

### 5.3 Client + pre-flight (`client.py`)

- `build_client() -> KiteConnect`: load `api_key` + cached `access_token`,
  construct `KiteConnect`, `set_access_token(...)`.
- `verify_token(kite)`: one call to `kite.profile()`. On
  `kiteconnect.exceptions.TokenException` it raises `KiteAuthError`
  ("token expired/invalid — re-run login") so the batch aborts **before any
  order is placed**. Rationale: the Kite token silently dies each morning; the
  authoritative signal is an API rejection, not a clock guess (avoids guesswork
  per global rules).

## 6. Order JSON schema (`orders.py`)

`load_orders(path) -> list[Order]` reads the JSON, validates with pydantic
(`extra="forbid"`, so unknown keys fail), and raises `KiteOrderSpecError` on any
problem. Top level: `{ "orders": [ … ] }`, at least one order.

Each order is a **discriminated union on `type`**.

### 6.1 `type: "regular"` / `type: "amo"` (`RegularOrder`)

| Field | Type / values | Notes |
|---|---|---|
| `type` | `"regular"` \| `"amo"` | maps to Kite `variety` regular/amo |
| `exchange` | `NSE`/`BSE`/`NFO`/`BFO`/`CDS`/`MCX`/`BCD` | enum |
| `tradingsymbol` | non-empty str | |
| `transaction_type` | `BUY`/`SELL` | |
| `quantity` | int > 0 | |
| `product` | `CNC`/`MIS`/`NRML` | **CNC = delivery** |
| `order_type` | `MARKET`/`LIMIT`/`SL`/`SL-M` | |
| `price` | float > 0 \| omitted | per rules below |
| `trigger_price` | float > 0 \| omitted | per rules below |
| `validity` | `DAY`/`IOC` | TTL excluded (YAGNI) |
| `tag` | str ≤ 20 chars \| omitted | optional Kite order tag |

**Fail-fast validators** (`model_validator`, raise — never default):

| `order_type` | `price` | `trigger_price` |
|---|---|---|
| MARKET | forbidden | forbidden |
| LIMIT | required | forbidden |
| SL | required | required |
| SL-M | forbidden | required |

Plus: `CNC` only allowed on `NSE`/`BSE` (equity delivery). Other product/exchange
combinations pass through to Kite, which is authoritative.

### 6.2 `type: "gtt"` (`GttOrder`)

| Field | Type / values | Notes |
|---|---|---|
| `type` | `"gtt"` | |
| `trigger_type` | `single` \| `oco` | `oco` → SDK `"two-leg"` |
| `exchange` | exchange enum | |
| `tradingsymbol` | non-empty str | |
| `last_price` | float > 0 | LTP at creation (required by API) |
| `trigger_values` | list[float] | 1 for single; 2 **ascending** for OCO |
| `legs` | list[`GttLeg`] | 1 for single; 2 for OCO |

`GttLeg`: `{ transaction_type (BUY/SELL), quantity (int>0), product (CNC/MIS/NRML),
price (float>0) }`. **`order_type` is not a leg field** — Kite GTT legs are
always LIMIT, so the dispatcher fixes it to `LIMIT` (an invariant of the
protocol, not a defaulted input).

**Validators:** `single` ⇒ exactly 1 trigger value and 1 leg; `oco` ⇒ exactly 2
trigger values (strictly ascending) and 2 legs.

### 6.3 Example (`examples/orders.sample.json`)

```json
{
  "orders": [
    { "type": "regular", "exchange": "NSE", "tradingsymbol": "INFY",
      "transaction_type": "BUY", "quantity": 1, "product": "CNC",
      "order_type": "MARKET", "validity": "DAY", "tag": "delivery-buy" },

    { "type": "amo", "exchange": "NSE", "tradingsymbol": "TCS",
      "transaction_type": "BUY", "quantity": 2, "product": "CNC",
      "order_type": "LIMIT", "price": 3500.0, "validity": "DAY" },

    { "type": "gtt", "trigger_type": "single", "exchange": "NSE",
      "tradingsymbol": "RELIANCE", "last_price": 2900.0,
      "trigger_values": [2700.0],
      "legs": [ { "transaction_type": "BUY", "quantity": 1,
                  "product": "CNC", "price": 2700.0 } ] },

    { "type": "gtt", "trigger_type": "oco", "exchange": "NSE",
      "tradingsymbol": "HDFCBANK", "last_price": 1600.0,
      "trigger_values": [1450.0, 1750.0],
      "legs": [ { "transaction_type": "SELL", "quantity": 5,
                  "product": "CNC", "price": 1450.0 },
                { "transaction_type": "SELL", "quantity": 5,
                  "product": "CNC", "price": 1750.0 } ] }
  ]
}
```

## 7. Placement & batch behavior (`placement.py`)

- `place_one(kite, order) -> str`:
  - `RegularOrder` → `kite.place_order(variety=<regular|amo>, exchange, tradingsymbol,
    transaction_type, quantity, product, order_type, price=…, trigger_price=…,
    validity=…, tag=…)` → returns `order_id`.
  - `GttOrder` → `kite.place_gtt(trigger_type=<single|two-leg>, tradingsymbol,
    exchange, trigger_values, last_price, orders=[{transaction_type, quantity,
    order_type:"LIMIT", product, price}, …])` → returns `trigger_id`.
- `run_batch(kite, orders)`: place **sequentially in file order** (KISS, within
  Kite rate limits). Each order is logged before the call and the broker response
  after. On `kiteconnect.exceptions.KiteException` (or any unexpected error) the
  failure is logged and the loop **continues** to the next order.
- After the loop, print a summary table: index · type · symbol · side/qty ·
  result-id-or-error. Return success/failure counts.

## 8. Logging, errors, exit codes

- Reuse `configure_logging(log_dir)` from `stock_data.logging_config` (importing
  the installed package is not "touching `src/`"). Loggers are named
  `stock_data.kite.*` so they inherit its handlers. `log_dir` is the fixed
  package location `scripts/kite/logs/` (a defined location, not a fallback for
  missing input). Every order and broker response is logged in detail; secret
  values are never logged.
- Custom exceptions (all fail-fast, clear messages): `KiteCredentialError`,
  `KiteAuthError`, `KiteOrderSpecError`.
- **Exit codes (`place_orders.py`):**
  - `0` — all orders placed successfully.
  - `1` — batch attempted but ≥1 order failed (partial or total).
  - `2` — setup failure, nothing attempted (missing/invalid credentials, dead
    token, unreadable/invalid orders JSON).

## 9. Dependencies & .gitignore

- Add **`kiteconnect>=5.2,<6`** (latest is 5.2.0, Apr 2026) to
  `pyproject.toml` `[project.dependencies]`, installed via `uv`. Implementation
  step verifies it resolves/installs on Python 3.12 before coding against it.
- `.gitignore` gains:
  ```
  scripts/kite/secrets/
  scripts/kite/logs/
  ```

## 10. CLI / run commands

```bash
# once per trading day — mint the access token
.venv/bin/python -m scripts.kite.login
.venv/bin/python -m scripts.kite.login --request-token <token>   # non-interactive

# place a batch of orders
.venv/bin/python -m scripts.kite.place_orders --orders scripts/kite/examples/orders.sample.json
```

`place_orders.py` requires `--orders <path>` (no default path). `scripts/kite/COMMANDS.md`
documents both commands with sample input, sample output, and the exit codes
above, mirroring the repository's top-level `COMMANDS.md`.

## 11. Testing & verification

- **Mocked unit tests** under `tests/` (pytest + pytest-mock, already dev deps).
  `KiteConnect` is mocked so **no network / no real orders**:
  - schema: valid orders parse; each invalid case raises (MARKET with price,
    LIMIT without price, SL/SL-M trigger rules, OCO with 1 leg or non-ascending
    triggers, quantity ≤ 0, bad enum, unknown key).
  - dispatch: `regular`/`amo` call `place_order` with exactly the right kwargs
    (incl. `variety`); `gtt` single/oco call `place_gtt` with the right
    `trigger_type`, `trigger_values`, and leg dicts (`order_type=="LIMIT"`).
  - batch: continue-on-error, summary counts, and the 0/1/2 exit-code mapping.
  - credentials/token: missing file → `KiteCredentialError`; round-trip
    read/write of the token cache.
- **Verification caveat (honest):** with the dry-run/confirmation removed and no
  Zerodha paper-trading endpoint, the only *non-firing* verification is the
  mocked tests. A real end-to-end check means the user placing a real (small)
  order at their discretion.

## 12. Out of scope (YAGNI)

Modify/cancel orders, list/cancel GTTs, order-status polling,
positions/holdings/P&L, cover orders, iceberg, TTL validity, concurrency,
env-var credential source, and any `src/` or `stock-data` CLI changes.

## 13. Verified SDK reference (`kiteconnect` 5.2.0)

- `KiteConnect(api_key=…)`; `login_url()`; `generate_session(request_token,
  api_secret=…)` → dict incl. `access_token`; `set_access_token(token)`.
- `place_order(variety, exchange, tradingsymbol, transaction_type, quantity,
  product, order_type, price=None, validity=None, validity_ttl=None,
  disclosed_quantity=None, trigger_price=None, iceberg_legs=None,
  iceberg_quantity=None, auction_number=None, tag=None, market_protection=None)`
  → `order_id` (str).
- `place_gtt(trigger_type, tradingsymbol, exchange, trigger_values, last_price,
  orders)` → `trigger_id`. `orders` legs = `{transaction_type, quantity,
  order_type, product, price}` (order_type must be `LIMIT`); SDK injects
  exchange/tradingsymbol from the top-level args.
- Constants: `VARIETY_REGULAR="regular"`, `VARIETY_AMO="amo"`;
  `PRODUCT_CNC/MIS/NRML`; `ORDER_TYPE_MARKET/LIMIT/SL`, `ORDER_TYPE_SLM="SL-M"`;
  `TRANSACTION_TYPE_BUY/SELL`; `VALIDITY_DAY/IOC`;
  `GTT_TYPE_SINGLE="single"`, `GTT_TYPE_OCO="two-leg"`; `EXCHANGE_NSE/BSE/NFO/…`.
- Exceptions (`kiteconnect.exceptions`): base `KiteException`; `TokenException`,
  `InputException`, `OrderException`, `NetworkException`, `DataException`,
  `GeneralException`.
- Note: the exact internal leg-dict assembly and whether `generate_session`
  auto-sets the token will be confirmed against the installed package source at
  implementation time.
```