# Remote Blob Config (partner + client URLs, 2 keys) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace inline terminal configs with remote encrypted blobs: `POST /config` / CLI take `{partner_url, client_url, partner_key, client_key, id}`; kassafu fetches+decrypts the client blob (SumUp or myPOS), fetches+decrypts the partner blob only for myPOS, and assembles + strictly validates the runtime config with no disk cache.

**Architecture:** `encrypt_partner.py` keeps `encrypt_file` / `decrypt_blob` / `parse_partner` (the crypto library + CLI tool) but loses its cache-writing `fetch_partner`. `kassafu.py` gains three pure helpers — `_fetch_blob_json(url, key, what)`, `_validate_client_config(cfg)`, `_resolve_remote_config(interface)` — used by `POST /config` and `_startup()`. Inline `{sumup}/{mypos}` POST bodies and the local `--config` file seed are dropped; the old `_merge_partner`, `--key`, `load_config_from_file`, and cache constants are removed.

**Tech Stack:** Python 3.12, Flask + waitress, httpx, cryptography (AES-256-GCM + PBKDF2-HMAC-SHA256), unittest.

---

## Design summary (from approved spec `2026-09-15-remote-blob-config-design.md`)

Interface body / CLI flags (5 fields):

```json
{"partner_url": "...", "client_url": "...", "partner_key": "...", "client_key": "...", "id": "..."}
```

- `partner_url`/`partner_key` optional (ignored for SumUp). Default partner URL: `http://www.kassaku.nl/restaurants/install/config.partner`.
- `client_url`, `client_key`, `id` required.
- Runtime: client blob → section-key detection (`sumup` vs `mypos`) → myPOS-only partner fetch → inject `id` → strict validation → terminal `.init()`.
- No disk cache; failures → `400 {"detail": "..."}`.
- `GET /config`: unconfigured → `{"message": "config not available, please check tomorrow"}`; configured → resolved config minus secrets.
- Client blob (sumup): `{"app": {...}, "sumup": {"api_key", "merchant_code"}}`.
- Client blob (mypos): `{"app": {...}, "mypos": {"gateway_url", "merchant": {"client_id", "client_secret"}}}`.
- Partner blob (mypos): `{"app": {...}, "partner": {"client_id", "client_secret", "application_id", "partner_id"}}`.

Terminal init contract is unchanged: `_apply_runtime_config` still takes a fully-resolved config.

---

## File structure

| File | Responsibility after this change |
| --- | --- |
| `encrypt_partner.py` | Crypto + CLI tool only. `encrypt_file`, `decrypt_blob`, `parse_partner`, `PARTNER_URL_DEFAULT`. No fetch, no cache. |
| `kassafu.py` | Server. `_fetch_blob_json`, `_validate_client_config`, `_resolve_remote_config`, POST /config, GET /config, `_startup`, CLI flags. |
| `tests/test_encrypt_partner.py` | Crypto + parse tests; fetch/cache tests removed. |
| `tests/test_kassafu_config.py` | `_resolve_remote_config` / `_validate_client_config` / `_fetch_blob_json` unit tests (no network). |
| `tests/test_kassafu_endpoints.py` | Config endpoint tests for the 5-field body; GET /config response. |
| `test_reader_status_mypos.py` | Live script: POST the 5-field body instead of pushing config.mypos.json. |

---

### Task 1: Slim `encrypt_partner.py` — new default URL, remove `fetch_partner`

**Files:**
- Modify: `encrypt_partner.py`
- Modify: `tests/test_encrypt_partner.py`

- [ ] **Step 1: Update the default URL constant**

In `encrypt_partner.py`, change line 23 to:

```python
PARTNER_URL_DEFAULT = "http://www.kassaku.nl/restaurants/install/config.partner"
```

- [ ] **Step 2: Remove `fetch_partner`**

Delete the whole `fetch_partner` function (currently lines 122-150) from `encrypt_partner.py`. Also remove the now-unused `import httpx` — wait, check: after deleting `fetch_partner`, is `httpx` referenced anywhere else in the file? If not, remove the `import httpx` line. Also remove the `logger` warning about cache writing if `logger` is now unused — it is still used by nothing else in this file after deletion, so remove `import logging` and `logger = logging.getLogger(__name__)` too. (Verify with `rg "httpx|logger" encrypt_partner.py`.)

- [ ] **Step 3: Update the module docstring**

The docstring at the top says "...and the importable crypto/fetch library kassafu uses at runtime." Change the second paragraph to:

```python
Also the importable crypto library kassafu uses at runtime (decrypt_blob + parse_partner).
```

- [ ] **Step 4: Remove the `FetchPartnerTests` class and fix `test_default_url`**

