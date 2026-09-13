# Partner configuration via encrypted remote XML

## Goal

Remove the myPOS `partner` credentials (`client_id`, `client_secret`,
`application_id`, `partner_id`) from the checked-in `config.mypos.json` and
instead fetch them, at runtime, from an encrypted file hosted on kassaku.nl:

    http://www.kassaku.nl/restaurants/install/partner.xml

The hosted file is a versioned AES-256-GCM blob (header + ciphertext). kassafu
downloads it, decrypts it with a secret key, and merges the partner
credentials into the active myPOS configuration before the terminal is
initialized. The decryption key is **never stored in code, config files, or
git**. It is supplied at runtime via `POST /config` (`mypos.partner_key`) or
via the `--key` CLI flag for terminal testing.

## Design decisions (agreed)

1. **Always fetch** — an inline `mypos.partner` block in any config is no
   longer honored. A myPOS config without a resolvable (fetched + decrypted)
   partner section fails terminal init.
2. **Encrypted from day one** — the plaintext partner JSON is never hosted and
   never committed. The hosted file is only the encrypted blob.
3. **Key transport** — `mypos.partner_key` (pushed by the POS/rest-API) or
   `--key <key>` (terminal testing). The key is a passphrase string; it is
   never written to disk, never logged, never returned by `GET /config`.
4. **Cache with fallback** — after the first successful fetch the blob is
   cached locally (`./partner.xml.enc` by default). If the network fails later,
   kassafu decrypts from the cached copy and logs a warning.
5. **One small tool** — `encrypt_partner.py` is both the "encrypt a file by
   hand" CLI and the importable crypto/fetch library kassafu uses at runtime.
   No separate library module.
6. **Crypto primitive** — AES-256-GCM (authenticated: confidentiality +
   integrity). PBKDF2-HMAC-SHA256 (200,000 iterations) derives the 256-bit
   key from the passphrase. `cryptography` is added to requirements.

## Encrypted blob format (version 1)

| Field | Size | Note |
| --- | --- | --- |
| `KASSAFU_BLOB` magic | 12 bytes | constant, ASCII |
| version byte | 1 byte | `0x01` |
| PBKDF2 salt | 16 bytes | `os.urandom` per encryption |
| iteration count | 4 bytes | big-endian, `200000` |
| AES-GCM nonce | 12 bytes | `os.urandom` per encryption |
| ciphertext + GCM tag | variable + 16 | GCM appends the tag |

Deciption algorithm:
1. Verify magic + version byte; bail on mismatch.
2. Derive key: `PBKDF2HMAC(SHA256, length=32, salt, iterations)`.
3. `AESGCM(key).decrypt(nonce, payload)` — raises on tampering / wrong key
   (GCM authentication failure).
4. Result is the plaintext (UTF-8 JSON).

Any unknown version byte is rejected with a clear error (future-proofing for
the "heavier encryption" upgrade path).

## `encrypt_partner.py` (new, committed)

CLI (hand-encryption tool):

    python3 encrypt_partner.py --key "//B1a9r6t8//" --input partner.json --output partner.xml.enc

Module API used by kassafu:

- `PARTNER_URL_DEFAULT = "http://www.kassaku.nl/restaurants/install/partner.xml"`
- `encrypt_file(input_path, output_path, key)` — read plaintext file, write blob.
- `decrypt_blob(blob: bytes, key: str) -> bytes` — raise `PartnerConfigError` on
  bad magic/version/tag.
- `parse_partner(plaintext: bytes) -> dict` — `json.loads`; return the `partner`
  dict; raise `PartnerConfigError` if absent/invalid.
- `fetch_partner(partner_url, key, cache_path) -> dict` — `httpx.get` with a
  10s timeout; on success write the blob to `cache_path`; on network failure
  fall back to the cached blob; then `decrypt_blob` + `parse_partner`. Raise
  `PartnerConfigError` if both fetch and cache are unavailable.
- `PartnerConfigError(Exception)`.

