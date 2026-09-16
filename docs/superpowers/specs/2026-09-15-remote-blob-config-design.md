# Remote configuration via two encrypted blobs (partner + client) with separate keys

## Goal

Replace the current inline-config design entirely: instead of sending
`{sumup: ...}` / `{mypos: ...}` credentials in `POST /config` (or in a local
`config.*.json` file), the POS sends **two URLs, two decryption keys, and one
device id**. KassaFu downloads the two encrypted files, decrypts them, and
assembles the runtime configuration itself.

This design is deliberately generic — it is a reusable recipe for any program
that must serve many customers while keeping *provider* credentials and
*customer* credentials secret and physically separated:

- The **partner file** holds everything the *provider* (e.g. the myPOS payment
  platform) issues to the software vendor: `client_id`, `client_secret`,
  `application_id`, `partner_id`.
- The **client file** holds everything a *customer/merchant* needs to connect
  their own terminal account: e.g. the myPOS `gateway_url`, `merchant`, and
  `terminal_id`, or the SumUp `api_key`, `merchant_code`, `reader_id`.
- A single file is still unreadable: a customer file without the partner file
  (myPOS) is useless, and the partner file without any customer file is
  useless. Two keys means a compromise of one customer's key never exposes the
  partner credentials.

## Design decisions (agreed)

1. **URL-only configuration.** `POST /config` accepts exactly the 5 fields
   below. Inline `{sumup: ...}` / `{mypos: ...}` configs are no longer
   accepted. There is one clear configuration mode.
2. **Order of resolution** (fixed): fetch + decrypt the **client** file first;
   decide the terminal type from its contents; only if that type needs it,
   fetch + decrypt the **partner** file. SumUp never requires the partner file.
3. **Section-key detection.** The terminal type is decided by which section
   the decrypted client file contains: a `sumup` key → SumUp, a `mypos` key →
   myPOS. No `mode` field is required.
4. **Separate keys.** `partner_key` decrypts the partner file, `client_key`
   decrypts the client file. For SumUp the partner fields are simply unused
   (accepted, ignored).
5. **No inline credentials, no disk cache.** Blobs are always fetched from the
   remote URLs; a network/decrypt failure is a hard `400`. Nothing is written
   to disk, and no secrets are logged, echoed, or returned by `GET /config`.
6. **Non-secret device id passes through.** The `id` field is a *runtime*
   parameter (the actual terminal/reader id), not part of any blob. It is used
   directly as `mypos.terminal_id` or `sumup.reader_id`. (These ids are public
   device identifiers — encrypting them adds nothing, and keeping them in the
   interface means a merchant with several terminals still needs only one
   client file.)
7. **Strict validation.** After decryption the client file must contain
   exactly the keys its type requires, else the request fails with a clear
   `400`. "It should contain exactly the right keys else the program cannot
   work."
8. **Same blob format as the partner work** — the AES-256-GCM v1 blob format,
   so `encrypt_partner.py`'s crypto is reused unchanged for both files.

## Interface

`POST /config` request body (JSON):

```json
{
  "partner_url": "http://www.kassaku.nl/restaurants/install/config.partner",
  "client_url": "https://example.com/configs/config.1234567890",
  "partner_key": "partner-secret-phrase",
  "client_key": "client-secret-phrase",
  "id": "80581413"
}
```

CLI startup (same fields, same defaults):

```
python3 kassafu.py --server \
  --partner-url http://www.kassaku.nl/restaurants/install/config.partner \
  --client-url https://example.com/configs/config.1234567890 \
  --partner-key <partner-secret> --client-key <client-secret> --id 80581413
```

- `partner_url` and `partner_key` are **optional** (ignored for SumUp).
  `client_url`, `client_key`, and `id` are **required** in the interface.
- `partner_url` default: `http://www.kassaku.nl/restaurants/install/config.partner`
  (partner files are named `config.partner` on the host; see Naming below).
- `partner_url`/`client_url` are fetched with a 10 s timeout and redirects
  followed. Both files are **remote blobs** — no local file paths.

Field naming table (intentional, for other integrators):

| Interface field | Role | Secret? |
| --- | --- | --- |
| `partner_url` | where the provider-credential blob lives | no |
| `client_url` | where the merchant-credential blob lives | no |
| `partner_key` | key that decrypts the partner blob | **yes** |
| `client_key` | key that decrypts the client blob | **yes** |
| `id` | device id (terminal/reader), passed to the terminal | no |

## Blob file naming (convention)