In `tests/test_encrypt_partner.py`:
- Delete the entire `FetchPartnerTests` class (lines 92-121).
- Remove `fetch_partner` from the import list at the top (line 14).
- Remove `import httpx` (line 7) and `from unittest import mock` (line 5) if they are now unused (they are only used by the deleted tests).
- Update `test_default_url` expectation (it was the last test in FetchPartnerTests) — move a `test_default_url` into `EncryptDecryptTests` (or a tiny new `DefaultUrlTests` class) asserting:

```python
    def test_default_url(self):
        self.assertEqual(
            PARTNER_URL_DEFAULT,
            "http://www.kassaku.nl/restaurants/install/config.partner",
        )
```

- [ ] **Step 5: Run the encrypt_partner tests**

Run: `venv/bin/python -m unittest tests.test_encrypt_partner -v`
Expected: ALL PASS. Count = 10 tests (5 EncryptDecrypt + 5 ParsePartner + 1 DefaultUrl; the 4 FetchPartnerTests are gone).

- [ ] **Step 6: Commit**

```bash
git add encrypt_partner.py tests/test_encrypt_partner.py
git commit -m "refactor: remove fetch_partner cache path, update default partner url"
```

---

### Task 2: Add the three resolution helpers to `kassafu.py` (tests first)

**Files:**
- Modify: `tests/test_kassafu_config.py`
- Modify: `kassafu.py`

- [ ] **Step 1: SRP hook — check current test scaffolding**

`tests/test_kassafu_config.py` currently imports `_merge_partner` (line 7), defines `MYPOS_CONFIG_NO_PARTNER` and `FAKE_PARTNER` (lines 125-140), and a `MergePartnerTests` class (lines 143-187). These all become obsolete. BEFORE writing new tests, replace the import line 7:

```python
from kassafu import _apply_runtime_config, _resolve_remote_config, _resolve_terminal_type
```

Keep `from encrypt_partner import PARTNER_URL_DEFAULT, PartnerConfigError` (line 6). Keep `SUMUP_CONFIG`, `MYPOS_CONFIG` (used by `ResolveTerminalTypeTests` / `ApplyRuntimeConfigTests`).

- [ ] **Step 2: Write the failing tests for `_resolve_remote_config`**

Append a new `RemoteResolveTests` class before `if __name__ == "__main__":`, and delete `MergePartnerTests`, `MYPOS_CONFIG_NO_PARTNER`, `FAKE_PARTNER`, and the now-unused `from copy import deepcopy` import:

```python
CLIENT_SUMUP = {"sumup": {"api_key": "sup_sk_test", "merchant_code": "M1234567"}}
CLIENT_MYPOS = {"mypos": {"gateway_url": "https://demo-api-gateway.mypos.com",
                          "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"}}}
PARTNER_OBJ = {"client_id": "ci", "client_secret": "cs",
               "application_id": "mps-app-test", "partner_id": "mps-p-test"}


class RemoteResolveTests(unittest.TestCase):
    def test_sumup_client_resolves_with_id(self):
        interface = {"client_url": "http://c/sumup.blob", "client_key": "k",
                     "id": "rdr_123"}
        blob_url_by_type = {"sumup": CLIENT_SUMUP}
        with mock.patch("kassafu._fetch_blob_json", return_value=CLIENT_SUMUP) as fetch:
            resolved = _resolve_remote_config(interface)
        fetch.assert_called_once_with("http://c/sumup.blob", "k", "client")
        self.assertEqual(resolved["sumup"]["reader_id"], "rdr_123")
        self.assertNotIn("partner", resolved)

    def test_sumup_does_not_fetch_partner(self):
        interface = {"client_url": "http://c/s.blob", "client_key": "k", "id": "r"}
        with mock.patch("kassafu._fetch_blob_json", return_value=CLIENT_SUMUP) as fetch:
            _resolve_remote_config(interface)
        self.assertEqual(fetch.call_count, 1)

    def test_mypos_resolves_and_injects_partner(self):
        def fake_fetch(url, key, what):
            return CLIENT_MYPOS if what == "client" else {"partner": PARTNER_OBJ}

        interface = {"partner_url": "http://p/partner.blob", "partner_key": "pk",
                     "client_url": "http://c/m.blob", "client_key": "ck", "id": "80581413"}
        with mock.patch("kassafu._fetch_blob_json", side_effect=fake_fetch) as fetch:
            resolved = _resolve_remote_config(interface)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(resolved["mypos"]["terminal_id"], "80581413")
        self.assertEqual(resolved["mypos"]["partner"], PARTNER_OBJ)

    def test_mypos_uses_default_partner_url_when_absent(self):
        def fake_fetch(url, key, what):
            return CLIENT_MYPOS if what == "client" else {"partner": PARTNER_OBJ}

        interface = {"partner_key": "pk", "client_url": "http://c/m.blob",
                     "client_key": "ck", "id": "80581413"}
        with mock.patch("kassafu._fetch_blob_json", side_effect=fake_fetch) as fetch:
            _resolve_remote_config(interface)
        self.assertEqual(fetch.call_args_list[1][0][0], PARTNER_URL_DEFAULT)

    def test_missing_client_url_raises(self):
        with self.assertRaises(PartnerConfigError):
            _resolve_remote_config({"client_key": "k", "id": "1"})

    def test_missing_client_key_raises(self):
        with self.assertRaises(PartnerConfigError):
            _resolve_remote_config({"client_url": "http://c/b", "id": "1"})

    def test_missing_id_raises(self):
        with self.assertRaises(PartnerConfigError):
            _resolve_remote_config({"client_url": "http://c/b", "client_key": "k"})

    def test_mypos_missing_partner_key_raises(self):
        interface = {"client_url": "http://c/m.blob", "client_key": "ck", "id": "1"}
        with mock.patch("kassafu._fetch_blob_json", return_value=CLIENT_MYPOS):
            with self.assertRaises(PartnerConfigError):
                _resolve_remote_config(interface)

    def test_client_missing_both_sections_raises(self):
        interface = {"client_url": "http://c/b", "client_key": "k", "id": "1"}
        with mock.patch("kassafu._fetch_blob_json", return_value={"app": {"name": "KassaFu"}}):
            with self.assertRaises(PartnerConfigError):
                _resolve_remote_config(interface)

    def test_client_missing_required_keys_raises(self):
        interface = {"client_url": "http://c/b", "client_key": "k", "id": "1"}
        with mock.patch("kassafu._fetch_blob_json", return_value={"sumup": {"api_key": "only"}}):
            with self.assertRaises(PartnerConfigError):
                _resolve_remote_config(interface)

    def test_partner_object_missing_fields_raises(self):
        interface = {"partner_key": "pk", "client_url": "http://c/m.blob",
                     "client_key": "ck", "id": "1"}
        with mock.patch(
            "kassafu._fetch_blob_json",
            side_effect=lambda url, key, what: (
                CLIENT_MYPOS if what == "client" else {"partner": {"client_id": "only"}}
            ),
        ):
            with self.assertRaises(PartnerConfigError):
                _resolve_remote_config(interface)
```