The blob plaintext is valid JSON; content (from the user's example, normalized):

```json
{
  "app": {"name": "KassaFu", "mode": "mypos"},
  "partner": {
    "client_id":     "client_dc3eea767ded4789810d3cff37c16d82",
    "client_secret": "secret_9ed70823a13a31142d2a23842b3ca0a31ae6920da4830aaef4344703f6ffac97",
    "application_id": "mps-app-30034196",
    "partner_id":     "mps-p-10009055"
  }
}
```

## kassafu runtime integration

New helper in `kassafu.py`:

```python
def _merge_partner(cfg: dict) -> dict:
    """Fetch + decrypt + inject myPOS partner creds into a copy of cfg."""
```

Behavior:
- If the resolved terminal type is not `mypos`, return `cfg` unchanged.
- Resolve URL: `cfg["mypos"]["partner_url"]` or `PARTNER_URL_DEFAULT`.
- Resolve key: `cfg["mypos"]["partner_key"]` or the `--key` CLI global.
  Missing both → `PartnerConfigError` ("Missing partner encryption key ...").
- Call `fetch_partner(url, key, cache_path)`; cache path defaults to
  `./partner.xml.enc` (configurable via `mypos.partner_cache`).
- Return a new dict: `cfg` copy with `cfg["mypos"]["partner"]` set to the
  fetched partner dict. The original dict is not mutated.

Call sites (both on threads that are safe to block on network — never on the
bridge loop):
- `update_config()` (POST /config): after `request.get_json`, before
  `bridge.run(_apply_config_atomic(...))`. On `PartnerConfigError`, return
  `{"detail": str(exc)}, 400`.
- `_startup()`: merge `config` before terminal init when `--config` seeds a
  myPOS config and no `--key` needed at boot. `_startup` is called before
  `serve()` on the main thread.

`_apply_runtime_config` keeps the existing contract (takes a fully-resolved
config; the caller is responsible for merging). Its error message
`"Failed to initialize {terminal_type} terminal with supplied configuration"`
covers a missing/unmergable partner section.

`--key` is added to the existing argparse in `__main__`:
`parser.add_argument("--key", type=str, help="Partner encryption key (terminal testing)")`.
Stored in a module global `KASSAFU_PARTNER_KEY` consulted by `_merge_partner`.

The bridge loop is never blocked by fetch/decrypt work.

## Config file shape

`config.mypos.json` (edited) — partner block removed, URL/key fields added:

```json
{
  "app": {"name": "KassaFu", "mode": "mypos"},
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "partner_url": "http://www.kassaku.nl/restaurants/install/partner.xml",
    "partner_key": "",
    "partner_cache": "partner.xml.enc",
    "merchant": {"client_id": "...", "client_secret": "..."},
    "terminal_id": "80581413"
  }
}
```

Notes:
- `merchant`/`terminal_id`/`gateway_url` stay (out of scope: merchant secrets
  were already in the repo and are not moved by this change).
- `partner_key` is the runtime-supplied key (empty in the committed file;
  real value pushed by the POS or via `--key`).

## Error handling

| Condition | Result |
| --- | --- |
| Fetch fails, cache absent | `400 {"detail": "Failed to fetch partner configuration: ..."}` |
| Blob can't decrypt (wrong key / tampered) | `400 {"detail": "Failed to decrypt partner configuration: ..."}` |
| Plaintext not valid partner JSON | `400 {"detail": "Failed to parse partner configuration: ..."}` |
| No key available | `400 {"detail": "Missing partner encryption key ..."}` |
| `get_config()` / `/pay` / logs | partner_key, client_secret never appear |

`POST /config` may return `400` for a broken partner fetch instead of `409`
for an active payment that started mid-fetch; the atomic apply guard still
never hot-swaps during an active payment. The `409`-vs-`400` precedence shift
is accepted and rare; documented.

## Testing

`tests/test_encrypt_partner.py` (new, no network):
- round-trip: `encrypt_file` → `decrypt_blob` returns original bytes.
- wrong key raises `PartnerConfigError`.
- corrupted byte in blob raises `PartnerConfigError` (GCM tag).
- unknown version byte raises `PartnerConfigError`.
- `parse_partner` extracts the 4 fields; rejects bad JSON / missing partner.
- `fetch_partner` fallback: point `partner_url` at a dead local URL and a
  pre-written cache file → decrypts from cache (monkeypatched `httpx.get`).

`tests/test_kassafu_config.py` (updated):
- `MYPOS_CONFIG` keeps a `partner` block so `_apply_runtime_config` unit tests
  still exercise init (the low-level applier expects a fully-resolved config).
- New tests for `_merge_partner`: myPOS + monkeypatched `fetch_partner` →
  partner injected; non-mypos → unchanged; missing key → `PartnerConfigError`.

`tests/test_kassafu_endpoints.py` (updated): POST /config myPOS cases use a
monkeypatched `_merge_partner` (or `fetch_partner`) so endpoint tests stay
offline. Existing 22 endpoint tests keep passing.

## Deployment, deps, docs

- `requirements.txt`: add `cryptography`.
- `install.sh`: copy `encrypt_partner.py` alongside the other `.py` files.
- `create_deb`: add `encrypt_partner.py` to the `cp` list and chmod loop.
- `README.md`: update the myPOS config example (no inline partner; add
  `partner_url` / `partner_key`), and document `encrypt_partner.py` +
  fetch/decrypt flow.
- `API.md`: update the myPOS request-body example in the same way (check
  whether it documents a config body; if not, skip).
- `SOFTWARE.md`: add `cryptography` to the dependency list.

## Out of scope / notes

- No webhook, no periodic re-fetch: kassafu fetches on config apply /
  startup only. Partner credentials rotate rarely; the gateway already
  refreshes OAuth tokens internally.
- HTTP (not HTTPS) is used for the default URL as specified. Security is
  carried by the authenticated GCM blob: a MITM can substitute only a blob
  that fails decryption, which triggers the cache fallback. The site can
  switch to HTTPS without any kassafu change.
- The user-supplied example key `//B1a9r6t8//` is a working passphrase for
  generating the blob; it must never be added to code/git. For production,
  rotate to a fresh key that is kept only in the POS/rest-API and the
  installer's memory.