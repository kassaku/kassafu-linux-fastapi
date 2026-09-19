# Config Blob Creation Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three small scripts (`create_partner.py`, `create_mypos.py`, `create_sumup.py`) that prompt for credentials, an encryption key, and an output filename, then write a plaintext JSON file and encrypt it into the KassaFu blob that is hosted on the server.

**Architecture:** One shared helper module `create_config.py` owns the prompt-and-encrypt flow (`build_and_encrypt`) and is reused by three thin wrapper scripts, each supplying its credential questions, JSON template, and suggested output name. Encryption reuses `encrypt_file` from the existing `encrypt_partner.py` — no new crypto code. Tests are `unittest` in `tests/`, consistent with `tests/test_encrypt_partner.py`.

**Tech Stack:** Python 3.12 stdlib (`getpass`, `json`), `cryptography` (via `encrypt_partner`), `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-19-create-config-scripts-design.md`

---

### Task 1: Shared helper `create_config.py`

**Files:**
- Create: `tests/test_create_config.py` (first part)
- Create: `create_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_create_config.py`:

```python
import json
import os
import tempfile
import unittest
from unittest import mock

from create_config import _ask, build_and_encrypt
from encrypt_partner import decrypt_blob


def _prompt(seq):
    """Return two side-effect mocks that drain answers from a shared iterable.

    Secrets go through getpass.getpass, non-secrets through builtins.input;
    both pull the next value from the same seq so alternating calls work.
    """
    patch_getpass = mock.patch(
        "getpass.getpass", side_effect=lambda *a: next(seq)
    )
    patch_input = mock.patch("builtins.input", side_effect=lambda *a: next(seq))
    return patch_getpass, patch_input


class AskTests(unittest.TestCase):
    def test_returns_typed_value(self):
        with mock.patch("builtins.input", return_value="typed"):
            self.assertEqual(_ask("x: "), "typed")

    def test_uses_default_on_empty(self):
        with mock.patch("builtins.input", return_value=""):
            self.assertEqual(_ask("x: ", default="dflt"), "dflt")

    def test_truthy_typed_value_wins_over_default(self):
        with mock.patch("builtins.input", return_value="typed"):
            self.assertEqual(_ask("x: ", default="dflt"), "typed")

    def test_required_nonempty_reprompts(self):
        seq = iter(["", "value"])
        with _prompt(seq):
            self.assertEqual(_ask("x: "), "value")

    def test_whitespace_treated_as_empty(self):
        with mock.patch("builtins.input", return_value="  "):
            self.assertEqual(_ask("x: ", default="dflt"), "dflt")


class BuildAndEncryptTests(unittest.TestCase):
    def test_writes_plaintext_json_and_encrypted_blob(self):
        seq = iter([
            "client_id_v", "client_secret_v", "app_v", "partner_v",
            "key_v", "config.test",
        ])
        with _prompt(seq):
            with tempfile.TemporaryDirectory() as tmpdir:
                cwd = os.getcwd()
                os.chdir(tmpdir)
                try:
                    build_and_encrypt(
                        questions=[
                            ("client_id", False, None),
                            ("client_secret", True, None),
                            ("application_id", False, None),
                            ("partner_id", False, None),
                        ],
                        build_json=lambda a: {
                            "app": {"name": "KassaFu"},
                            "partner": {
                                "client_id": a["client_id"],
                                "client_secret": a["client_secret"],
                                "application_id": a["application_id"],
                                "partner_id": a["partner_id"],
                            },
                        },
                        default_out="config.x",
                        help_out="test",
                    )
                finally:
                    os.chdir(cwd)

        with open(os.path.join(tmpdir, "config.test.json"), encoding="utf-8") as f:
            plain = json.load(f)
        self.assertEqual(plain["partner"], {
            "client_id": "client_id_v",
            "client_secret": "client_secret_v",
            "application_id": "app_v",
            "partner_id": "partner_v",
        })

        with open(os.path.join(tmpdir, "config.test"), "rb") as f:
            blob = f.read()
        decrypted = json.loads(decrypt_blob(blob, "key_v").decode("utf-8"))
        self.assertEqual(decrypted["partner"]["client_id"], "client_id_v")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m unittest tests.test_create_config -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'create_config'`.

- [ ] **Step 3: Write minimal implementation**

Create `create_config.py`:

