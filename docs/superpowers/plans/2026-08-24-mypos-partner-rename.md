# myPOS Partner Config Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the myPOS `integration` config block to `partner` and move `partner_id`/`application_id` into it, mirroring the partners.mypos.com summary page verbatim; old configs fail init with an explicit rename hint.

**Architecture:** Pure schema rename threaded through three layers: `MyPOSGateway` (reads credentials from `config["partner"]`), `MyPOSTerminal` (validates the new layout, builds the gateway dict in the new shape), and all test fixtures. One atomic task — splitting it would leave fixtures and implementation disagreeing about the schema.

**Tech Stack:** Python stdlib `unittest`, httpx (existing deps).

**Spec:** `docs/superpowers/specs/2026-08-24-mypos-partner-rename-design.md`

**Important repo notes:**
- Run tests from repo root: `venv/bin/python -m unittest discover -s tests -v` (45 tests currently green).
- The user's LIVE deployment (`~/zhongcan/kassafu.py`) listens on 127.0.0.1:8888 — NEVER kill it or bind port 8888; e2e checks use port 8895.
- Never `git add -A` / `git add .`; stage only files listed per step. Worktree has user WIP (`M test_reader_status_mypos.py`, untracked `.config.mypos.json.swp`) — leave untouched.
- `config.mypos.json` is gitignored (real credentials) — modify locally but NEVER stage it.
- Commit style: short imperative, no prefixes.

---

### Task 1: Rename `integration` → `partner` across gateway, terminal, and tests

**Files:**
- Modify: `mypos_gateway.py` (`__init__` lines ~51-68, `_request_integration_token` lines ~95-105)
- Modify: `mypos_terminal.py` (`__init__` attrs lines ~41-54, `init` lines ~65-120, `get_config` lines ~125-134)
- Modify: `tests/test_mypos_gateway.py` (`CONFIG` line ~9-16)
- Modify: `tests/test_mypos_terminal.py` (`CONFIG` line ~7-17, `InitTests` lines ~59-87)
- Modify: `tests/test_kassafu_config.py` (`MYPOS_CONFIG` line ~16-25, broken-config test line ~96-110)
- Modify locally (never commit): `config.mypos.json`

- [ ] **Step 1: Update test fixtures to the new layout**

In `tests/test_mypos_gateway.py`, replace:

```python
CONFIG = {
    "gateway_url": "https://demo-api-gateway.mypos.com",
    "integration": {"client_id": "client_integration", "client_secret": "secret_integration"},
    "partner_id": "mps-p-test",
    "application_id": "mps-app-test",
    "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
    "terminal_id": "80026232",
}
```

with:

```python
CONFIG = {
    "gateway_url": "https://demo-api-gateway.mypos.com",
    "partner": {
        "client_id": "client_integration",
        "client_secret": "secret_integration",
        "application_id": "mps-app-test",
        "partner_id": "mps-p-test",
    },
    "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
    "terminal_id": "80026232",
}
```

In `tests/test_mypos_terminal.py`, replace the `CONFIG` block:

```python
CONFIG = {
    "app": {"name": "KassaFu", "mode": "sandbox"},
    "mypos": {
        "gateway_url": "https://demo-api-gateway.mypos.com",
        "integration": {"client_id": "client_integration", "client_secret": "secret_integration"},
        "partner_id": "mps-p-test",
        "application_id": "mps-app-test",
        "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
        "terminal_id": "80026232",
    },
}
```

with:

```python
CONFIG = {
    "app": {"name": "KassaFu", "mode": "sandbox"},
    "mypos": {
        "gateway_url": "https://demo-api-gateway.mypos.com",
        "partner": {
            "client_id": "client_integration",
            "client_secret": "secret_integration",
            "application_id": "mps-app-test",
            "partner_id": "mps-p-test",
        },
        "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
        "terminal_id": "80026232",
    },
}
```

