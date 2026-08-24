# Terminal Config Auto-Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-detect the terminal type (sumup/mypos) from which top-level config section is present, fix the `--config` override ordering bug, and add two per-terminal test config files.

**Architecture:** New pure helper `_resolve_terminal_type(config)` in `kassafu.py` implements the precedence rules from the spec. `lifespan()` re-resolves `TERMINAL_TYPE` from the final loaded config (after any `--config` reload), fixing the import-time bug. Two new JSON configs let you switch terminals purely by choosing the file.

**Tech Stack:** Python 3 stdlib (`unittest`), FastAPI/uvicorn (existing deps), JSON configs.

**Spec:** `docs/superpowers/specs/2026-08-24-terminal-config-autodetect-design.md`

**Important repo notes:**
- Run all tests from the repo root with the venv interpreter: `venv/bin/python -m unittest ...` (importing `kassafu` needs fastapi/uvicorn/httpx from the venv, and writes `kassafu.log` to CWD — expected).
- Never `git add -A` / `git add .`. Stage only the files listed per step.
- Current worktree has unrelated changes (`test_reader_status.py` deleted, `test_reader_status_mypos.py` / `test_reader_status_sumup.py` untracked). Do not touch them.

---

### Task 1: `_resolve_terminal_type` helper (TDD)

**Files:**
- Create: `tests/test_kassafu_config.py`
- Modify: `kassafu.py` (add helper directly after `_get_terminal_class`, currently lines 83-89)

- [ ] **Step 1: Write the failing test**

Create `tests/test_kassafu_config.py`:

```python
import unittest

from kassafu import _resolve_terminal_type


class ResolveTerminalTypeTests(unittest.TestCase):
    def test_explicit_terminal_type_wins_over_sections(self):
        config = {"app": {"terminal_type": "mypos"}, "sumup": {"api_key": "k"}}
        self.assertEqual(_resolve_terminal_type(config), "mypos")

    def test_explicit_terminal_type_is_case_insensitive(self):
        config = {"app": {"terminal_type": "MyPOS"}, "sumup": {"api_key": "k"}}
        self.assertEqual(_resolve_terminal_type(config), "mypos")

    def test_explicit_unknown_terminal_type_falls_back_to_sumup(self):
        config = {"app": {"terminal_type": "sandbox"}}
        self.assertEqual(_resolve_terminal_type(config), "sumup")

    def test_mypos_only_section_detected(self):
        config = {"mypos": {"gateway_url": "https://demo-api-gateway.mypos.com"}}
        self.assertEqual(_resolve_terminal_type(config), "mypos")

    def test_sumup_only_section_detected(self):
        config = {"sumup": {"api_key": "k"}}
        self.assertEqual(_resolve_terminal_type(config), "sumup")

    def test_both_sections_default_to_sumup(self):
        config = {
            "sumup": {"api_key": "k"},
            "mypos": {"gateway_url": "https://demo-api-gateway.mypos.com"},
        }
        self.assertEqual(_resolve_terminal_type(config), "sumup")

    def test_no_sections_defaults_to_sumup(self):
        self.assertEqual(_resolve_terminal_type({}), "sumup")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m unittest tests.test_kassafu_config -v`
Expected: FAIL/ERROR with `ImportError: cannot import name '_resolve_terminal_type' from 'kassafu'`

- [ ] **Step 3: Implement the helper**

In `kassafu.py`, directly after the existing `_get_terminal_class` function (lines 83-89), add:

```python
def _resolve_terminal_type(cfg: dict) -> str:
    terminal_type = cfg.get("app", {}).get("terminal_type")
    if terminal_type:
        t = str(terminal_type).lower()
        if t in TERMINAL_CLASSES:
            return t
        logger.warning(f"Unknown terminal type '{terminal_type}', falling back to section detection")

    has_sumup = "sumup" in cfg
    has_mypos = "mypos" in cfg

    if has_mypos and not has_sumup:
        return "mypos"

    if has_sumup and has_mypos:
        logger.warning("Both 'sumup' and 'mypos' sections configured, defaulting to sumup")
    elif not has_sumup:
        logger.warning("No 'sumup' or 'mypos' section found, defaulting to sumup")
    return "sumup"
```

Then, directly after that function, add the module-level initial value (replaces the old lines 74-75 semantics):

```python
TERMINAL_TYPE = _resolve_terminal_type(config)
```

And delete the now-wrong module-level lines 74-75:

```python
TERMINAL_MODE = config.get("app", {}).get("mode", "sumup")
TERMINAL_TYPE = config.get("app", {}).get("terminal_type", TERMINAL_MODE)
```

