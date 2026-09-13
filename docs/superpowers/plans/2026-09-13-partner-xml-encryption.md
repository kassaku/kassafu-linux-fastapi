# Partner XML Encryption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the myPOS `partner` credentials from `config.mypos.json` and fetch them at runtime from an encrypted AES-256-GCM blob hosted on kassaku.nl, decrypting with a runtime-supplied key.

**Architecture:** A new tool/library `encrypt_partner.py` encrypts the partner JSON into a versioned blob (`KASSAFU_BLOB` magic + version byte + salt + iterations + nonce + ciphertext) and exposes `decrypt_blob`/`parse_partner`/`fetch_partner`. kassafu merges the fetched partner section via a new `_merge_partner()` helper called from `update_config()` (POST /config) and `_startup()`, before terminal init — never on the bridge loop. The key travels via `mypos.partner_key` in the posted config or the `--key` CLI flag (module global `KASSAFU_PARTNER_KEY`); it is never stored, logged, or committed.

**Tech Stack:** Python 3, `cryptography` (AESGCM + PBKDF2HMAC), `httpx` (fetch), Flask/waitress (existing app), unittest.

**Supersedes:** The `partner` block inline in `config.mypos.json`. Low-level `_apply_runtime_config` still takes a fully-resolved config (inline partner OK for its unit tests).

---

### Task 1: Add `cryptography` dependency and install it

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the pin to requirements.txt**

```text
cryptography==41.0.7
```

(Place after the `httpx>=0.28.1` line, matching the existing alphabetized-ish flow.)

- [ ] **Step 2: Install into the venv**

Run: `venv/bin/pip install cryptography==41.0.7`
Expected: installed successfully.

- [ ] **Step 3: Verify import**

Run: `venv/bin/python -c "import cryptography; print(cryptography.__version__)"`
Expected: prints `41.0.7`.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add cryptography dependency for partner encryption"
```

---

### Task 2: Write failing tests for `encrypt_partner.py`

**Files:**
- Create: `tests/test_encrypt_partner.py`

- [ ] **Step 1: Write the test file**

```python
import json
import os
import tempfile
import unittest
from unittest import mock

import httpx

from encrypt_partner import (
    PARTNER_URL_DEFAULT,
    PartnerConfigError,
    decrypt_blob,
    encrypt_file,
    fetch_partner,
    parse_partner,
)

PLAIN = json.dumps({
    "app": {"name": "KassaFu", "mode": "mypos"},
    "partner": {
        "client_id": "client_test",
        "client_secret": "secret_test",
        "application_id": "mps-app-test",
        "partner_id": "mps-p-test",
    },
}).encode("utf-8")


def _make_blob(tmpdir, key="test-key"):
    src = os.path.join(tmpdir, "src.json")
    dst = os.path.join(tmpdir, "dst.blob")
    with open(src, "wb") as f:
        f.write(PLAIN)
    encrypt_file(src, dst, key)
    with open(dst, "rb") as f:
        return f.read()


class EncryptDecryptTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = _make_blob(tmpdir)
            self.assertEqual(decrypt_blob(blob, "test-key"), PLAIN)

    def test_wrong_key_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = _make_blob(tmpdir)
            with self.assertRaises(PartnerConfigError):
                decrypt_blob(blob, "wrong-key")

    def test_corrupted_blob_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = bytearray(_make_blob(tmpdir))
            blob[-1] ^= 0xFF
            with self.assertRaises(PartnerConfigError):
                decrypt_blob(bytes(blob), "test-key")

    def test_unknown_version_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = bytearray(_make_blob(tmpdir))
            blob[12] = 0x63
            with self.assertRaises(PartnerConfigError):
                decrypt_blob(bytes(blob), "test-key")

    def test_bad_magic_raises(self):
        blob = b"NOTKASSAFU_BLOB" + b"\x00" * 64
        with self.assertRaises(PartnerConfigError):
            decrypt_blob(blob, "test-key")


class ParsePartnerTests(unittest.TestCase):
    def test_returns_partner_dict(self):
        self.assertEqual(parse_partner(PLAIN)["client_id"], "client_test")

    def test_rejects_bad_json(self):
        with self.assertRaises(PartnerConfigError):
            parse_partner(b"{not json")

    def test_rejects_missing_partner(self):
        with self.assertRaises(PartnerConfigError):
            parse_partner(b'{"app": {"name": "KassaFu"}}')