(The `mock`, `_resolve_remote_config`, `PARTNER_URL_DEFAULT`, `PartnerConfigError` names must already be imported at the top of the test module.)

- [ ] **Step 3: Run to verify the new tests fail**

Run: `venv/bin/python -m unittest tests.test_kassafu_config.RemoteResolveTests -v`
Expected: FAIL/ERROR — `_resolve_remote_config` is not defined yet (and the obsolete MergePartnerTests import will also error — fix Step 1 first so the module imports and only RemoteResolveTests fail).

- [ ] **Step 4: Add `import httpx` and switch the kassafu.py import**

In `kassafu.py`:
- Add `import httpx` in the stdlib/third-party import block (next to `import json`).
- Replace the `from encrypt_partner import (...)` block (lines 39-43) with:

```python
from encrypt_partner import (
    PARTNER_URL_DEFAULT,
    PartnerConfigError,
    decrypt_blob,
)
```

- Remove the module globals `KASSAFU_PARTNER_KEY = None` and `PARTNER_CACHE_DEFAULT = "partner.xml.enc"` (lines 83-84), and add:

```python
KASSAFU_INTERFACE = {}
```

- [ ] **Step 5: Add the three helper functions**

Insert after `_resolve_terminal_type` (before the old `_merge_partner`), and DELETE the entire old `_merge_partner` function (currently lines 117-140):