In the same file, replace `test_init_fails_without_gateway_url` and `test_init_fails_without_merchant_credentials` and add the old-key rejection test so `InitTests` reads:

```python
class InitTests(unittest.TestCase):
    def test_init_fails_without_gateway_url(self):
        t = MyPOSTerminal()
        config = {"mypos": {"partner": {"client_id": "x", "client_secret": "y"}}}
        self.assertFalse(t.init(config))

    def test_init_fails_without_merchant_credentials(self):
        t = MyPOSTerminal()
        config = {"mypos": {
            "gateway_url": "https://demo-api-gateway.mypos.com",
            "partner": {"client_id": "x", "client_secret": "y"},
        }}
        self.assertFalse(t.init(config))

    def test_init_rejects_old_integration_key(self):
        t = MyPOSTerminal()
        config = {"mypos": {
            "gateway_url": "https://demo-api-gateway.mypos.com",
            "integration": {"client_id": "client_old", "client_secret": "secret_old"},
            "merchant": {"client_id": "cli_x", "client_secret": "sec_x"},
        }}
        self.assertFalse(t.init(config))

    def test_init_ready_with_terminal_id(self):
        t = make_terminal()
        self.assertTrue(t.is_ready)
        self.assertEqual(t.terminal_id, "80026232")

    def test_get_config_excludes_secrets(self):
        t = make_terminal()
        cfg = t.get_config()
        mypos = cfg["mypos"]
        self.assertNotIn("integration", mypos)
        self.assertNotIn("merchant", mypos)
        self.assertEqual(
            mypos["partner"],
            {"partner_id": "mps-p-test", "application_id": "mps-app-test"}
        )
        self.assertEqual(mypos["terminal_id"], "80026232")
```

In `tests/test_kassafu_config.py`, replace:

```python
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
```

with:

```python
MYPOS_CONFIG = {
    "mypos": {
        "gateway_url": "https://demo-api-gateway.mypos.com",
        "partner": {
            "client_id": "ci",
            "client_secret": "cs",
            "application_id": "mps-app-test",
            "partner_id": "mps-p-test",
        },
        "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
        "terminal_id": "80026232",
    }
}
```

and in `test_invalid_config_keeps_previous_terminal`, replace:

```python
        broken = {
            "mypos": {
                k: v for k, v in MYPOS_CONFIG["mypos"].items() if k != "partner_id"
            }
        }
```

with:

```python
        broken = {
            "mypos": {
                k: v for k, v in MYPOS_CONFIG["mypos"].items() if k != "partner"
            }
        }
```

- [ ] **Step 2: Run suite to verify fixtures fail against old implementation**

Run: `venv/bin/python -m unittest discover -s tests -v`
Expected: failures/errors in gateway + terminal + config tests (implementation still reads `integration`). Count will differ from 45; that is fine — what matters is that the new-layout fixtures fail and nothing else regressed structurally.

- [ ] **Step 3: Update `mypos_gateway.py`**

In `MyPOSGateway.__init__`, replace:

```python
    def __init__(self, config: Dict, transport=None):
        self.gateway_url = config.get("gateway_url", "").rstrip("/")
        integration = config.get("integration", {})
        self.integration_client_id = integration.get("client_id", "")
        self.integration_client_secret = integration.get("client_secret", "")
        self.partner_id = config.get("partner_id", "")
        self.application_id = config.get("application_id", "")
        merchant = config.get("merchant", {})
        self.merchant_client_id = merchant.get("client_id", "")
        self.merchant_client_secret = merchant.get("client_secret", "")
        self._transport = transport
```

with:

```python
    def __init__(self, config: Dict, transport=None):
        self.gateway_url = config.get("gateway_url", "").rstrip("/")
        partner = config.get("partner", {})
        self.partner_client_id = partner.get("client_id", "")
        self.partner_client_secret = partner.get("client_secret", "")
        self.partner_id = partner.get("partner_id", "")
        self.application_id = partner.get("application_id", "")
        merchant = config.get("merchant", {})
        self.merchant_client_id = merchant.get("client_id", "")
        self.merchant_client_secret = merchant.get("client_secret", "")
        self._transport = transport
```

