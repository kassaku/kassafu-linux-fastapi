# myPOS Credential Error UI Design

Date: 2026-09-20
Status: Approved

## Goal

Show a clear "wrong credentials" message in the zhongcan POS UI when myPOS
credentials are invalid, never start a payment while they are wrong, and
automatically recover once the credentials are fixed on the website.

Credential errors are distinguished by kind: partner credentials (fail on
`POST /api/v1/oauth/token`) versus merchant credentials (fail on
`POST /api/v1/auth/session`).

## Problem

Today a myPOS configuration with wrong credentials is indistinguishable from
a healthy one at startup:

- `MyPOSTerminal.init()` only validates that credential *fields exist*; it
  never validates them against the gateway (`mypos_terminal.py:65-119`).
- kassafu therefore reports `terminal_ready: true` on `/health` and accepts
  `/pay`.
- The actual failure (`POST /oauth/token` -> HTTP 400) happens mid-payment.
- `/reader/status` does fail: `get_terminal()` needs a token, gets a 400, and
  returns `{"online":false, "error_code":108007, "error":...}`. zhongcan's
  `handleReaderStatus` only inspects `online`, so the POS shows a generic
  "device issue" (`payment_terminal_kassafu.cpp:250-265`).
- `startPayment` (`view_billing_dialog.cpp:837`, `view_ask_table_dialog.cpp:700`)
  does not gate on state, so the POS initiates payments against bad credentials.

## User-approved decisions

1. **Detection signal:** kassafu emits a dedicated error code from
   `/reader/status` when an auth call fails (no string matching in zhongcan).
2. **State machine:** zhongcan gets dedicated downstream credential-error
   states (not a reuse of `CONFIRM_CREDENTIALS`).
3. **Granularity:** partner and merchant credential errors are distinguished
   (`108014` partner, `108015` merchant).
4. **Error state is inert:** while either credential-error state is active,
   no payment can start; the UI only shows the error message and an OK/dismiss
   button. No retry / pay-cash / cancel-transaction actions.
5. **Self-healing:** while in a credential-error state, zhongcan re-POSTs
   `/config` every 5 minutes (re-fetching the encrypted blobs from the
   website); when the fixed credentials validate, `/reader/status` reports
   online again and zhongcan leaves the error state automatically. Detection
   keeps polling in the error states.
6. **UI translation:** new text IDs translated in all 8 sdl2ui languages.

## Design

### Part A — kassafu (Python, `workspace/kassafu`)

#### `mypos_gateway.py`

- Add instance state `self._auth_failure = None` (`"partner"`/`"merchant"`).
- `_request_partner_token()`: on HTTP 400/401/403 set `_auth_failure =
  "partner"`; on a 200/201 response clear any stored `"partner"` failure.
- `_request_session()`: on HTTP 400/401/403 set `_auth_failure = "merchant"`;
  on success clear any stored `"merchant"` failure.
- Expose `auth_failure` property returning `self._auth_failure`.

#### `mypos_terminal.py`

- Error codes: `108014` = partner credentials invalid, `108015` = merchant
  credentials invalid. Documented beside `_map_error_code` (`:151`).
- `check_status()` (`:201`): when the gateway raises `MyPOSGatewayError` and
  `gateway.auth_failure` is set, return
  `{"online": false, "ready": false, "error": <detail>, "error_code": 108014 | 108015}`.
- `process_payment()` (`:220`): the failure payload reuses the same mapping so
  a mid-payment auth failure also carries the correct error code.

#### Tests (`tests/test_mypos_gateway.py` and related)

- Partner token 400/401/403 -> `auth_failure == "partner"`;
  success clears it.
- Session 400/401/403 -> `auth_failure == "merchant"`.
- `check_status()` returns 108014/108015 on the corresponding failures.
- Existing tests keep passing; run the kassafu pytest suite.

### Part B — zhongcan C++ (`workspace/zhongcan-project`)

#### `payment_terminal.hpp`

- Add to `EpaymentState`: `PARTNER_CREDENTIALS_INVALID`,
  `MERCHANT_CREDENTIALS_INVALID` (documented like the neighbours).

#### `payment_terminal_kassafu.{hpp,cpp}`

- `setRemoteConfig(...)` stores the passed device id / client url / client key
  / partner url / partner key as members (currently it only enqueues one
  request, `payment_terminal_kassafu.cpp:50-74`).