```python
#!/usr/bin/env python3
"""Shared prompt-and-encrypt helper for the create_*.py config builders."""

import getpass
import json

from encrypt_partner import encrypt_file


def _ask(prompt, secret=False, default=None):
    """Prompt once; reprompt on empty input unless a default is available."""
    while True:
        if secret:
            value = getpass.getpass(prompt)
        else:
            value = input(prompt)
        value = value.strip()
        if value:
            return value
        if default is not None:
            return default


def build_and_encrypt(questions, build_json, default_out, help_out):
    """Ask credential questions, then an encryption key and output filename.

    Writes the plaintext JSON to <out>.json and encrypts it to <out> using
    encrypt_partner.encrypt_file. questions is a list of
    (label, secret_bool, default_or_None); build_json maps the answers dict
    to the JSON payload.
    """
    print(help_out)
    answers = {}
    for label, secret, default in questions:
        prompt = label
        if default:
            prompt += f" [{default}]"
        answers[label] = _ask(prompt + ": ", secret=secret, default=default)

    key = _ask("Encryption key: ", secret=True)
    out = _ask(f"Output blob filename [{default_out}]: ", default=default_out)

    plain_path = out + ".json"
    with open(plain_path, "w", encoding="utf-8") as f:
        json.dump(build_json(answers), f, indent=2)
        f.write("\n")
    encrypt_file(plain_path, out, key)
    print(f"Wrote {plain_path} and encrypted blob {out}.")


if __name__ == "__main__":
    print("Shared helper for create_partner.py, create_mypos.py, create_sumup.py.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m unittest tests.test_create_config -v`

Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add create_config.py tests/test_create_config.py
git commit -m "feat: shared prompt-and-encrypt helper for config creation"
```

---

### Task 2: `create_partner.py`

**Files:**
- Modify: `tests/test_create_config.py` (add template tests)
- Create: `create_partner.py`

- [ ] **Step 1: Add the failing template test**

Append to `tests/test_create_config.py` (before the `if __name__` block):

```python
from create_partner import _build as build_partner


class PartnerTemplateTests(unittest.TestCase):
    def test_partner_template(self):
        payload = build_partner({
            "client_id": "c",
            "client_secret": "s",
            "application_id": "a",
            "partner_id": "p",
        })
        self.assertEqual(payload, {
            "app": {"name": "KassaFu"},
            "partner": {
                "client_id": "c",
                "client_secret": "s",
                "application_id": "a",
                "partner_id": "p",
            },
        })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m unittest tests.test_create_config.PartnerTemplateTests -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'create_partner'`.

- [ ] **Step 3: Write minimal implementation**

Create `create_partner.py`:

```python
#!/usr/bin/env python3
"""Create and encrypt the myPOS partner credentials blob (config.partner)."""

from create_config import build_and_encrypt


def _build(answers):
    return {
        "app": {"name": "KassaFu"},
        "partner": {
            "client_id": answers["client_id"],
            "client_secret": answers["client_secret"],
            "application_id": answers["application_id"],
            "partner_id": answers["partner_id"],
        },
    }