In `_request_integration_token`, replace the request body:

```python
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.integration_client_id,
                        "client_secret": self.integration_client_secret,
                    },
```

with:

```python
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.partner_client_id,
                        "client_secret": self.partner_client_secret,
                    },
```

(Method name `_get_integration_token` / `_request_integration_token` stays — it names the OAuth token, not the config block.)

Run: `venv/bin/python -m unittest tests.test_mypos_gateway -v`
Expected: all gateway tests PASS (fixtures already updated in Step 1).

- [ ] **Step 4: Update `mypos_terminal.py`**

Replace the attribute defaults in `__init__`:

```python
    def __init__(self):
        self.gateway_url = ""
        self.partner_client_id = ""
        self.partner_client_secret = ""
        self.partner_id = ""
        self.application_id = ""
        self.merchant_client_id = ""
        self.merchant_client_secret = ""
        self.terminal_id = None
```

(keep everything below `self.terminal_id = None` unchanged)

In `init()`, replace:

```python
            self.gateway_url = self.mypos_config.get("gateway_url", "").rstrip("/")
            integration = self.mypos_config.get("integration", {})
            self.integration_client_id = integration.get("client_id", "")
            self.integration_client_secret = integration.get("client_secret", "")
            self.partner_id = self.mypos_config.get("partner_id", "")
            self.application_id = self.mypos_config.get("application_id", "")
            merchant = self.mypos_config.get("merchant", {})
            self.merchant_client_id = merchant.get("client_id", "")
            self.merchant_client_secret = merchant.get("client_secret", "")
            self.terminal_id = self.mypos_config.get("terminal_id", None)

            if not self.gateway_url:
                logger.error("Missing mypos.gateway_url in configuration")
                return False
            if not self.integration_client_id or not self.integration_client_secret:
                logger.error("Missing mypos.integration.client_id or client_secret")
                return False
            if not self.partner_id or not self.application_id:
                logger.error("Missing mypos.partner_id or application_id")
                return False
            if not self.merchant_client_id or not self.merchant_client_secret:
                logger.error("Missing mypos.merchant.client_id or client_secret")
                return False

            self.gateway = MyPOSGateway({
                "gateway_url": self.gateway_url,
                "integration": {
                    "client_id": self.integration_client_id,
                    "client_secret": self.integration_client_secret,
                },
                "partner_id": self.partner_id,
                "application_id": self.application_id,
                "merchant": {
                    "client_id": self.merchant_client_id,
                    "client_secret": self.merchant_client_secret,
                },
            })
```

with:

```python
            self.gateway_url = self.mypos_config.get("gateway_url", "").rstrip("/")
            partner = self.mypos_config.get("partner", {})
            if not partner:
                logger.error("Missing mypos.partner credentials (renamed from 'integration')")
                return False
            self.partner_client_id = partner.get("client_id", "")
            self.partner_client_secret = partner.get("client_secret", "")
            self.partner_id = partner.get("partner_id", "")
            self.application_id = partner.get("application_id", "")
            merchant = self.mypos_config.get("merchant", {})
            self.merchant_client_id = merchant.get("client_id", "")
            self.merchant_client_secret = merchant.get("client_secret", "")
            self.terminal_id = self.mypos_config.get("terminal_id", None)

            if not self.gateway_url:
                logger.error("Missing mypos.gateway_url in configuration")
                return False
            if not self.partner_client_id or not self.partner_client_secret:
                logger.error("Missing mypos.partner.client_id or client_secret")
                return False
            if not self.partner_id or not self.application_id:
                logger.error("Missing mypos.partner.partner_id or application_id")
                return False
            if not self.merchant_client_id or not self.merchant_client_secret:
                logger.error("Missing mypos.merchant.client_id or client_secret")
                return False

            self.gateway = MyPOSGateway({
                "gateway_url": self.gateway_url,
                "partner": {
                    "client_id": self.partner_client_id,
                    "client_secret": self.partner_client_secret,
                    "application_id": self.application_id,
                    "partner_id": self.partner_id,
                },
                "merchant": {
                    "client_id": self.merchant_client_id,
                    "client_secret": self.merchant_client_secret,
                },
            })
```

