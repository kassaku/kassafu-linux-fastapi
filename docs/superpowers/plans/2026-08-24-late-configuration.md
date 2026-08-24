# Late Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KassaFu boots without any config file into a "waiting" state and receives its full configuration later via `POST /config`, hot-swapping the terminal (sumup/mypos/future) based on auto-detection.

**Architecture:** New pure-ish helper `_apply_runtime_config(new_config)` owns validate→init→atomic-swap logic and returns `(success, detail)`; the endpoint is a thin HTTP wrapper. Boot no longer reads any file unless `--config <path>` is passed explicitly (manual seed); `lifespan` skips terminal creation when no device section is present. Discovery logic extracted to `_maybe_discover(term)` shared by startup and post-swap.

**Tech Stack:** Python stdlib `unittest`, FastAPI/uvicorn (existing deps).

**Spec:** `docs/superpowers/specs/2026-08-24-late-configuration-design.md`

**Important repo notes:**
- Run tests from repo root: `venv/bin/python -m unittest ...`. Importing `kassafu` will NO LONGER require `config.json` after Task 2.
- The user's LIVE deployment (`~/zhongcan/kassafu.py`, pid may differ) listens on **127.0.0.1:8888**. NEVER kill it; always verify against free high ports (8893+) using `--port`.
- Never `git add -A` / `git add .`; stage only listed files. Worktree contains unrelated WIP (deleted `test_reader_status.py`, untracked `test_reader_status_mypos.py` / `test_reader_status_sumup.py`) — leave untouched.
- Commit messages follow repo style: short imperative, no prefixes.

---

### Task 1: `_apply_runtime_config` helper (TDD)

**Files:**
- Modify: `tests/test_kassafu_config.py` (append new test class + imports)
- Modify: `kassafu.py` (add function directly after `_resolve_terminal_type`, which ends near line 108)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_kassafu_config.py` (extend existing imports at top to match):

```python
import unittest

import kassafu
from kassafu import _apply_runtime_config, _resolve_terminal_type
from mypos_terminal import MyPOSTerminal
from sumup_terminal import SumUpTerminal

SUMUP_CONFIG = {
    "sumup": {
        "api_key": "sup_sk_test",
        "merchant_code": "M1234567",
        "reader_id": "rdr_test123",
    }
}

MYPOS_CONFIG = {
    "mypos": {
        "gateway_url": "https://demo-api-gateway.mypos.com",
        "integration": {"client_id": "ci", "client_secret": "cs"},
        "partner_id": "mps-p-test",
        "application_id": "mps-app-test",
        "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
        "terminal_id": "80026232",
    }
}


class ApplyRuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = (kassafu.config, kassafu.terminal, kassafu.TERMINAL_TYPE)
        kassafu.config = {}
        kassafu.terminal = None
        kassafu.TERMINAL_TYPE = None

    def tearDown(self):
        kassafu.config, kassafu.terminal, kassafu.TERMINAL_TYPE = self._saved

    def test_apply_on_empty_state_creates_sumup_terminal(self):
        ok, detail = _apply_runtime_config(SUMUP_CONFIG)
        self.assertTrue(ok)
        self.assertEqual(detail, "sumup")
        self.assertIsInstance(kassafu.terminal, SumUpTerminal)
        self.assertEqual(kassafu.TERMINAL_TYPE, "sumup")
        self.assertEqual(kassafu.config, SUMUP_CONFIG)

    def test_apply_mypos_config_creates_mypos_terminal(self):
        ok, detail = _apply_runtime_config(MYPOS_CONFIG)
        self.assertTrue(ok)
        self.assertEqual(detail, "mypos")
        self.assertIsInstance(kassafu.terminal, MyPOSTerminal)
        self.assertEqual(kassafu.TERMINAL_TYPE, "mypos")

    def test_live_swap_from_sumup_to_mypos(self):
        _apply_runtime_config(SUMUP_CONFIG)
        ok, detail = _apply_runtime_config(MYPOS_CONFIG)
        self.assertTrue(ok)
        self.assertEqual(detail, "mypos")
        self.assertIsInstance(kassafu.terminal, MyPOSTerminal)

        ok, detail = _apply_runtime_config(SUMUP_CONFIG)
        self.assertTrue(ok)
        self.assertEqual(detail, "sumup")
        self.assertIsInstance(kassafu.terminal, SumUpTerminal)

    def test_invalid_config_keeps_previous_terminal(self):
        _apply_runtime_config(SUMUP_CONFIG)
        previous = kassafu.terminal

        broken = {
            "mypos": {
                k: v for k, v in MYPOS_CONFIG["mypos"].items() if k != "partner_id"
            }
        }
        ok, detail = _apply_runtime_config(broken)
        self.assertFalse(ok)
        self.assertIn("Failed to initialize", detail)
        self.assertIs(kassafu.terminal, previous)
        self.assertEqual(kassafu.TERMINAL_TYPE, "sumup")
        self.assertEqual(kassafu.config, SUMUP_CONFIG)

    def test_non_dict_config_rejected(self):
        ok, detail = _apply_runtime_config("nope")
        self.assertFalse(ok)
        self.assertIn("JSON object", detail)