Hosted files use a `config.<id>` convention so a POS can guess the client URL
from the id, but this is **convention only** — `client_url` is always supplied
explicitly and never derived:

- partner file: `config.partner`
- client files: `config.<terminal_id>` or `config.<reader_id>`

The two files are **encrypted** on the host using `encrypt_partner.py`; only
the vendor holds the plaintext and the keys.

## Encrypted blob format (version 1) — unchanged from the partner work

| Field | Size | Note |
| --- | --- | --- |
| `KASSAFU_BLOB` magic | 12 bytes | constant, ASCII |
| version byte | 1 byte | `0x01` |
| PBKDF2 salt | 16 bytes | `os.urandom` per encryption |
| iteration count | 4 bytes | big-endian, `200000` |
| AES-GCM nonce | 12 bytes | `os.urandom` per encryption |
| ciphertext + GCM tag | variable + 16 | GCM appends the tag |

Decryption:
1. Verify magic + version byte; bail on mismatch.
2. Derive key: `PBKDF2HMAC(SHA256, length=32, salt, iterations)`.
3. `AESGCM(key).decrypt(nonce, payload)` — raises on tampering/wrong key.
4. Result is the plaintext (UTF-8 JSON).

## Blob contents (plaintext JSON)

### Client file — SumUp

```json
{
  "app": {"name": "KassaFu"},
  "sumup": {
    "api_key": "sup_sk_...",
    "merchant_code": "MN2RA8M1"
  }
}
```

(`id` in the interface becomes `reader_id`; it is NOT in this file.)

### Client file — myPOS

```json
{
  "app": {"name": "KassaFu"},
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "merchant": {
      "client_id": "cli_3KmJ3uXR1vnVUx5lRRYrfvvEezRv",
      "client_secret": "sec_JwnJTwmDdkIwwxpP4mrj3RPmgE6cZX5Ttk7n37xKB0geiFurYlWOEOvdH73d"
    }
  }
}
```

(`id` in the interface becomes `terminal_id`; it is NOT in this file.)

### Partner file — myPOS only

```json
{
  "app": {"name": "KassaFu"},
  "partner": {
    "client_id":     "client_dc3eea767ded4789810d3cff37c16d82",
    "client_secret": "secret_9ed70823a13a31142d2a23842b3ca0a31ae6920da4830aaef4344703f6ffac97",
    "application_id": "mps-app-30034196",
    "partner_id":     "mps-p-10009055"
  }
}
```

### Assembled runtime config

After resolution KassaFu builds exactly the config the existing terminal
`.init()` expects:

SumUp:

```json
{
  "app": {"name": "KassaFu"},
  "sumup": {
    "api_key": "sup_sk_...",
    "merchant_code": "MN2RA8M1",
    "reader_id": "<id from interface>"
  }
}
```

myPOS:

```json
{
  "app": {"name": "KassaFu"},
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "merchant": {"client_id": "...", "client_secret": "..."},
    "terminal_id": "<id from interface>",
    "partner": {
      "client_id":     "...",
      "client_secret": "...",
      "application_id": "...",
      "partner_id":     "..."
    }
  }
}
```

## Runtime flow (kassafu)

New helpers in `kassafu.py` (all network/decrypt work happens on the request
thread or main thread — never on the bridge loop):

```python
def _fetch_blob_json(url: str, key: str, what: str) -> dict:
    """GET url → decrypt_blob → json.loads. Raises PartnerConfigError."""

def _resolve_remote_config(interface: dict) -> dict:
    """Turn the 5 interface fields into a fully-resolved runtime config."""
```

`_resolve_remote_config` implements exactly the agreed order:

1. `client = _fetch_blob_json(client_url, client_key, "client")`
2. Detect type from the client file:
   - `sumup` section present → SumUp (partner file not consulted).
   - `mypos` section present → myPOS; then
     `partner = _fetch_blob_json(partner_url or PARTNER_URL_DEFAULT, partner_key, "partner")`
     and inject `client["mypos"]["partner"] = partner`.
3. Inject `client[section]["terminal_id" | "reader_id"] = interface["id"]`.
4. Strict-validate the resolved config (below).
5. Return the assembled dict.

Call sites:
- `update_config()` (POST /config): parse the 5 fields, call
  `_resolve_remote_config`, then `bridge.run(_apply_config_atomic(resolved))`
  as today. On `PartnerConfigError` → `{"detail": str(exc)}, 400`.