```python
def _fetch_blob_json(url: str, key: str, what: str) -> dict:
    """GET a remote blob URL, decrypt it, and parse its JSON.

    what is 'client' or 'partner' and only shapes the error message.
    Raises PartnerConfigError with a prefix identifying the blob.
    """
    try:
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        if response.is_error:
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise PartnerConfigError(f"Failed to fetch {what} configuration from {url}: {exc}")

    try:
        plaintext = decrypt_blob(response.content, key)
    except PartnerConfigError as exc:
        raise PartnerConfigError(f"Failed to decrypt {what} configuration: {exc}")

    try:
        data = json.loads(plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PartnerConfigError(f"Failed to parse {what} configuration: {exc}")
    if not isinstance(data, dict):
        raise PartnerConfigError(f"{what} configuration is not a JSON object")
    return data


def _validate_client_config(cfg: dict) -> str:
    """Strict-validate a decrypted client config; return 'sumup' or 'mypos'."""
    has_sumup = "sumup" in cfg
    has_mypos = "mypos" in cfg
    if has_sumup == has_mypos:
        raise PartnerConfigError(
            "Client configuration must contain exactly one of 'sumup' or 'mypos'"
        )

    if has_sumup:
        sumup = cfg["sumup"]
        if not isinstance(sumup, dict):
            raise PartnerConfigError("Missing sumup section in client configuration")
        if not sumup.get("api_key"):
            raise PartnerConfigError("Missing sumup.api_key in client configuration")
        if not sumup.get("merchant_code"):
            raise PartnerConfigError("Missing sumup.merchant_code in client configuration")
        return "sumup"

    mypos = cfg["mypos"]
    if not isinstance(mypos, dict):
        raise PartnerConfigError("Missing mypos section in client configuration")
    if not mypos.get("gateway_url"):
        raise PartnerConfigError("Missing mypos.gateway_url in client configuration")
    merchant = mypos.get("merchant")
    if not isinstance(merchant, dict):
        raise PartnerConfigError("Missing mypos.merchant in client configuration")
    if not merchant.get("client_id") or not merchant.get("client_secret"):
        raise PartnerConfigError(
            "Missing mypos.merchant.client_id/client_secret in client configuration"
        )
    return "mypos"


def _resolve_remote_config(interface: dict) -> dict:
    """Turn the 5 interface fields into a fully-resolved runtime config."""
    client_url = interface.get("client_url") or ""
    client_key = interface.get("client_key") or ""
    device_id = interface.get("id") or ""
    if not client_url or not client_key or not device_id:
        raise PartnerConfigError(
            "Missing client_url, client_key or id in configuration"
        )

    partner_url = interface.get("partner_url") or PARTNER_URL_DEFAULT
    partner_key = interface.get("partner_key") or ""

    client = _fetch_blob_json(client_url, client_key, "client")
    term_type = _validate_client_config(client)

    if term_type == "mypos":
        if not partner_key:
            raise PartnerConfigError(
                "Missing partner_key for myPOS client configuration"
            )
        partner_doc = _fetch_blob_json(partner_url, partner_key, "partner")
        partner_obj = partner_doc.get("partner")
        if not isinstance(partner_obj, dict):
            raise PartnerConfigError(
                "Missing partner.partner object in partner configuration"
            )
        for field in ("client_id", "client_secret", "application_id", "partner_id"):
            if not partner_obj.get(field):
                raise PartnerConfigError(
                    f"Missing partner partner.{field} in partner configuration"
                )
        client["mypos"]["partner"] = partner_obj
        client["mypos"]["terminal_id"] = device_id
    else:
        client["sumup"]["reader_id"] = device_id

    client.setdefault("app", {})
    return client
```

- [ ] **Step 6: Run to verify the new tests pass**

Run: `venv/bin/python -m unittest tests.test_kassafu_config -v`
Expected: ALL PASS — `RemoteResolveTests` (11 tests) + `ResolveTerminalTypeTests` (7) + `ApplyRuntimeConfigTests` (6) = 24 config tests pass. `MergePartnerTests` is gone.

- [ ] **Step 7: Run the full suite (red expected elsewhere)**

Run: `venv/bin/python -m unittest discover -s tests 2>&1 | tail -20`
Expected: FAILURES in `tests/test_kassafu_endpoints.py` (they still reference `kassafu.fetch_partner` and post inline configs) and possibly an import error. This is expected — Task 4 fixes the endpoints. Note the failures but do NOT fix endpoint tests in this task.

- [ ] **Step 8: Commit (partial)**

```bash
git add kassafu.py tests/test_kassafu_config.py
git commit -m "feat: add remote blob resolution helpers to kassafu"
```

---

### Task 3: Rewrite the config endpoint tests + routes (POST /config, GET /config)

**Files:**
- Modify: `tests/test_kassafu_endpoints.py`
- Modify: `kassafu.py`

- [ ] **Step 1: Update the endpoint test scaffolding**

In `tests/test_kassafu_endpoints.py`:
- The `get_config()` in `FakeTerminal` stays as-is.
- Replace the `ConfigEndpointTests` class (currently lines 228-294) entirely with:

