# myPOS Gateway Rework Design

Date: 2026-08-11
Status: Approved

## Goal

Rework `mypos_terminal.py` to talk to the myPOS ePOS API Gateway (OpenAPI "POS" v1,
servers `demo-api-gateway.mypos.com` / `api-gateway.mypos.com`) instead of the
currently-implemented, non-matching endpoints. The current file calls
`/oauth/token`, `/oauth/session`, `/epos/terminals`, `/epos/payments`, and
`/epos/payments/{id}/reverse`, which do not match the spec.

Payment functionality must stay compatible with the SumUp interface that
`kassafu.py` consumes, so `kassafu.py` and the test scripts
(`test_reader_status.py`, `test_real_payment.py`) remain unchanged.

## Scope

Implements the payment flow only:

- Create Payment — `POST /epos/v1/payments`
- Get Payment By ID — `GET /epos/v1/payments/{payment_id}`
- Cancel Payment — `DELETE /epos/v1/payments/{payment_id}`
- Get Terminals — `GET /pos/v1/terminals` (discovery)
- Get Terminal Details — `GET /pos/v1/terminals/{terminal_id}` (status check)

Refund (`POST /epos/v1/payments/refund`), reversal
(`POST /epos/v1/payments/{payment_id}/reversal`), transaction history, receipts,
terminal activation/deactivation, models, and outlets are explicitly out of scope
and will be added later if needed.

## Architecture

Two modules:

### New file: `mypos_gateway.py`

`MyPOSGateway` class. Owns all myPOS HTTP + auth. Has no knowledge of kassafu's
interface or error-code contract.

Responsibilities:
- Read and store credentials (gateway_url, integration client_id/secret,
  merchant client_id/secret, partner_id, application_id).
- Obtain and cache the OAuth Bearer token (integration creds) and the merchant
  session token, with expiry-based refresh.
- Issue API requests with the four required headers.
- Raise `MyPOSGatewayError(status, detail)` on non-2xx and transport errors.
- On 401: invalidate cached tokens and retry the request once.

Methods:

- `async get_terminals(**params) -> dict`
- `async get_terminal(terminal_id) -> dict`
- `async create_payment(payload: dict) -> dict`
- `async get_payment(payment_id) -> dict`
- `async cancel_payment(payment_id) -> dict`

### Rewritten file: `mypos_terminal.py`

`MyPOSTerminal` adapter. Keeps the exact interface `kassafu.py` uses:

- `init(config) -> bool`
- `update_config(config) -> bool`
- `get_config() -> dict`
- `discover_reader() -> bool`
- `check_status() -> dict`
- `process_payment(order_id, amount_cents, currency="EUR") -> dict`
- `get_transaction_status(transaction_id) -> str`
- `cancel_payment(order_id) -> dict`
- `clear_display()`
- `_log_transaction(...)`, `_log_status_update(...)`
- attributes: `terminal_id`, `is_ready`, `current_order_id`,
  `current_transaction_id`, `current_amount_cents`, `current_currency`,
  `current_status`, `current_created_at`, `current_card_scheme`,
  `current_card_last_4`

Instantiates `MyPOSGateway` from config in `init()`. Delegates all myPOS calls
to it. Maps gateway responses to the kassafu contract and error codes.

## Authentication flow

Matches the official myPOS flow (Identity / authentication docs):

1. `POST {gateway}/api/v1/oauth/token`
   - body: `application/x-www-form-urlencoded`
     `client_id=<integration>`, `client_secret=<integration>`,
     `grant_type=client_credentials`
   - response: `access_token`, `expires_in` (3600), `token_type`, `scope`
   - cached; refresh 60 seconds before expiry
2. `POST {gateway}/api/v1/auth/session`
   - header: `Authorization: Bearer <integration token>`
   - body JSON: `{"client_id": <merchant>, "client_secret": <merchant>}`
   - response: `session` (field name!), `expires_in` (360)
   - cached; refresh 30 seconds before expiry
3. Every API request sends:
   - `Authorization: Bearer <integration token>`
   - `X-Session: <session>`
   - `X-Partner-Id: mps-p-*`
   - `X-Application-Id: mps-app-*`

The current code puts the merchant token in `Authorization` and reads the wrong
session field (`sessionToken`); the rework fixes both.