if __name__ == "__main__":
    unittest.main()
```

(The existing `ResolveTerminalTypeTests` class stays unchanged below the new fixtures.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m unittest tests.test_kassafu_config -v`
Expected: FAIL/ERROR — `ImportError: cannot import name '_apply_runtime_config' from 'kassafu'`

- [ ] **Step 3: Implement the helper**

In `kassafu.py`, directly after `_resolve_terminal_type`, add:

```python
def _apply_runtime_config(new_config: dict):
    """Replace runtime config and hot-swap the terminal implementation.

    Returns (success, detail): detail is the active terminal type on success,
    an error message on failure. Globals are only mutated on success.
    """
    global config, terminal, TERMINAL_TYPE

    if not isinstance(new_config, dict):
        return False, "Configuration must be a JSON object"

    term_type = _resolve_terminal_type(new_config)
    term_cls = _get_terminal_class(term_type)

    candidate = term_cls()
    if not candidate.init(new_config):
        detail = f"Failed to initialize {term_type} terminal with supplied configuration"
        logger.error(detail)
        return False, detail

    config = new_config
    TERMINAL_TYPE = term_type
    terminal = candidate

    logger.info(f"Terminal switched to '{term_type}' via runtime configuration")
    return True, term_type
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m unittest tests.test_kassafu_config -v`
Expected: `OK` (12 tests: 7 old + 5 new)

- [ ] **Step 5: Run the full suite**

Run: `venv/bin/python -m unittest discover -s tests -v`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add kassafu.py tests/test_kassafu_config.py
git commit -m "Add runtime config apply helper with terminal hot swap"
```

---

### Task 2: Boot without config, waiting mode, `/health` update

No unit tests for this task (would require booting ASGI); verified end-to-end in Step 4. Full suite must stay green throughout.

**Files:**
- Modify: `kassafu.py`

- [ ] **Step 1: Remove import-time file loading**

Delete the constant near the top (line ~40):

```python
CONFIG_FILE = "config.json"
```

Change the loader signature from `def load_config_from_file(config_path: str = CONFIG_FILE) -> dict:` to:

```python
def load_config_from_file(config_path: str) -> dict:
```

Replace the module-level load (line ~72):

```python
config = load_config_from_file()
```

with:

```python
config = {}
```

In `__main__` (~line 433-441), change the argument definition:

```python
parser.add_argument("--config", type=str, help="Configuration file path (optional manual seed)")
```

and replace:

```python
if args.config != "config.json":
    CONFIG_FILE = args.config
    config = load_config_from_file(CONFIG_FILE)
```

with:

```python
if args.config:
    config = load_config_from_file(args.config)
```

- [ ] **Step 2: Extract discovery helper + waiting-mode lifespan**

Directly above `lifespan`, add:

```python
async def _maybe_discover(term):
    """Run reader/terminal discovery when supported and no id is configured yet."""
    if hasattr(term, 'discover_reader') and hasattr(term, 'reader_id'):
        if not term.reader_id:
            logger.info("No reader ID provided, discovering...")
            await term.discover_reader()
            if not term.reader_id:
                logger.warning(f"No {TERMINAL_TYPE} terminal found. Please check your configuration.")
    elif hasattr(term, 'terminal_id'):
        if not term.terminal_id:
            logger.info("No terminal ID provided, discovering...")
            await term.discover_reader()