```python
class ConfigEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    INTERFACE = {
        "client_url": "http://example.test/client.blob",
        "client_key": "client-key",
        "id": "80026232",
    }

    def test_get_config_without_terminal_returns_message(self):
        r = self.client.get("/config")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.get_json(), {"message": "config not available, please check tomorrow"}
        )

    def test_post_config_rejected_during_active_payment(self):
        kassafu.active_payment = True
        r = self.client.post("/config", json=self.INTERFACE)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error_code"], 108012)

    def test_post_config_non_dict_returns_400(self):
        r = self.client.post("/config", json="nope")
        self.assertEqual(r.status_code, 400)
        self.assertIn("JSON object", r.get_json()["detail"])

    def test_post_config_missing_id_returns_400(self):
        body = {"client_url": "http://example.test/c.blob", "client_key": "k"}
        r = self.client.post("/config", json=body)
        self.assertEqual(r.status_code, 400)
        self.assertIn("client_url, client_key or id", r.get_json()["detail"])

    def test_post_config_sumup_success(self):
        resolved = {
            "app": {"name": "KassaFu"},
            "sumup": {"api_key": "sup_sk_test", "merchant_code": "M1234567",
                      "reader_id": "80026232"},
        }
        with mock.patch("kassafu._resolve_remote_config", return_value=resolved):
            r = self.client.post("/config", json=self.INTERFACE)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["terminal_type"], "sumup")
        self.assertIsNotNone(kassafu.terminal)

    def test_post_config_mypos_success(self):
        resolved = {
            "app": {"name": "KassaFu"},
            "mypos": {
                "gateway_url": "https://demo-api-gateway.mypos.com",
                "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
                "terminal_id": "80026232",
                "partner": {"client_id": "ci", "client_secret": "cs",
                            "application_id": "mps-app-test", "partner_id": "mps-p-test"},
            },
        }
        with mock.patch("kassafu._resolve_remote_config", return_value=resolved):
            r = self.client.post("/config", json=self.INTERFACE)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["terminal_type"], "mypos")
        self.assertIsNotNone(kassafu.terminal)

    def test_post_config_resolution_error_returns_400(self):
        with mock.patch(
            "kassafu._resolve_remote_config",
            side_effect=PartnerConfigError("Failed to fetch client configuration"),
        ):
            r = self.client.post("/config", json=self.INTERFACE)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Failed to fetch client configuration", r.get_json()["detail"])
```

Note: `mock`, `PartnerConfigError` are already imported at the top of the file; `_reset_state`, `SUMUP_CONFIG`, `FakeTerminal` remain from earlier classes.

- [ ] **Step 2: Run to verify the new endpoint tests fail**

Run: `venv/bin/python -m unittest tests.test_kassafu_endpoints.ConfigEndpointTests -v`
Expected: mostly FAIL — the routes still call `_merge_partner` and old behavior.

- [ ] **Step 3: Update `POST /config` in kassafu.py**

Replace `update_config()` (currently lines 521-538) with:

```python
@app.post("/config")
def update_config():
    """Replace runtime configuration and hot-swap the terminal (in-memory only)"""
    new_config = request.get_json(silent=True)
    if not isinstance(new_config, dict):
        return {"detail": "Configuration must be a JSON object"}, 400

    try:
        resolved = _resolve_remote_config(new_config)
    except PartnerConfigError as exc:
        return {"detail": str(exc)}, 400

    body, status = bridge.run(_apply_config_atomic(resolved))

    if status == 200:
        try:
            bridge.run(_maybe_discover(terminal, TERMINAL_TYPE))
        except Exception as exc:  # discovery problems must not fail an applied config
            logger.warning(f"Post-swap discovery failed: {exc}")

    return body, status
```

- [ ] **Step 4: Update `GET /config` in kassafu.py**

Replace `get_config()` (currently lines 511-518) with:

```python
@app.get("/config")
def get_config():
    """Return the resolved runtime config (secrets excluded)."""
    if not terminal:
        return {"message": "config not available, please check tomorrow"}
    cfg = terminal.get_config()
    cfg["app"]["mode"] = TERMINAL_TYPE
    return cfg
```

- [ ] **Step 5: Run the endpoint tests**

Run: `venv/bin/python -m unittest tests.test_kassafu_endpoints.ConfigEndpointTests -v`
Expected: ALL PASS (8 tests). Then full file: `venv/bin/python -m unittest tests.test_kassafu_endpoints -v` — all endpoint classes pass.

- [ ] **Step 6: Run the full suite**

Run: `venv/bin/python -m unittest discover -s tests`
Expected: ALL PASS. Count: 94 − 4 (FetchPartner) − 6 (MergePartner) + 11 (RemoteResolve) + 0 net on ConfigEndpointTests (was 6, now 8 = +2) = **97 tests**.

- [ ] **Step 7: Commit**

```bash
git add kassafu.py tests/test_kassafu_endpoints.py
git commit -m "feat: switch config endpoints to remote blob resolution"
```

---

### Task 4: `_startup` resolution + new CLI flags (drop `--config`, `--key`)

**Files:**
- Modify: `kassafu.py`

- [ ] **Step 1: Remove `load_config_from_file`**

Delete the `load_config_from_file` function (currently lines 50-63) from `kassafu.py`. It is only used by the old `--config` path.

- [ ] **Step 2: Update `_startup()`**

Replace the start of `_startup()` (currently lines 227-245) with:

```python
    global terminal, TERMINAL_TYPE, payment_queue, config

    if KASSAFU_INTERFACE.get("client_url"):
        try:
            config = _resolve_remote_config(KASSAFU_INTERFACE)
        except PartnerConfigError as exc:
            logger.error(f"Remote configuration unavailable: {exc}")

    if any(name in config for name in TERMINAL_CLASSES):
        TERMINAL_TYPE = _resolve_terminal_type(config)
        logger.info(f"KassaFu starting with terminal type '{TERMINAL_TYPE}' on port {PORT}")

        candidate = _get_terminal_class(TERMINAL_TYPE)()
        if not bridge.call_in_loop(candidate.init, config):
            logger.error(f"Failed to initialize {TERMINAL_TYPE} terminal - continuing unconfigured")
        else:
            terminal = candidate
            bridge.run(_maybe_discover(terminal, TERMINAL_TYPE))
    else:
        logger.info("KassaFu started without configuration - waiting for POST /config")

    payment_queue = bridge.call_in_loop(asyncio.Queue)
    bridge.create_task(process_payment_queue())
```