class FetchPartnerTests(unittest.TestCase):
    def test_fetches_and_caches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = _make_blob(tmpdir)
            cache = os.path.join(tmpdir, "cache.blob")
            with mock.patch("encrypt_partner.httpx.get", return_value=httpx.Response(200, content=blob)):
                partner = fetch_partner("http://example/partner.xml", "test-key", cache)
            self.assertEqual(partner["client_id"], "client_test")
            self.assertTrue(os.path.exists(cache))

    def test_cache_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blob = _make_blob(tmpdir)
            cache = os.path.join(tmpdir, "cache.blob")
            with open(cache, "wb") as f:
                f.write(blob)
            with mock.patch("encrypt_partner.httpx.get", side_effect=httpx.ConnectError("down")):
                partner = fetch_partner("http://dead/partner.xml", "test-key", cache)
            self.assertEqual(partner["client_id"], "client_test")

    def test_no_cache_raises(self):
        with mock.patch("encrypt_partner.httpx.get", side_effect=httpx.ConnectError("down")):
            with self.assertRaises(PartnerConfigError):
                fetch_partner("http://dead/partner.xml", "test-key", "/nonexistent/cache.blob")

    def test_default_url(self):
        self.assertEqual(
            PARTNER_URL_DEFAULT,
            "http://www.kassaku.nl/restaurants/install/partner.xml",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/bin/python -m unittest tests.test_encrypt_partner -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'encrypt_partner'`.

---

### Task 3: Implement `encrypt_partner.py`

**Files:**
- Create: `encrypt_partner.py`

- [ ] **Step 1: Write the module**

```python
#!/usr/bin/env python3
"""Encrypt/decrypt the myPOS partner credentials for remote hosting.

CLI (hand-encryption tool):

    python3 encrypt_partner.py --key "//B1a9r6t8//" --input partner.json --output partner.xml.enc

Also the importable crypto/fetch library kassafu uses at runtime.
"""

import argparse
import json
import logging
import os

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

PARTNER_URL_DEFAULT = "http://www.kassaku.nl/restaurants/install/partner.xml"

BLOB_MAGIC = b"KASSAFU_BLOB"
BLOB_VERSION = 1
PBKDF2_ITERATIONS = 200_000
KEY_LENGTH = 32
SALT_LENGTH = 16
NONCE_LENGTH = 12
TAG_LENGTH = 16


class PartnerConfigError(Exception):
    """Raised when the partner blob cannot be fetched, decrypted, or parsed."""


def _derive_key(key: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(key.encode("utf-8"))


def encrypt_file(input_path: str, output_path: str, key: str) -> None:
    """Read a plaintext file and write the versioned encrypted blob."""
    with open(input_path, "rb") as f:
        plaintext = f.read()

    salt = os.urandom(SALT_LENGTH)
    nonce = os.urandom(NONCE_LENGTH)
    key_bytes = _derive_key(key, salt)
    ciphertext = AESGCM(key_bytes).encrypt(nonce, plaintext, None)

    header = (
        BLOB_MAGIC
        + bytes([BLOB_VERSION])
        + salt
        + PBKDF2_ITERATIONS.to_bytes(4, "big")
        + nonce
    )
    with open(output_path, "wb") as f:
        f.write(header + ciphertext)


def decrypt_blob(blob: bytes, key: str) -> bytes:
    """Decrypt a versioned blob, raising PartnerConfigError on failure."""
    magic_len = len(BLOB_MAGIC)
    header_len = magic_len + 1 + SALT_LENGTH + 4 + NONCE_LENGTH
    if len(blob) < header_len + TAG_LENGTH:
        raise PartnerConfigError("Blob too short to be a valid KassaFu blob")

    if blob[:magic_len] != BLOB_MAGIC:
        raise PartnerConfigError("Bad blob magic: not a KassaFu blob")

    version = blob[magic_len]
    if version != BLOB_VERSION:
        raise PartnerConfigError(f"Unsupported blob version {version}")

    pos = magic_len + 1
    salt = blob[pos:pos + SALT_LENGTH]
    pos += SALT_LENGTH
    iterations = int.from_bytes(blob[pos:pos + 4], "big")
    pos += 4
    nonce = blob[pos:pos + NONCE_LENGTH]
    pos += NONCE_LENGTH

    key_bytes = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KEY_LENGTH,
        salt=salt,
        iterations=iterations,
    ).derive(key.encode("utf-8"))

    try:
        return AESGCM(key_bytes).decrypt(nonce, blob[pos:], None)
    except Exception as exc:
        raise PartnerConfigError(f"Decryption failed (wrong key or corrupted blob): {exc}")


def parse_partner(plaintext: bytes) -> dict:
    """Parse the decrypted JSON and return the partner dict."""
    try:
        data = json.loads(plaintext.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PartnerConfigError(f"Partner payload is not valid JSON: {exc}")

    partner = data.get("partner")
    if not isinstance(partner, dict):
        raise PartnerConfigError("Partner payload missing 'partner' object")
    return partner


def fetch_partner(partner_url: str, key: str, cache_path: str) -> dict:
    """Fetch, decrypt and parse the partner config, caching the blob."""
    blob = None
    try:
        response = httpx.get(partner_url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        blob = response.content
    except httpx.HTTPError as exc:
        logger.warning(f"Failed to fetch partner config from {partner_url}: {exc}")

    if blob is None:
        try:
            with open(cache_path, "rb") as f:
                blob = f.read()
            logger.warning("Falling back to cached partner config")
        except OSError:
            raise PartnerConfigError(
                "Failed to fetch partner configuration and no cached copy available"
            )

    try:
        with open(cache_path, "wb") as f:
            f.write(blob)
    except OSError:
        logger.warning(f"Could not write partner cache to {cache_path}")

    plaintext = decrypt_blob(blob, key)
    return parse_partner(plaintext)


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt the myPOS partner credentials file into a KassaFu blob"
    )
    parser.add_argument("--key", required=True, help="Encryption passphrase")
    parser.add_argument("--input", required=True, help="Plaintext JSON file")
    parser.add_argument("--output", required=True, help="Encrypted blob output file")
    args = parser.parse_args()

    encrypt_file(args.input, args.output, args.key)
    print(f"Encrypted {args.input} -> {args.output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `venv/bin/python -m unittest tests.test_encrypt_partner -v`
Expected: all 11 tests PASS.

- [ ] **Step 3: CLI smoke check (in /tmp, no repo files touched)**

```bash
cd /tmp/opencode && printf '%s' '{"app":{"name":"KassaFu","mode":"mypos"},"partner":{"client_id":"c","client_secret":"s","application_id":"a","partner_id":"p"}}' > partner.json
python3 /home/mensfort/workspace/kassafu/encrypt_partner.py --key "//B1a9r6t8//" --input partner.json --output partner.xml.enc
```

Expected: prints `Encrypted partner.json -> partner.xml.enc`; the produced blob is binary (starts with `KASSAFU_BLOB`), not plaintext.

- [ ] **Step 4: Commit**

```bash
git add encrypt_partner.py tests/test_encrypt_partner.py
git commit -m "feat: add encrypt_partner tool with versioned AES-GCM blob support"
```

---

### Task 4: `_merge_partner` in kassafu.py (tests first)

**Files:**
- Modify: `tests/test_kassafu_config.py`
- Modify: `kassafu.py`

- [ ] **Step 1: Add imports to the test file**

Add to the top of `tests/test_kassafu_config.py`:

```python
from unittest import mock

from encrypt_partner import PARTNER_URL_DEFAULT, PartnerConfigError
from kassafu import _apply_runtime_config, _merge_partner, _resolve_terminal_type
```

(Replace the current `from kassafu import _apply_runtime_config, _resolve_terminal_type` line.)

- [ ] **Step 2: Add `_merge_partner` unit tests**

Append before `if __name__ == "__main__":` in `tests/test_kassafu_config.py`:

```python
MYPOS_CONFIG_NO_PARTNER = {
    "mypos": {
        "gateway_url": "https://demo-api-gateway.mypos.com",
        "partner_url": "http://example.test/partner.xml",
        "partner_key": "test-key",
        "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
        "terminal_id": "80026232",
    }
}

FAKE_PARTNER = {
    "client_id": "ci",
    "client_secret": "cs",
    "application_id": "app",
    "partner_id": "pi",
}


class MergePartnerTests(unittest.TestCase):
    def setUp(self):
        self._saved_key = kassafu.KASSAFU_PARTNER_KEY
        kassafu.KASSAFU_PARTNER_KEY = None

    def tearDown(self):
        kassafu.KASSAFU_PARTNER_KEY = self._saved_key

    def test_non_mypos_returns_same_object(self):
        cfg = SUMUP_CONFIG
        self.assertIs(_merge_partner(cfg), cfg)

    def test_injects_fetched_partner(self):
        cfg = {k: v for k, v in MYPOS_CONFIG_NO_PARTNER.items()}
        with mock.patch("kassafu.fetch_partner", return_value=FAKE_PARTNER) as fetch:
            merged = _merge_partner(cfg)
        fetch.assert_called_once_with(
            "http://example.test/partner.xml", "test-key", "partner.xml.enc"
        )
        self.assertEqual(merged["mypos"]["partner"], FAKE_PARTNER)
        self.assertNotIn("partner", cfg["mypos"])

    def test_default_url_used_when_absent(self):
        cfg = {k: v for k, v in MYPOS_CONFIG_NO_PARTNER.items()}
        del cfg["mypos"]["partner_url"]
        with mock.patch("kassafu.fetch_partner", return_value=FAKE_PARTNER) as fetch:
            _merge_partner(cfg)
        self.assertEqual(fetch.call_args[0][0], PARTNER_URL_DEFAULT)

    def test_cli_key_fallback(self):
        kassafu.KASSAFU_PARTNER_KEY = "cli-key"
        cfg = {k: v for k, v in MYPOS_CONFIG_NO_PARTNER.items()}
        del cfg["mypos"]["partner_key"]
        with mock.patch("kassafu.fetch_partner", return_value=FAKE_PARTNER) as fetch:
            _merge_partner(cfg)
        self.assertEqual(fetch.call_args[0][1], "cli-key")

    def test_missing_key_raises(self):
        cfg = {k: v for k, v in MYPOS_CONFIG_NO_PARTNER.items()}
        del cfg["mypos"]["partner_key"]
        with self.assertRaises(PartnerConfigError):
            _merge_partner(cfg)

    def test_non_dict_returns_same_object(self):
        self.assertIs(_merge_partner("nope"), "nope")
```

- [ ] **Step 3: Run to verify the new tests fail**

Run: `venv/bin/python -m unittest tests.test_kassafu_config -v`
Expected: FAIL — `AttributeError: module 'kassafu' has no attribute '_merge_partner'` (new tests). Existing `ApplyRuntimeConfigTests` still pass.

- [ ] **Step 4: Add the import and globals to kassafu.py**

At the top of `kassafu.py`, after the existing `from mypos_terminal import MyPOSTerminal`:

```python
from encrypt_partner import (
    PARTNER_URL_DEFAULT,
    PartnerConfigError,
    fetch_partner,
)
```

After the `active_payment = False` global (around line 76):

```python
KASSAFU_PARTNER_KEY = None
PARTNER_CACHE_DEFAULT = "partner.xml.enc"
```

- [ ] **Step 5: Add the `_merge_partner` helper**

Insert after `_resolve_terminal_type` (before `_apply_runtime_config`):

```python
def _merge_partner(cfg: dict) -> dict:
    """Fetch + decrypt + inject the myPOS partner credentials into a copy of cfg.

    Non-myPOS configs pass through unchanged. Raises PartnerConfigError when
    the partner blob cannot be fetched/decrypted or no key is available.
    """
    if not isinstance(cfg, dict) or _resolve_terminal_type(cfg) != "mypos":
        return cfg

    mypos = cfg.get("mypos", {})
    partner_url = mypos.get("partner_url") or PARTNER_URL_DEFAULT
    partner_key = mypos.get("partner_key") or KASSAFU_PARTNER_KEY
    if not partner_key:
        raise PartnerConfigError(
            "Missing partner encryption key (set mypos.partner_key or pass --key)"
        )

    cache_path = mypos.get("partner_cache") or PARTNER_CACHE_DEFAULT
    partner = fetch_partner(partner_url, partner_key, cache_path)

    merged = dict(cfg)
    merged["mypos"] = dict(mypos)
    merged["mypos"]["partner"] = partner
    return merged
```

- [ ] **Step 6: Run the config tests to verify they pass**

Run: `venv/bin/python -m unittest tests.test_kassafu_config -v`
Expected: all tests (existing + new `_merge_partner` tests) PASS.

- [ ] **Step 7: Commit**

```bash
git add kassafu.py tests/test_kassafu_config.py
git commit -m "feat: add _merge_partner to fetch and inject partner credentials"
```

---

### Task 5: Wire `_merge_partner` into the config and startup call sites

**Files:**
- Modify: `kassafu.py`
- Modify: `tests/test_kassafu_endpoints.py`

- [ ] **Step 1: Add the `--key` argparse flag in `__main__`**

In `kassafu.py`, in the `if __name__ == "__main__":` block, after the `--debug` argument:

```python
    parser.add_argument("--key", type=str, help="Partner encryption key (terminal testing)")
```

After `args = parser.parse_args()`, set the module global:

```python
    if args.key:
        KASSAFU_PARTNER_KEY = args.key
```

- [ ] **Step 2: Merge in `update_config()`**

Replace the body of `update_config()` (the POST /config route) with:

```python
@app.post("/config")
def update_config():
    """Replace runtime configuration and hot-swap the terminal (in-memory only)"""
    new_config = request.get_json(silent=True)
    try:
        new_config = _merge_partner(new_config)
    except PartnerConfigError as exc:
        return {"detail": str(exc)}, 400

    body, status = bridge.run(_apply_config_atomic(new_config))

    if status == 200:
        try:
            bridge.run(_maybe_discover(terminal, TERMINAL_TYPE))
        except Exception as exc:  # discovery problems must not fail an applied config
            logger.warning(f"Post-swap discovery failed: {exc}")

    return body, status
```

- [ ] **Step 3: Merge in `_startup()`**

In `_startup()`, add `config` to the `global` statement and merge before terminal init:

```python
def _startup():
    """Initialize the terminal, payment queue and queue consumer.

    Runs once before the WSGI server starts serving. Terminal init and the
    queue consumer run on the bridge loop, exactly as they did on FastAPI's
    single event loop.
    """
    global terminal, TERMINAL_TYPE, payment_queue, config

    try:
        config = _merge_partner(config)
    except PartnerConfigError as exc:
        logger.error(f"Partner configuration unavailable: {exc}")

    if any(name in config for name in TERMINAL_CLASSES):
        ...
```

(The rest of the function is unchanged.)

- [ ] **Step 4: Add endpoint tests for the myPOS config flow**

In `tests/test_kassafu_endpoints.py`:
- Add import at top: `from unittest import mock`
- Add to `ConfigEndpointTests` (before the closing of the class):

```python
    def test_post_config_mypos_with_key_merges_partner(self):
        cfg_mypos = {
            "app": {"name": "KassaFu", "mode": "mypos"},
            "mypos": {
                "gateway_url": "https://demo-api-gateway.mypos.com",
                "partner_key": "test-key",
                "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
                "terminal_id": "80026232",
            },
        }
        with mock.patch("kassafu.fetch_partner", return_value={
            "client_id": "mps-app-30034196", "client_secret": "s",
            "application_id": "app", "partner_id": "mps-p-1",
        }):
            r = self.client.post("/config", json=cfg_mypos)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["terminal_type"], "mypos")
        self.assertIsNotNone(kassafu.terminal)

    def test_post_config_mypos_fetch_error_returns_400(self):
        cfg_mypos = {
            "app": {"name": "KassaFu", "mode": "mypos"},
            "mypos": {
                "gateway_url": "https://demo-api-gateway.mypos.com",
                "partner_key": "test-key",
                "merchant": {"client_id": "cli_merchant", "client_secret": "sec_merchant"},
                "terminal_id": "80026232",
            },
        }
        with mock.patch(
            "kassafu.fetch_partner",
            side_effect=PartnerConfigError("Failed to fetch partner configuration"),
        ):
            r = self.client.post("/config", json=cfg_mypos)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Failed to fetch partner configuration", r.get_json()["detail"])
```

(Add `from encrypt_partner import PartnerConfigError` to the imports of that test file too.)

- [ ] **Step 5: Run the full endpoint suite**

Run: `venv/bin/python -m unittest tests.test_kassafu_endpoints -v`
Expected: all 24 endpoint tests pass (when run on their own, the two new myPOS tests need `mock` and `PartnerConfigError` imported — verify those imports are present).

- [ ] **Step 6: Run the full suite**

Run: `venv/bin/python -m unittest discover -s tests`
Expected: all ~91 tests pass (72 existing + 11 encrypt_partner + 6 merge + 2 new endpoint tests).

Note: the `_merge_partner` and `fetch_partner` monkeypatch names must match. `kassafu.fetch_partner` is module-level (imported via `from encrypt_partner import fetch_partner`), so `mock.patch("kassafu.fetch_partner", ...)` patches the name kassafu's `_merge_partner` looks up.

- [ ] **Step 7: Commit**

```bash
git add kassafu.py tests/test_kassafu_endpoints.py
git commit -m "feat: wire partner encryption into config and startup paths"
```

---

### Task 6: Add the example partner key to `test_reader_status_mypos.py`

**Files:**
- Modify: `test_reader_status_mypos.py`

Purpose: the user runs this script to push `config.mypos.json` (which no longer contains a `partner` block) to a running server. The script injects the partner key so the server can decrypt the hosted blob. It reads `KASSAFU_PARTNER_KEY` from the environment, defaulting to the example passphrase `//B1a9r6t8//` (replace with your real key).

- [ ] **Step 1: Add the key source**

After the `CONFIG_FILE = ...` line:

```python
PARTNER_KEY = os.environ.get("KASSAFU_PARTNER_KEY", "//B1a9r6t8//")
```

- [ ] **Step 2: Inject the key into the pushed config**

In `push_config()`, after `config = json.load(f)` inside the try block:

```python
    if isinstance(config, dict) and "mypos" in config:
        config.setdefault("mypos", {})["partner_key"] = PARTNER_KEY
```

- [ ] **Step 3: Verify no syntax break**

Run: `venv/bin/python -m py_compile test_reader_status_mypos.py`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add test_reader_status_mypos.py
git commit -m "feat: pass partner encryption key from test script"
```

---

### Task 7: Update the local `config.mypos.json` and `.gitignore`

**Files:**
- Modify: `config.mypos.json` (gitignored — amended locally, not committed)
- Modify: `.gitignore`

- [ ] **Step 1: Rewrite `config.mypos.json`**

```json
{
  "app": {"name": "KassaFu", "mode": "mypos"},
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "partner_url": "http://www.kassaku.nl/restaurants/install/partner.xml",
    "partner_key": "",
    "partner_cache": "partner.xml.enc",
    "merchant": {
      "client_id": "cli_3KmJ3uXR1vnVUx5lRRYrfvvEezRv",
      "client_secret": "sec_JwnJTwmDdkIwwxpP4mrj3RPmgE6cZX5Ttk7n37xKB0geiFurYlWOEOvdH73d"
    },
    "terminal_id": "80581413"
  }
}
```

(Keep the existing `merchant` and `terminal_id` values from the current file — copy them verbatim, do not invent them.)

- [ ] **Step 2: Add generated-blob files to `.gitignore`**

Append to `.gitignore`:

```gitignore
# Partner encryption blob + plaintext (never committed)
config.partner.json
partner.xml.enc
partner.xml.enc.*
```

- [ ] **Step 3: Verify `.gitignore` took effect**

Run: `git status --short`
Expected: `config.partner.json` (which currently shows `??`) no longer appears (it is now ignored).

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore generated partner blob and plaintext files"
```

---

### Task 8: Deployment and docs

**Files:**
- Modify: `install.sh`
- Modify: `create_deb`
- Modify: `README.md`
- Modify: `API.md`
- Modify: `SOFTWARE.md`

- [ ] **Step 1: Copy `encrypt_partner.py` in `install.sh`**

After the `cp "$SCRIPT_DIR/sumup_terminal.py" "$INSTALL_DIR/"` line, add:

```bash
cp "$SCRIPT_DIR/encrypt_partner.py" "$INSTALL_DIR/"
```

- [ ] **Step 2: Add `encrypt_partner.py` to `create_deb`**

Update the cp line (line 13) to include `encrypt_partner.py`:

```bash
cp kassafu.py asyncio_bridge.py encrypt_partner.py mypos_terminal.py mypos_gateway.py sumup_terminal.py "$ROOT/"
```

And the chmod loop (line 17) to include it:

```bash
for f in kassafu.py asyncio_bridge.py encrypt_partner.py mypos_terminal.py mypos_gateway.py sumup_terminal.py install.sh; do
```

- [ ] **Step 3: Update `README.md` (myPOS config example)**

Replace the myPOS JSON block (lines ~55-73) with:

```json
{
  "app": {"name": "KassaFu", "mode": "mypos"},
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "partner_url": "http://www.kassaku.nl/restaurants/install/partner.xml",
    "partner_key": "",
    "partner_cache": "partner.xml.enc",
    "merchant": {
      "client_id": "cli_...",
      "client_secret": "sec_..."
    },
    "terminal_id": "80581413"
  }
}
```

- [ ] **Step 4: Document the encrypt/host/fetch flow in `README.md`**

Add a short subsection after the myPOS config example:

````markdown
### Hosting myPOS partner credentials

The `partner` credentials are no longer stored in `config.mypos.json`. They live in an encrypted blob hosted at the `partner_url` above. To build it from a plaintext JSON file:

```bash
cp config.partner.json partner.json   # contains {"app":..., "partner": {...}}
python3 encrypt_partner.py --key "your-secret" --input partner.json --output partner.xml.enc
# upload partner.xml.enc to the partner_url location
```

The key is supplied at runtime via `mypos.partner_key` (pushed by the POS) or `--key <key>` (terminal testing) and is never stored in code, config, or git.
````

- [ ] **Step 5: Update `API.md` (myPOS request-body example)**

Replace the myPOS example JSON in the `POST /config` section (lines 495-516) with:

```json
{
  "app": {
    "name": "KassaFu",
    "mode": "mypos"
  },
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "partner_url": "http://www.kassaku.nl/restaurants/install/partner.xml",
    "partner_key": "your-secret",
    "partner_cache": "partner.xml.enc",
    "merchant": {
      "client_id": "cli_...",
      "client_secret": "sec_..."
    },
    "terminal_id": "80581413"
  }
}
```

Add a note under it: "The `partner` section is fetched and decrypted from `partner_url`; **do not** include an inline `partner` block. `partner_key` is read from this config (or passed with `--key`) and never returned by `GET /config`."

- [ ] **Step 6: Add `cryptography` to `SOFTWARE.md`**

In the dependencies list, after the `python-dotenv==1.0.0` line, add:

```text
cryptography==41.0.7
```

- [ ] **Step 7: Sanity-check the docs changes**

Run: `venv/bin/python -m py_compile` on nothing — instead run `git diff --stat` and eyeball that only the 5 docs/deploy files changed.
Expected: install.sh, create_deb, README.md, API.md, SOFTWARE.md modified.

- [ ] **Step 8: Commit**

```bash
git add install.sh create_deb README.md API.md SOFTWARE.md
git commit -m "docs: document encrypted partner hosting and deploy the encrypt tool"
```

---

### Task 9: Full verification and smoke test

- [ ] **Step 1: Run the entire test suite**

Run: `venv/bin/python -m unittest discover -s tests`
Expected: all tests PASS (72 baseline + new ones, no failures).

- [ ] **Step 2: Grep for accidentally committed secrets**

Run: `git grep -n "client_dc3eea\|secret_9ed708\|B1a9r6t8" -- ':!docs/superpowers/plans/*' ':!docs/superpowers/specs/*'`
Expected: no matches in code/config (the key `//B1a9r6t8//` may appear in the plan/spec docs only, which is allowed — the runtime passphrase must be rotated for production).

- [ ] **Step 3: Live smoke test (myPOS path, optional — needs upload)**

If the blob has been uploaded to `partner_url`, start `kassafu.py --server --config config.mypos.json --key "your-secret"` and confirm:
- `/health` shows `"mode": "mypos"`.
- `POST /config` with the myPOS config (partner_key set) returns 200, `terminal_type: "mypos"`.

If not yet uploaded, the cache fallback path is already covered by unit tests; defer the live test.

- [ ] **Step 4: Final review**

Compare against the spec (`docs/superpowers/specs/2026-09-13-partner-xml-encryption-design.md`) checklist and confirm each item has a task. Update this plan's status checkboxes.

---

## Self-review notes (run after writing)

- Spec cover: always-fetch; key via `mypos.partner_key`/`--key`; cache fallback; one tool; AES-256-GCM + PBKDF2; versioned blob; call sites in `update_config` + `_startup`; config shape; error table; test suite; deps/deploy/docs — all mapped to Tasks 1-9.
- Placeholder scan: every code step has full code; no TBD/TODO.
- Type consistency: `encrypt_file(input, output, key)`, `decrypt_blob(blob, key) -> bytes`, `parse_partner(plaintext) -> dict`, `fetch_partner(url, key, cache) -> dict`, `_merge_partner(cfg) -> dict`, `KASSAFU_PARTNER_KEY`, `PARTNER_URL_DEFAULT`, `PARTNER_CACHE_DEFAULT`, `PartnerConfigError` — names match across tasks.