## Endpoint usage

### Create payment

`POST /epos/v1/payments`

Request body (snake_case):

```json
{
  "reference_number": "<order_id>",
  "amount": { "value": <amount_cents>, "currency_code": "EUR" },
  "description": "<optional>",
  "terminal_id": "<8-digit TID>",
  "app_name": "KassaFu",
  "app_version": "1.0.0",
  "operator_code": "<optional, omitted if unset>"
}
```

- `reference_number` = KassaFu `order_id` (max 50 chars)
- `amount.value` in minor units (matches existing `amount_cents`)
- `app_name`/`app_version` from config with defaults `KassaFu` / `1.0.0`

Response `201` includes `payment_id` -> stored as `current_transaction_id`.

### Get payment status

`GET /epos/v1/payments/{payment_id}`

Spec status -> kassafu contract mapping (returned by `get_transaction_status`):

| spec status | kassafu status |
|---|---|
| `Success` | `SUCCESSFUL` |
| `Failed`, `Rejected` | `FAILED` |
| `Canceled`, `Reversed` | `CANCELLED` |
| `InProgress`, anything else | `PENDING` |

Card info: `card_qualifier` -> `current_card_scheme`, last 4 of `pan` ->
`current_card_last_4`.

### Cancel payment

`DELETE /epos/v1/payments/{payment_id}` -> `202 Accepted`

### Terminal discovery

`GET /pos/v1/terminals` -> `{ pagination, terminals: [{terminal_id, serial_number, model}] }`.
Take the first item's `terminal_id`.

### Terminal status

`GET /pos/v1/terminals/{terminal_id}` -> response contains `status`.
`status == "Active"` maps to `online=True, ready=True`. Also expose
`terminal_name`, `model`, `serial_number`, `device_currency` in the result.

## Configuration

Config schema unchanged (loaded by kassafu.py from config.json):

```json
{
  "mypos": {
    "gateway_url": "https://demo-api-gateway.mypos.com",
    "integration": { "client_id": "...", "client_secret": "..." },
    "partner_id": "mps-p-...",
    "application_id": "mps-app-...",
    "merchant": { "client_id": "cli_...", "client_secret": "sec_..." },
    "terminal_id": "80026232"
  }
}
```

Validation on init:
- required: `gateway_url`, `integration.client_id`, `integration.client_secret`
- newly required: `partner_id`, `application_id`,
  `merchant.client_id`, `merchant.client_secret`
- `terminal_id` optional; if absent, `is_ready=False` and discovery is used

`get_config()` excludes all secrets (unchanged behavior).

## Error handling

- Gateway raises `MyPOSGatewayError(status, detail)` on non-2xx; on transport
  errors raises `httpx.HTTPError` wrapped in `MyPOSGatewayError`.
- 401: gateway invalidates integration + session tokens and retries once before
  surfacing the error.
- Adapter maps to kassafu error codes:
  - 400 -> 108007 (validation)
  - 401/403 -> 108003 (invalid/missing config / unauthorized)
  - 404 -> 108002 (not found)
  - 5xx -> 108011 (API error)
  - transport/timeout -> 108001 / 108005
- `process_payment` returns the existing success/failure dict shape, so
  `kassafu.py` `/pay` and `/payment/status` behave as before.

## Files changed

- new: `mypos_gateway.py`
- rewrite: `mypos_terminal.py`
- edit: `install.sh` — add `cp "$SCRIPT_DIR/mypos_gateway.py" "$INSTALL_DIR/"`
- unchanged: `kassafu.py`, `test_reader_status.py`, `test_real_payment.py`,
  `config.json` schema, `requirements.txt`

No `setup.py` exists; packaging is via `install.sh` only.

## Testing

- stdlib `unittest` + `httpx.MockTransport` (httpx already a dependency; no new
  packages).
- `test_mypos_gateway.py`:
  - auth: token caching, refresh-before-expiry, session fetch, 401 invalidation
    + single retry
  - endpoints: correct method/path/headers/body per call; response parsing
- `test_mypos_terminal.py`:
  - status mapping table
  - `process_payment` request body construction and response handling
  - `check_status` Active mapping
  - error-code mapping for each HTTP status
  - `cancel_payment` flow