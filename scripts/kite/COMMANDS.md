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