```

Replace the whole current `lifespan` body between `global terminal, TERMINAL_TYPE` and `asyncio.create_task(process_payment_queue())` so it reads:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global terminal, TERMINAL_TYPE

    if any(name in config for name in TERMINAL_CLASSES):
        TERMINAL_TYPE = _resolve_terminal_type(config)
        logger.info(f"KassaFu starting with terminal type '{TERMINAL_TYPE}' on port {PORT}")

        candidate = _get_terminal_class(TERMINAL_TYPE)()
        if not candidate.init(config):
            logger.error(f"Failed to initialize {TERMINAL_TYPE} terminal - continuing unconfigured")
        else:
            terminal = candidate
            await _maybe_discover(terminal)
    else:
        logger.info("KassaFu started without configuration - waiting for POST /config")

    asyncio.create_task(process_payment_queue())

    yield

    logger.info("KassaFu shutting down")
```

- [ ] **Step 3: Update `/health`**

Replace the `if not terminal:` branch of the health endpoint (~line 347) with:

```python
    if not terminal:
        return {
            "status": "unconfigured",
            "mode": None,
            "terminal_ready": False,
            "error_code": 0
        }
```

(The healthy branch stays unchanged.)

- [ ] **Step 4: End-to-end verification (use ports 8893+, NEVER touch port 8888)**

Bare boot waits:

```bash
venv/bin/python kassafu.py --server --port 8893 > /tmp/opencode/kf-bare.log 2>&1 &
sleep 2 && curl -s http://localhost:8893/health; kill %1
```

Expected: `{"status":"unconfigured","mode":null,"terminal_ready":false,"error_code":0}` and log line `waiting for POST /config`.

Seeded boot works as before:

```bash
venv/bin/python kassafu.py --server --config config.sumup.json --port 8894 > /tmp/opencode/kf-seed.log 2>&1 &
sleep 2 && curl -s http://localhost:8894/health; kill %1
```

Expected: `{"status":"healthy","mode":"sumup","terminal_ready":true,...}`.

- [ ] **Step 5: Run the full suite**

Run: `venv/bin/python -m unittest discover -s tests -v`
Expected: all green

- [ ] **Step 6: Commit**

```bash
git add kassafu.py
git commit -m "Boot without config file and wait for runtime configuration"
```

---

### Task 3: `POST /config` rewrite — full replacement endpoint

The unit-tested core already exists (`_apply_runtime_config`); this wires HTTP semantics per spec: 409 during payment, 400 on failure, discovery after swap.

**Files:**
- Modify: `kassafu.py` — replace entire `update_config` endpoint (lines ~399-427, including the dead `for key ... pass` loop)

- [ ] **Step 1: Replace the endpoint**

Delete the whole current `update_config` function and put this in its place:

```python
@app.post("/config")
async def update_config(new_config: dict):
    """Replace runtime configuration and hot-swap the terminal (in-memory only)"""
    if active_payment:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "message": "Payment in progress, configuration rejected",
                "error_code": 108012,
            },
        )

    ok, detail = _apply_runtime_config(new_config)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)

    try:
        await _maybe_discover(terminal)
    except Exception as exc:  # discovery problems must not fail an applied config
        logger.warning(f"Post-swap discovery failed: {exc}")

    return {"success": True, "terminal_type": detail}
```

- [ ] **Step 2: Run the full suite**

Run: `venv/bin/python -m unittest discover -s tests -v`
Expected: all green

- [ ] **Step 3: End-to-end verification of the late-config flow**

```bash
venv/bin/python kassafu.py --server --port 8895 > /tmp/opencode/kf-late.log 2>&1 &
sleep 2
curl -s http://localhost:8895/health
# expect: {"status":"unconfigured","mode":null,...}
curl -s -X POST http://localhost:8895/config \
  -H 'Content-Type: application/json' -d @config.mypos.json
# expect: {"success":true,"terminal_type":"mypos"}
curl -s http://localhost:8895/health
# expect: {"status":"healthy","mode":"mypos","terminal_ready":true,"error_code":0}
kill %1
```

Failure path keeps previous state:

```bash
venv/bin/python kassafu.py --server --port 8896 > /tmp/opencode/kf-late2.log 2>&1 &
sleep 2
curl -s -X POST http://localhost:8896/config \
  -H 'Content-Type: application/json' -d @config.sumup.json > /dev/null
printf '{"mypos":{"gateway_url":"https://demo-api-gateway.mypos.com"}}' | curl -s -X POST \
  http://localhost:8896/config -H 'Content-Type: application/json' -d @-
# expect HTTP 400 whose detail mentions Failed to initialize
curl -s http://localhost:8896/health
# expect still: {"status":"healthy","mode":"sumup",...}  (old terminal preserved)
kill %1
```

- [ ] **Step 4: Commit**

```bash
git add kassafu.py
git commit -m "Rewrite POST /config as full replacement with terminal hot swap"
```