(The rest of `_startup` stays; the old `config = _merge_partner(config)` line is removed.)

- [ ] **Step 3: Replace the CLI flags in `__main__`**

Replace the argparse block (currently lines 544-557) with:

```python
    parser = argparse.ArgumentParser(description="KassaFu Payment Bridge")
    parser.add_argument("--server", action="store_true", help="Run in server mode")
    parser.add_argument("--port", type=int, help="Override port (default: 8888)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose HTTP logging (masked secrets)")
    parser.add_argument("--partner-url", type=str, help="Partner blob URL (myPOS only)")
    parser.add_argument("--client-url", type=str, help="Client blob URL")
    parser.add_argument("--partner-key", type=str, help="Partner blob encryption key (myPOS only)")
    parser.add_argument("--client-key", type=str, help="Client blob encryption key")
    parser.add_argument("--id", type=str, help="Device id (terminal_id / reader_id)")
    args = parser.parse_args()

    if args.debug:
        import os
        os.environ["KASSAFU_HTTP_DEBUG"] = "1"

    if args.partner_url:
        KASSAFU_INTERFACE["partner_url"] = args.partner_url
    if args.client_url:
        KASSAFU_INTERFACE["client_url"] = args.client_url
    if args.partner_key:
        KASSAFU_INTERFACE["partner_key"] = args.partner_key
    if args.client_key:
        KASSAFU_INTERFACE["client_key"] = args.client_key
    if args.id:
        KASSAFU_INTERFACE["id"] = args.id
```

- [ ] **Step 4: Update the usage text**

The non-server branch prints usage; replace lines 568-570 with:

```python
        print("Usage: python3 kassafu.py --server --client-url <url> --client-key <key> --id <id>")
        print("Optional: --partner-url/--partner-key (myPOS only), --port 8888")
```

- [ ] **Step 5: CLI sanity check (no server)**

Run: `venv/bin/python kassafu.py` (no args) and `venv/bin/python kassafu.py --help`
Expected: usage text prints; `--help` shows the 5 new flags and no `--config`/`--key`.

- [ ] **Step 6: Run the full suite**

Run: `venv/bin/python -m unittest discover -s tests`
Expected: still 97 tests, ALL PASS (no behavior change, just wiring).

- [ ] **Step 7: Commit**

```bash
git add kassafu.py
git commit -m "feat: resolve remote config at startup via new cli flags"
```

---

### Task 5: Update the live reader test script for the new interface

**Files:**
- Modify: `test_reader_status_mypos.py`

- [ ] **Step 1: Read the current script**

Read `test_reader_status_mypos.py` fully. It currently loads `config.mypos.json` (a local file with a `mypos` section) and POSTs it, plus a `PARTNER_KEY` constant injected into the config before pushing.

- [ ] **Step 2: Replace the push with the 5-field interface**

Replace the config-loading + push logic so the script POSTs the new interface body:

```python
CONFIG_FILE = os.environ.get('KASSAFU_CONFIG', 'config.mypos.json')

PARTNER_KEY = os.environ.get("KASSAFU_PARTNER_KEY", "//B1a9r6t8//")
CLIENT_KEY = os.environ.get("KASSAFU_CLIENT_KEY", "//B1a9r6t8//")
PARTNER_URL = os.environ.get(
    "KASSAFU_PARTNER_URL", "http://www.kassaku.nl/restaurants/install/config.partner"
)
CLIENT_URL = os.environ.get("KASSAFU_CLIENT_URL", "http://www.kassaku.nl/restaurants/install/config.id")

def push_config():
    """Push the remote-config interface to the running server."""
    client_url = CLIENT_URL
    if "{id}" in client_url:
        client_url = client_url.replace("{id}", os.environ.get("KASSAFU_ID", ""))
    if not client_url:
        print("❌ KASSAFU_CLIENT_URL is required")
        return

    payload = {
        "partner_url": PARTNER_URL,
        "client_url": client_url,
        "partner_key": PARTNER_KEY,
        "client_key": CLIENT_KEY,
        "id": os.environ.get("KASSAFU_ID", ""),
    }
    try:
        resp = requests.post('http://localhost:8888/config', json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"✅ Config pushed to KassaFu (terminal: {resp.json().get('terminal_type', '?')})")
        else:
            print(f"❌ Config push failed ({resp.status_code}): {resp.json()}")
    except requests.RequestException as exc:
        print(f"❌ Config push failed: {exc}")
```