Replace `get_config`:

```python
    def get_config(self) -> Dict:
        return {
            "app": self.app_config,
            "mypos": {
                "gateway_url": self.gateway_url,
                "partner_id": self.partner_id,
                "application_id": self.application_id,
                "terminal_id": self.terminal_id,
            }
        }
```

with:

```python
    def get_config(self) -> Dict:
        return {
            "app": self.app_config,
            "mypos": {
                "gateway_url": self.gateway_url,
                "partner": {
                    "partner_id": self.partner_id,
                    "application_id": self.application_id,
                },
                "terminal_id": self.terminal_id,
            }
        }
```

Run: `venv/bin/python -m unittest discover -s tests -v`
Expected: all 46 tests OK (45 existing adjusted + 1 new rejection test).

- [ ] **Step 5: Update local `config.mypos.json` (gitignored — never stage)**

Rewrite the file to the new layout, preserving the real values currently present:

```json
{
  "app": {
    "name": "KassaFu",
    "mode": "sandbox"
  },
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "partner": {
      "client_id": "<current integration.client_id value>",
      "client_secret": "<current integration.client_secret value>",
      "application_id": "<current top-level application_id value>",
      "partner_id": "<current top-level partner_id value>"
    },
    "merchant": {
      "client_id": "<unchanged>",
      "client_secret": "<unchanged>"
    },
    "terminal_id": "<unchanged>"
  }
}
```

Read the current file first and copy values verbatim — do not invent placeholders for real fields.

- [ ] **Step 6: End-to-end boot check (port 8895, NEVER 8888)**

```bash
venv/bin/python kassafu.py --server --config config.mypos.json --port 8895 > /tmp/opencode/kf-rename.log 2>&1 &
sleep 2 && curl -s http://localhost:8895/health; kill %1
```

Expected: `{"status":"healthy","mode":"mypos","terminal_ready":true,"error_code":0}` (boot validates fields only; no network call happens at startup). Also confirm `/tmp/opencode/kf-rename.log` contains no `Missing mypos.` errors.

Old-key rejection check:

```bash
printf '{"app":{"mode":"sandbox"},"mypos":{"gateway_url":"https://api-gateway.mypos.com","integration":{"client_id":"c","client_secret":"s"},"merchant":{"client_id":"m","client_secret":"n"}}}' > /tmp/opencode/old-key-config.json
venv/bin/python kassafu.py --server --config /tmp/opencode/old-key-config.json --port 8896 > /tmp/opencode/kf-oldkey.log 2>&1 &
sleep 2 && curl -s http://localhost:8896/health; kill %1
```

Expected health: `"status":"unconfigured"` (init failed) and log line `Missing mypos.partner credentials (renamed from 'integration')`.

- [ ] **Step 7: Commit**

```bash
git add mypos_gateway.py mypos_terminal.py tests/test_mypos_gateway.py tests/test_mypos_terminal.py tests/test_kassafu_config.py
git commit -m "Rename myPOS integration config block to partner"
```

---

## Self-Review Notes

- Spec coverage: new layout (Steps 3-4), old-key explicit failure (Step 4 + Step 1 test), fixture updates (Step 1), docs untouched (verified: README/API.md contain no mypos config examples), zhongcan out of scope (user handles), local config update (Step 5).
- Type consistency: `partner` dict carries exactly `client_id`, `client_secret`, `application_id`, `partner_id` everywhere (gateway reads, terminal builds, fixtures assert).
- No placeholders: real values copied by implementer in Step 5 from the existing file.