(Keep `PORT = 8888` where it is.)

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m unittest tests.test_kassafu_config -v`
Expected: `OK` (7 tests pass)

- [ ] **Step 5: Run the full existing suite to check for regressions**

Run: `venv/bin/python -m unittest discover -s tests -v`
Expected: all existing tests still `OK`

- [ ] **Step 6: Commit**

```bash
git add kassafu.py tests/test_kassafu_config.py
git commit -m "Add terminal type auto-detection helper"
```

---

### Task 2: Resolve in `lifespan` (fixes `--config` bug)

**Files:**
- Modify: `kassafu.py:92-98` (`lifespan`)

- [ ] **Step 1: Re-resolve after any `--config` reload**

In `lifespan`, add the resolution line so the block reads:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global terminal, TERMINAL_TYPE

    TERMINAL_TYPE = _resolve_terminal_type(config)

    logger.info(f"KassaFu starting with terminal type '{TERMINAL_TYPE}' on port {PORT}")
```

The rest of `lifespan` stays unchanged — it already reads `TERMINAL_TYPE`, which is also consumed by `/health` and `/config` endpoints (kassafu.py:330-371). Because `__main__` reloads the global `config` before uvicorn starts, `lifespan` now sees the `--config` file's sections. This removes the import-time bug where `--config` could never change the terminal type.

- [ ] **Step 2: Verify startup picks the right terminal per config file**

No unit test here (would require booting the ASGI app); verified end-to-end in Task 3 Step 4 once both config files exist.

- [ ] **Step 3: Run the full suite again**

Run: `venv/bin/python -m unittest discover -s tests -v`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add kassafu.py
git commit -m "Resolve terminal type from effective config at startup"
```

---

### Task 3: Per-terminal test configs + end-to-end check

**Files:**
- Create: `config.sumup.json`
- Create: `config.mypos.json`

- [ ] **Step 1: Create `config.sumup.json`**

Exact copy of the current `config.json`:

```json
{
  "app": {
    "name": "KassaFu",
    "mode": "sandbox"
  },
  "sumup": {
    "api_key": "sup_sk_wFlGnnpuTlYCbiekkVN1uNjqbeqUS8H6U",
    "merchant_code": "MN2RA8M1",
    "reader_id": "rdr_6P0860A4S186MV3FHM2Q185AD7"
  }
}
```

- [ ] **Step 2: Create `config.mypos.json`**

Template with every key `MyPOSTerminal.init` requires; fill the REPLACE_* values with your myPOS sandbox credentials before real use:

```json
{
  "app": {
    "name": "KassaFu",
    "mode": "sandbox"
  },
  "mypos": {
    "gateway_url": "https://demo-api-gateway.mypos.com",
    "integration": {
      "client_id": "REPLACE_WITH_INTEGRATION_CLIENT_ID",
      "client_secret": "REPLACE_WITH_INTEGRATION_CLIENT_SECRET"
    },
    "partner_id": "mps-p-XXXXXXXX",
    "application_id": "mps-app-XXXXXXXX",
    "merchant": {
      "client_id": "cli_REPLACE",
      "client_secret": "sec_REPLACE"
    },
    "terminal_id": "80026232"
  }
}
```

- [ ] **Step 3: Sanity-check JSON validity of both files**

Run: `venv/bin/python -c "import json; json.load(open('config.sumup.json')); json.load(open('config.mypos.json')); print('both valid')"`
Expected: `both valid`

- [ ] **Step 4: End-to-end startup check for each config (no payments)**

SumUp (background, then stop):

```bash
venv/bin/python kassafu.py --server --config config.sumup.json > /tmp/opencode/kassafu-sumup.log 2>&1 &
sleep 3 && curl -s http://localhost:8888/health; kill %1
```

Expected health JSON contains `"mode":"sumup"` and the log contains
`KassaFu starting with terminal type 'sumup'`.

myPOS:

```bash
venv/bin/python kassafu.py --server --config config.mypos.json > /tmp/opencode/kassafu-mypos.log 2>&1 &
sleep 3 && curl -s http://localhost:8888/health; kill %1
```

Expected health JSON contains `"mode":"mypos"` and the log contains
`KassaFu starting with terminal type 'mypos'`.

(Both configs carry a terminal/reader ID, so startup performs no discovery
network calls; placeholder credentials are non-empty strings, so
`MyPOSTerminal.init` validation passes.)

Default config unchanged:

```bash
venv/bin/python kassafu.py --server > /tmp/opencode/kassafu-default.log 2>&1 &
sleep 3 && curl -s http://localhost:8888/health; kill %1
```

Expected: `"mode":"sumup"` (config.json has only a sumup section).

- [ ] **Step 5: Commit**

```bash
git add config.sumup.json config.mypos.json
git commit -m "Add per-terminal test config files"
```
