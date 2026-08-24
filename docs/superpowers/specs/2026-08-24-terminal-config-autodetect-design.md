# Terminal Config Auto-Detection Design

Date: 2026-08-24
Status: Approved

## Goal

Run KassaFu against SumUp or myPOS by pointing `--config` at a
terminal-specific config file. The terminal type is auto-detected from which
top-level config section is present (`sumup` vs `mypos`), so two separate test
configs work without code changes or duplicated settings.

## Problem

Two defects make per-terminal configs impossible today:

1. `kassafu.py` computes `TERMINAL_TYPE` at import time from the default
   `config.json` (lines 74-75), *before* `__main__` applies the `--config`
   override (lines 415-417). Passing `--config other.json` loads new
   credentials but never switches the terminal type.
2. `app.mode` doubles as the fallback terminal type. The current
   `config.json` has `"mode": "sandbox"` — an unknown terminal name — which
   silently falls back to SumUp in `_get_terminal_class`.

## Design

### Detection rule: `_resolve_terminal_type(config) -> str`

New pure helper in `kassafu.py`, next to `_get_terminal_class`:

Precedence:

1. `app.terminal_type` present and a key of `TERMINAL_CLASSES` → use it
   (explicit escape hatch).
2. Otherwise, presence of top-level sections decides:
   - only `mypos` present → `"mypos"`
   - only `sumup` present → `"sumup"`
   - both present → `"sumup"` + warning log (backwards compatible default,
     user-approved)
   - neither present → `"sumup"` + warning log (today's behavior)
3. Explicit `app.terminal_type` that is unknown → warning + `"sumup"`
   (mirrors `_get_terminal_class` fallback).

Comparison is case-insensitive, consistent with `_get_terminal_class`.

### Resolution timing (bug fix)

`lifespan()` resolves the terminal type via the helper using the **final**
global `config` (i.e., after any `--config` reload) and assigns the
module-level `TERMINAL_TYPE`. Startup logs, init-failure messages, discovery
warnings, and the `/config` endpoints (lines 330-371) keep reading
`TERMINAL_TYPE` unchanged.

`TERMINAL_MODE` is removed; `app.mode` means sandbox/live only and no longer
influences terminal selection.

### Test config files

- `config.sumup.json` — copy of the current `config.json` (SumUp sandbox
  credentials, `app.mode: "sandbox"`).
- `config.mypos.json` — template containing every required myPOS key with
  placeholder secrets: `gateway_url`
  (`https://demo-api-gateway.mypos.com`), `integration.client_id/secret`,
  `partner_id`, `application_id`, `merchant.client_id/secret`,
  `terminal_id`; `app.mode: "sandbox"`; no `terminal_type` (exercises
  auto-detection).
- `config.json` stays untouched as the default.

Usage:

```bash
venv/bin/python kassafu.py --server --config config.sumup.json
venv/bin/python kassafu.py --server --config config.mypos.json
```

## Testing

New `tests/test_kassafu_config.py` (stdlib `unittest`, matching existing
style). Cases for `_resolve_terminal_type`:

- explicit `terminal_type: "mypos"` wins even when only `sumup` present
- explicit unknown type falls back to `sumup`
- `mypos`-only config → `mypos`
- `sumup`-only config → `sumup`
- both sections → `sumup`
- neither section → `sumup`

Importing `kassafu` requires `fastapi`/`uvicorn`/`httpx` (already venv
dependencies) and writes `kassafu.log` to the CWD, so tests run from the repo
root like the existing suites (`python3 -m unittest tests.test_kassafu_config`).

## Files changed

- modified: `kassafu.py` — add `_resolve_terminal_type`, resolve in
  `lifespan`, drop `TERMINAL_MODE`
- new: `config.sumup.json`, `config.mypos.json`, `tests/test_kassafu_config.py`

Out of scope: `run.sh`, `install.sh`, systemd unit, service files.