(The exact body/flow must match what the CURRENT script does — keep its structure, health-check calls, storage ID handling if any, and terminal status checks unchanged. Only the config-push section and the constants change.)

- [ ] **Step 3: Syntax check**

Run: `venv/bin/python -c "import ast; ast.parse(open('test_reader_status_mypos.py').read())"` — no output = OK.

- [ ] **Step 4: Commit**

```bash
git add test_reader_status_mypos.py
git commit -m "feat: push remote-config interface from reader test script"
```

---

### Task 6: Docs + example config cleanup

**Files:**
- Modify: `README.md`
- Modify: `API.md`
- Modify: `docs/remote-config-flow.dot` (only if it references inline config; otherwise skip)

- [ ] **Step 1: README — replace the config section**

Read the myPOS config example section (around lines 55-73) and the "Hosting myPOS partner credentials" subsection in `README.md`. Replace the myPOS JSON block with the 5-field interface example:

```json
POST /config
{
  "partner_url": "http://www.kassaku.nl/restaurants/install/config.partner",
  "client_url": "http://www.kassaku.nl/restaurants/install/config.80581413",
  "partner_key": "your-partner-secret",
  "client_key": "your-client-secret",
  "id": "80581413"
}
```

And update the hosting subsection so it shows how to encrypt BOTH files:

````markdown
### Hosting myPOS partner credentials

The myPOS credentials live in two encrypted files hosted on kassaku.nl:

- `config.partner` — the provider/partner credentials (`partner` object).
- `config.<id>` — the customer/merchant credentials (the `mypos` or `sumup`
  object, one file per terminal id).

Build them from plaintext JSON with `encrypt_partner.py`:

```bash
python3 encrypt_partner.py --key "your-partner-secret" --input partner.json --output config.partner
python3 encrypt_partner.py --key "your-client-secret" --input client.json --output config.80581413
# upload both to the hosted directory
```

Keys are never stored in code, config, or git. They are supplied at runtime
via `POST /config` (or the matching CLI flags) and never returned by `GET /config`.
````

- [ ] **Step 2: API.md — update POST /config and GET /config**

In `API.md`, replace the `POST /config` myPOS example body (currently the inline `{app, mypos: {gateway_url, partner_url, partner_key, ...}}` form) with the 5-field interface body (same JSON as README above). Under it keep/adapt the note: "The `partner` and `mypos`/`sumup` sections are fetched and decrypted from `partner_url` / `client_url`; **do not** send them inline. Keys are read from the request and never returned by `GET /config`."

Also update any `GET /config` example to the new unconfigured message `{"message": "config not available, please check tomorrow"}` and the note that a configured `/config` returns the resolved config minus secrets.

- [ ] **Step 3: SOFTWARE.md**

`SOFTWARE.md` already lists `cryptography` — no change needed. Verify only (`git diff --stat` off this step).

- [ ] **Step 4: Remove stale local config references (.gitignore / docs)**

- `.gitignore` currently ignores `config.partner.json`, `partner.xml.enc`, `partner.xml.enc.*`. Add one line under that block if absent:

```gitignore
config.<id>.plain
```

(Deployment of the actual blob files stays out of git; no other change needed unless `docs/remote-config-flow.dot` mentions `partner.xml.enc` — if so, update the labels to `config.partner` and `config.<id>`.)

- [ ] **Step 5: Commit**

```bash
git add README.md API.md .gitignore docs/remote-config-flow.dot
git commit -m "docs: document remote blob config interface"
```

(Skip `docs/remote-config-flow.dot` in the `git add` if it had no changes.)

---

### Task 7: Version 1.0 marker + `/version` endpoint

**Files:**
- Modify: `kassafu.py`
- Modify: `tests/test_kassafu_endpoints.py`
- Modify: `README.md` (mention the endpoint briefly)

- [ ] **Step 1: Add the version constant**

In `kassafu.py`, at module level (next to `TERMINAL_CLASSES`), add:

```python
__version__ = "1.0.0"
```

- [ ] **Step 2: Add the tests**

In `tests/test_kassafu_endpoints.py`, append to `ConfigEndpointTests`:

```python
    def test_version_endpoint_returns_1_0_0(self):
        r = self.client.get("/version")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.get_json(),
            {"app": "KassaFu", "version": "1.0.0"},
        )
```

- [ ] **Step 3: Add the route**

In `kassafu.py`, add (near the other simple GET routes, e.g. right after `get_config`):

```python
@app.get("/version")
def version():
    """Return the KassaFu version."""
    return {"app": "KassaFu", "version": __version__}
```

- [ ] **Step 4: Run config endpoint tests**

Run: `venv/bin/python -m unittest tests.test_kassafu_endpoints.ConfigEndpointTests -v`
Expected: ALL PASS (now 9 tests in this class).

- [ ] **Step 5: Document in README**