def main():
    build_and_encrypt(
        questions=[
            ("provider client_id", False, None),
            ("provider client_secret", True, None),
            ("application_id", False, None),
            ("partner_id", False, None),
        ],
        build_json=_build,
        default_out="config.partner",
        help_out="Create and encrypt the myPOS partner credentials blob.",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m unittest tests.test_create_config -v`

Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add create_partner.py tests/test_create_config.py
git commit -m "feat: create_partner.py builds the myPOS partner credential blob"
```

---

### Task 3: `create_mypos.py`

**Files:**
- Modify: `tests/test_create_config.py` (add template tests)
- Create: `create_mypos.py`

- [ ] **Step 1: Add the failing template test**

Append to `tests/test_create_config.py` (before the `if __name__` block):

```python
from create_mypos import _build as build_mypos


class MyposTemplateTests(unittest.TestCase):
    def test_mypos_template(self):
        payload = build_mypos({
            "gateway_url": "https://api-gateway.mypos.com",
            "client_id": "c",
            "client_secret": "s",
        })
        self.assertEqual(payload, {
            "app": {"name": "KassaFu"},
            "mypos": {
                "gateway_url": "https://api-gateway.mypos.com",
                "merchant": {"client_id": "c", "client_secret": "s"},
            },
        })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m unittest tests.test_create_config.MyposTemplateTests -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'create_mypos'`.

- [ ] **Step 3: Write minimal implementation**

Create `create_mypos.py`:

```python
#!/usr/bin/env python3
"""Create and encrypt a myPOS merchant credentials blob (config.<terminal_id>)."""

from create_config import build_and_encrypt


def _build(answers):
    return {
        "app": {"name": "KassaFu"},
        "mypos": {
            "gateway_url": answers["gateway_url"],
            "merchant": {
                "client_id": answers["client_id"],
                "client_secret": answers["client_secret"],
            },
        },
    }


def main():
    build_and_encrypt(
        questions=[
            ("gateway_url", False, "https://api-gateway.mypos.com"),
            ("merchant client_id", False, None),
            ("merchant client_secret", True, None),
        ],
        build_json=_build,
        default_out="config.80581413",
        help_out="Create and encrypt a myPOS merchant credentials blob.",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m unittest tests.test_create_config -v`

Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add create_mypos.py tests/test_create_config.py
git commit -m "feat: create_mypos.py builds a myPOS merchant credential blob"
```

---

### Task 4: `create_sumup.py`

**Files:**
- Modify: `tests/test_create_config.py` (add template tests)
- Create: `create_sumup.py`

- [ ] **Step 1: Add the failing template test**

Append to `tests/test_create_config.py` (before the `if __name__` block):

```python
from create_sumup import _build as build_sumup


class SumupTemplateTests(unittest.TestCase):
    def test_sumup_template(self):
        payload = build_sumup({"api_key": "k", "merchant_code": "m"})
        self.assertEqual(payload, {
            "app": {"name": "KassaFu"},
            "sumup": {"api_key": "k", "merchant_code": "m"},
        })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m unittest tests.test_create_config.SumupTemplateTests -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'create_sumup'`.

- [ ] **Step 3: Write minimal implementation**

Create `create_sumup.py`:

```python
#!/usr/bin/env python3
"""Create and encrypt a SumUp merchant credentials blob (config.<reader_id>)."""

from create_config import build_and_encrypt


def _build(answers):
    return {
        "app": {"name": "KassaFu"},
        "sumup": {
            "api_key": answers["api_key"],
            "merchant_code": answers["merchant_code"],
        },
    }


def main():
    build_and_encrypt(
        questions=[
            ("api_key", True, None),
            ("merchant_code", False, None),
        ],
        build_json=_build,
        default_out="config.rdr_6P0860A4S186MV3FHM2Q185AD7",
        help_out="Create and encrypt a SumUp merchant credentials blob.",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m unittest tests.test_create_config -v`

Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add create_sumup.py tests/test_create_config.py
git commit -m "feat: create_sumup.py builds a SumUp merchant credential blob"
```

---

### Task 5: Ignore produced blobs, document scripts, full suite

**Files:**
- Modify: `.gitignore:228-231`
- Modify: `README.md:66-81`

- [ ] **Step 1: Add blob outputs and produced files to `.gitignore`**

Edit the "Partner encryption blob + plaintext" block (`.gitignore` lines 228-231) so it reads:

```
# Partner encryption blob + plaintext (never committed)
config.partner.json
config.*.json
config.*.plain
config.partner
config.*.enc
partner.xml.enc
partner.xml.enc.*
```

Explanation: `config.partner` and any `*.enc` blobs are freshly produced by the new `create_*.py` scripts and must never be committed. (`config.partner.json` stays covered by `config.*.json` but the explicit line is kept.)

- [ ] **Step 2: Document the scripts in README.md**

In the "Hosting myPOS partner credentials" section of `README.md` (after the existing `encrypt_partner.py` example, lines 75-79), add:

```markdown
New-blob setup is interactive: the `create_*.py` scripts prompt for the
credentials, an encryption key, and the output filename, write the plaintext
`<name>.json`, and encrypt it to `<name>` in one go:

```bash
python3 create_partner.py     # myPOS provider credentials  -> config.partner
python3 create_mypos.py       # myPOS merchant credentials  -> config.<terminal_id>
python3 create_sumup.py       # SumUp merchant credentials  -> config.<reader_id>
```
```

- [ ] **Step 3: Run the full test suite**

Run: `venv/bin/python -m unittest discover -s tests -p 'test_*.py'`

Expected: `OK` (98 existing tests + 9 new = 107).

- [ ] **Step 4: Commit**

```bash
git add .gitignore README.md
git commit -m "docs: ignore and document the config blob creation scripts"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| Shared helper `create_config.py` with `build_and_encrypt` | Task 1 |
| Flow: credentials → key → filename → plaintext → blob | Task 1 |
| Secrets read via `getpass` | Task 1 (`_ask` secret branch) |
| `encrypt_file` reused, no new crypto | Task 1 |
| `create_partner.py` template (client_id, client_secret, application_id, partner_id) | Task 2 |
| `create_mypos.py` template (gateway_url default, merchant client_id/client_secret) | Task 3 |
| `create_sumup.py` template (api_key, merchant_code) | Task 4 |
| Plaintext `<filename>.json` kept alongside blob | Task 1 |
| Reprompt on empty required values | Task 1 (`_ask`) |
| Encryption failure propagates; plaintext preserved | Task 1 (no catch; file written before encrypt) |
| No upload, no overwrite guard, no format validation | out of scope — no task adds these |

**Placeholder scan:** No TBD/TODO; every code step contains full code.

**Type consistency:** `build_and_encrypt(questions, build_json, default_out, help_out)` signature is identical in Task 1 definition and Tasks 2-4 call sites; `_build(answers)` dict keys match the question labels in every script.

Note: `tests/test_create_config.py` imports are split across tasks (module imports at top, class imports appended before the `if __name__` block). The `from create_partner import _build` lines must be added to the file as the tests are appended.