- `_startup()`: the CLI flags seed the same 5 fields; resolve them once before
  terminal init. If resolution fails at boot, log and continue unconfigured
  (the POS can still fix it with POST /config later).

`_apply_runtime_config` keeps its existing contract (takes a fully-resolved
config; the caller resolves first).

## Validation (strict)

- Client file must be a JSON object and have exactly one of `sumup` / `mypos`.
  Both present or neither present → `400`.
- SumUp requires: `sumup.api_key`, `sumup.merchant_code`.
- myPOS requires: `mypos.gateway_url`, `mypos.merchant` (object with
  `client_id` and `client_secret`), `mypos.terminal_id` (injected from `id`),
  and a valid `mypos.partner` object (from the partner file) with
  `client_id`, `client_secret`, `application_id`, `partner_id`.
- All failures return a clear `400 {"detail": "..."}` explaining exactly what
  is missing or wrong.

## Error handling

| Condition | Result |
| --- | --- |
| `client_url` fetch fails | `400 {"detail": "Failed to fetch client configuration: ..."}` |
| Client blob won't decrypt (wrong `client_key` / tampered) | `400 {"detail": "Failed to decrypt client configuration: ..."}` |
| Client plaintext not valid JSON / missing both sections / both sections | `400 {"detail": "Failed to parse client configuration: ..."}` |
| SumUp client missing `api_key`/`merchant_code` | `400 {"detail": "Missing sumup.api_key/merchant_code ..."}` |
| myPOS client missing required keys | `400 {"detail": "Missing mypos.gateway_url/merchant ..."}` |
| myPOS: `partner_url` fetch fails / wrong `partner_key` / bad partner JSON | `400 {"detail": "Failed to fetch/decrypt/parse partner configuration: ..."}` |
| myPOS: partner object missing fields | `400 {"detail": "Missing mypos.partner.* ..."}` |
| Interface missing `client_url`/`client_key`/`id` | `400 {"detail": "Missing client_url/client_key/id ..."}` |
| `get_config()` | never contains any key or secret |

Note: because resolution runs before the atomic apply guard, a `400` for a bad
blob can precede a `409` for an active payment that started mid-request. The
atomic guard itself is unchanged — a good config is never hot-swapped mid
payment.

## `GET /config` behavior

- **Unconfigured** → `{"message": "config not available, please check tomorrow"}`
- **Configured** → resolved runtime config as today, minus all keys/secrets
  (the terminal classes already strip secrets in `get_config()`).

## Broad brush (other integrators)

This section generalizes the recipe so a different program can reuse it:

1. Decide which data is **provider-wide** (shared by all customers; one file)
   vs **customer-specific** (per merchant; many files).
2. Put provider-wide data in the *partner* file, customer data in the *client*
   file, both as versioned AES-256-GCM blobs, each with its own key.
3. Give the *interface* 5 fields: partner URL + key, client URL + key, and the
   non-secret device id. URLs are secrets-agnostic; keys are the secrets.
4. Resolve in a fixed order: client first (it decides the type), partner only
   if the client type needs it.
5. Validate strictly after decryption — the decrypted content defines what the
   program needs to run; anything missing is a hard error with a clear message.
6. Never cache, never log, never return keys.

## Deployment, deps, docs

- `encrypt_partner.py` is reused as-is (crypto + `decrypt_blob`). Its
  `fetch_partner` cache behavior is **delegated away** — kassafu now uses
  `decrypt_blob` + a thin `_fetch_blob_json` instead, so no disk cache exists.
  `fetch_partner`, `PARTNER_URL_DEFAULT`, and cache constants may remain but
  are not part of the new path; the plan will decide removal.
- `requirements.txt`: unchanged (cryptography already added).
- `install.sh` / `create_deb`: already copy `encrypt_partner.py`.
- `README.md`: rewrite the configuration section to the URL/key/id model.
- `API.md`: update `POST /config` and `GET /config` examples.
- `SOFTWARE.md`: already lists `cryptography`.

## Out of scope / notes

- No webhook, no periodic re-fetch: kassafu resolves on config apply/startup
  only.
- No id-derived URL derivation (homework noted — `client_url` is always
  explicit; `config.<id>` is a naming convention only).
- Both blobs are encrypted; the vendor keeps both keys. HTTP (not HTTPS) is
  used for the default partner URL as before; security is carried by the
  authenticated GCM blob.
- The `id` field is passed through to the terminal; terminal auto-discovery
  (`_maybe_discover`) still applies when the caller wants kassafu to find the
  id itself (it will then overwrite the field).