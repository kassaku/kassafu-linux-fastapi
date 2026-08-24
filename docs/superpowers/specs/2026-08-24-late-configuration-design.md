# Late Configuration Design

Date: 2026-08-24
Status: Approved

## Goal

KassaFu runs as a POS boot service that starts **before** any credentials exist.
It boots into a "waiting" state, receives its full configuration later via
`POST /config`, auto-detects the device (sumup/mypos/future) from the config
sections, and swaps the terminal implementation live. One active terminal at a
time.

## Problem

Today kassafu cannot start without a valid `config.json`: module import calls
`load_config_from_file()` which `sys.exit(1)` on a missing file, and `lifespan`
raises `RuntimeError` when terminal init fails. The existing `POST /config`
merges partial settings into the *existing* terminal object, can never switch
device type, contains dead code (kassafu.py:410-412), and raises an
unhandled error (500) when no terminal exists yet.

## User-approved decisions

1. Bare startup loads **no** config file: empty config, waiting mode.
2. `--config <path>` remains as a **manual seed only**: file loading happens
   exclusively when the flag is passed explicitly.
3. Late configuration arrives as **full JSON via `POST /config`** (wholesale
   replacement, not merge).
4. Persistence is **in-memory only**; after a restart the config is re-sent.
5. Extensibility = **registry pattern** (`TERMINAL_CLASSES`); no plugin
   machinery now.
6. A **failed swap keeps the previous terminal running**; a bad push must not
   take down a working POS.

## Design

### Boot sequence

- Module level: `config = {}` — no file I/O at import time (also removes the
  tests' CWD dependency on `config.json`). `CONFIG_FILE` constant removed.
- `__main__`: `--config` loses `default="config.json"` and the
  `!= "config.json"` comparison hack. If the flag is passed, the file is
  loaded (missing/corrupt file exits loudly — explicit operator intent);
  otherwise `config` stays `{}` and startup logs
  `"No configuration - waiting for POST /config"`.
- `lifespan`: if `_resolve_terminal_type(config)` finds no terminal section,
  skip terminal creation entirely (`terminal` stays `None`) but still start
  the payment queue task. If a section exists but `init()` fails, log the
  errors and continue in waiting mode instead of raising `RuntimeError`.

### Waiting mode

- `/health`: while no configuration has been applied,
  `{"status": "unconfigured", "mode": null, "terminal_ready": false}`
  (`mode` must not claim `"sumup"` merely because that is the fallback
  default). Once a config is applied, `status` becomes `"healthy"` and
  `mode` reports the active device type as before.
- Payment endpoints already guard on missing terminal and keep their existing
  errors: `/pay` 503 "Terminal not ready", `/payment/status` 503/108008,
  `/reader/status` 108010. No changes needed there.

### `POST /config` rework — full replacement + hot swap

New flow, replacing the merge logic entirely:

1. If `active_payment` is true → `409 Conflict`
   (`"error_code": 108012`, message "Payment in progress").
2. Body must be a JSON object; replace global `config` with it.
3. Re-resolve device via `_resolve_terminal_type(config)`; instantiate a
   fresh terminal of that class; call `init(config)`.
4. On success: atomically swap globals `terminal` and `TERMINAL_TYPE`;
   run discovery if the new terminal lacks a reader/terminal id (existing
   behavior). Return `{"success": true, "terminal_type": "<type>"}`.
5. On failure (missing keys, validation): keep old `config`, `terminal`,
   `TERMINAL_TYPE`; return 400 with the init error detail. If previously
   unconfigured, stay unconfigured (no crash).

The swap+init logic lives in one helper,
`_apply_runtime_config(new_config: dict) -> tuple[bool, str]` returning
`(success, detail)`, so it is unit-testable without booting ASGI; the endpoint
is a thin wrapper mapping the result to HTTP codes.

Queue interaction: queued payments dequeued after a swap are processed by the
new terminal (queue processor reads the global). While unconfigured nothing
can enter the queue (`/pay` guards first).

### Future devices (recipe, not machinery)

Supporting a device = one module implementing the existing terminal interface
(`init`, `process_payment`, `check_status`, `get_config`, `is_ready`, ...) +
one `TERMINAL_CLASSES` entry keyed by its config section name. Auto-detection
then picks it up by section presence or explicit `app.terminal_type`. Already
generic after the auto-detection feature; this design adds nothing further.

## Testing

Extend `tests/test_kassafu_config.py` (stdlib unittest):

- `_apply_runtime_config` on empty state → success, sumup terminal created
- live swap sumup→mypos and mypos→sumup with minimal valid configs
- invalid mypos config (missing required key) → failure, previous terminal
  untouched, previous config preserved
- explicit unknown `app.terminal_type` in posted config falls back per
  existing precedence rules

Tests reset module globals between cases. Full suite must stay green.

## Files changed

- modified: `kassafu.py` (boot/loading, lifespan waiting mode, `POST /config`
  rewrite via `_apply_runtime_config`, `/health` wording)
- modified: `tests/test_kassafu_config.py`

Out of scope: persistence, plugin discovery, zhongcan deployment migration.

## Deployment note

Any deployment relying on implicit `config.json` pickup (e.g. the zhongcan
service unit running bare `kassafu.py --server`) will now boot unconfigured;
its unit should add `--config` or its frontend must push the config after
boot. That migration belongs to the deployment, not this repo change.