- `startPayment()` (`:76`): if the session state is either credential-error
  state, refuse (log + return without transitioning or sending `/pay`);
  the state machine stays put.
- `handleReaderStatus()` (`:250`): read `error_code` from the JSON; `108014`
  -> `PARTNER_CREDENTIALS_INVALID` + `messageId = _PAYMENT_MSG_PARTNER_CREDENTIALS`;
  `108015` -> `MERCHANT_CREDENTIALS_INVALID` +
  `messageId = _PAYMENT_MSG_MERCHANT_CREDENTIALS`; otherwise keep the existing
  `online`/offline logic.
- `update()` (`:110`): add both new states to the health/reader polling group
  (`:124-148`) so detection continues. Add `m_credentialRetryTimer` (5 min);
  while in a credential-error state, when it expires re-enqueue the stored
  remote config via the same request used in `setRemoteConfig` and reset the
  timer.

#### `payment_terminal.cpp`

- `paymentMsgIdToTextId()` (`:13`): `108014` -> `_PAYMENT_MSG_PARTNER_CREDENTIALS`,
  `108015` -> `_PAYMENT_MSG_MERCHANT_CREDENTIALS`.
- `getStatusText()` (`:120`): cases for the two new states returning their
  translations.

#### `message_box_card_payment.cpp`

- `stateToTextId()` (`:20`): cases mapping both new states to their messages.
- `paintButtons()` (`:117`): when the terminal is in a credential-error state,
  render a single OK (dismiss) button only — no retry, pay-cash,
  open/cancel-transaction controls. Pressing OK closes the dialog and leaves
  the state active.

#### `card_payment_button.cpp`

- `onLoop()` colouring (`:160`): treat both new states like the
  WAIT_DRIVER_CONNECTED / error group (i.e. the button stays visible and shows
  the error/attention colours).

#### Simulation terminal

- Unaffected. Gating and credential handling live only in
  `CpaymentTerminalKassafu`.

### Part C — sdl2ui translations (8 languages x 2 strings)

- `lingual.h`: add `_PAYMENT_MSG_PARTNER_CREDENTIALS` and
  `_PAYMENT_MSG_MERCHANT_CREDENTIALS` in the `_PAYMENT_MSG_*` block (`:440`).
- `lingual.cpp`: add both names to the master list.
- `lingual_english.cpp`, `lingual_dutch.cpp`, `lingual_german.cpp`,
  `lingual_simplified.cpp`, `lingual_traditional.cpp`, `lingual_arabic.cpp`,
  `lingual_bahasa.cpp`, `lingual_turkisch.cpp`: add both entries, placed in
  the same order as `lingual.h`. Proposed strings:

  | Language | Partner | Merchant |
  |---|---|---|
  | English | Wrong partner credentials | Wrong merchant credentials |
  | Dutch | Verkeerde partner-gegevens | Verkeerde merchant-gegevens |
  | German | Falsche Partner-Zugangsdaten | Falsche Händler-Zugangsdaten |
  | Simplified Chinese | 合作伙伴凭据错误 | 商户凭据错误 |
  | Traditional Chinese | 合作夥伴憑據錯誤 | 商戶憑據錯誤 |
  | Arabic | بيانات اعتماد الشريك غير صحيحة | بيانات اعتماد التاجر غير صحيحة |
  | Bahasa | Kredensial partner salah | Kredensial merchant salah |
  | Turkish | Ortak kimlik bilgileri hatalı | Satıcı kimlik bilgileri hatalı |

## Error handling

- A transport failure or HTTP 5xx from the gateway must not reclassify as a
  credential error; only the auth endpoints (400/401/403) do.
- If `/config` re-push fails at transport level, keep the error state and let
  the 5-minute timer retry; `update()` already survives failed requests.
- A successful credential refresh clears `m_session.messageId` back through the
  normal `online`->`IDLE` path in `handleReaderStatus`.

## Testing

- kassafu: pytest additions (see Part A), plus the full existing suite.
- zhongcan: compile check of the touched translation and payment files via the
  project's build; no behavioural automated test exists for the SDL UI.

## Out of scope

- Deployment of the live service (`~/zhongcan`) and the POS binary; shipping
  to the machine is the user's step after this lands.
- SumUp credential handling (SumUp never validated partner credentials).
- Any new UI affordance beyond the error message + OK dismiss.