In `README.md`, under the API example section, add one line to the `GET /version` example list:

```json
GET /version   -> {"app": "KassaFu", "version": "1.0.0"}
```

- [ ] **Step 6: Commit**

```bash
git add kassafu.py tests/test_kassafu_endpoints.py README.md
git commit -m "feat: version 1.0 with /version endpoint"
```

---

### Task 8: Full verification

- [ ] **Step 1: Full suite**

Run: `venv/bin/python -m unittest discover -s tests`
Expected: ALL PASS (97 tests), 0 failures/errors.

- [ ] **Step 2: Secret grep**

Run: `git grep -n "client_dc3eea\|secret_9ed708\|sup_sk_wFlGnnpuTlYCbiekkVN1uNjqbeqUS8H6U\|B1a9r6t8" -- ':!docs/superpowers/plans/*' ':!docs/superpowers/specs/*'`
Expected: no matches outside plan/spec docs. The example passphrase `//B1a9r6t8//` may appear in `encrypt_partner.py`'s docstring and `test_reader_status_mypos.py` defaults (known, user-owned, will be rotated).

- [ ] **Step 3: Live smoke test (remote blobs, test data)**

In `/tmp/opencode/remote_smoke`, create two plaintext files and encrypt them:

```bash
# partner.json -> {"partner": {"client_id":"ci","client_secret":"cs","application_id":"app","partner_id":"pi"}}
# client_sumup.json -> {"sumup": {"api_key":"sup_sk_test","merchant_code":"M1234567"}}
/usr/bin/openssl list-message-digests >/dev/null 2>&1  # sanity only; use venv python below
venv/bin/python encrypt_partner.py --key "PK" --input /tmp/opencode/remote_smoke/partner.json --output /tmp/opencode/remote_smoke/config.partner
venv/bin/python encrypt_partner.py --key "CK" --input /tmp/opencode/remote_smoke/client_sumup.json --output /tmp/opencode/remote_smoke/config.rdr1
```

Host `/tmp/opencode/remote_smoke` with `python3 -m http.server` on a port, then run one smoke script all in a single bash invocation (blockshell style):

```bash
#!/bin/bash
set -uo pipefail
cd /tmp/opencode/remote_smoke
python3 -m http.server 8199 >serve.log 2>&1 & BLOB_PID=$!
sleep 1
/home/mensfort/workspace/kassafu/venv/bin/python /home/mensfort/workspace/kassafu/kassafu.py \
  --server --client-url http://127.0.0.1:8199/config.rdr1 --client-key CK --id rdr1 >/tmp/opencode/remote_smoke/kassafu.log 2>&1 & K_PID=$!
sleep 3
echo "=== GET /config (unconfigured -> later, after POST below) ==="
curl -s http://127.0.0.1:8888/config; echo
echo "=== POST /config (sumup) ==="
curl -s -X POST http://127.0.0.1:8888/config -H "Content-Type: application/json" \
  -d '{"client_url":"http://127.0.0.1:8199/config.rdr1","client_key":"CK","id":"rdr1"}'; echo
echo "=== health ==="
curl -s http://127.0.0.1:8888/health; echo
kill $BLOB_PID $K_PID 2>/dev/null
```

Expected: `GET /config` before POST prints the message; the SumUp POST returns `{"success":true,"terminal_type":"sumup"}`; health shows `"mode":"sumup"`. Then repeat the flow for a myPOS client blob (with a `partner` blob and `--partner-url`/`--partner-key`) and expect `terminal_type` mypos.

- [ ] **Step 4: Plan checkbox sweep**

Run `rg -n -- "- \[ \]" docs/superpowers/plans/2026-09-15-remote-blob-config.md` and mark every box `[x]` (e.g. `sed -i 's/^- \[ \]/- [x]/g'`), then:

```bash
git add docs/superpowers/plans/2026-09-15-remote-blob-config.md
git commit -m "docs: mark remote blob config plan complete"
```

---

## Self-review notes (for the plan author)

- **Spec coverage:** 5-field interface (T2/T3/T4), client-first resolution (T2 helpers), section-key detection (T2 `_validate_client_config`), myPOS-only partner fetch (T2), inject `id` (T2), strict validation (T2), no cache (T1 removes `fetch_partner`), GET /config message (T3), CLI flags (T4), docs (T6), verification (T7).
- **Type/name consistency:** `_fetch_blob_json(url, key, what)`, `_validate_client_config(cfg) -> str`, `_resolve_remote_config(interface) -> dict`, `KASSAFU_INTERFACE`, `PARTNER_URL_DEFAULT`, `PartnerConfigError` — used identically across all tasks.
- **Count check:** 94 baseline − 4 FetchPartnerTests − 6 MergePartnerTests + 11 RemoteResolveTests + ConfigEndpointTests 6→8 (+2) + version test (+1) = 98. Verify after Task 3.6.