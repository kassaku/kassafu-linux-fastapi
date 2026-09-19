# Three small scripts to create and encrypt config blobs

## Goal

Provide three small CLI scripts that turn typed-in credentials into the
encrypted blobs KassaFu fetches at runtime (`config.partner` for the myPOS
provider credentials, `config.<id>` for the myPOS/SumUp merchant credentials).

Each script follows the same flow: ask credentials → ask encode key → ask
output filename → write plaintext JSON → encrypt to a blob.

## Design decision (agreed)

- **Shared helper module** `create_config.py` with `build_and_encrypt(...)`;
  the three scripts are thin wrappers that supply their credential prompts and
  JSON template. No duplicated prompt/crypto logic.
- **Plaintext kept on disk** as `<filename>.json` next to the blob
  (matches the existing `config.partner.json` convention; both are gitignored).
- **Reuse crypto** from `encrypt_partner.py` (`encrypt_file`); no new crypto
  code.

## Flow (each script)

1. Prompt for credentials; secrets are read with `getpass` (no echo).
2. Prompt for the encode key with `getpass`.
3. Prompt for the output filename (the blob name, e.g. `config.partner`,
   `config.80581413`).
4. Build the JSON payload, write it to `<filename>.json`.
5. Call `encrypt_file(<filename>.json, <filename>, key)` to produce the blob.
6. Print a confirmation.

## Credential sets / JSON templates

All three include `"app": {"name": "KassaFu"}`.

### create_partner.py

```json
{
  "app": {"name": "KassaFu"},
  "partner": {
    "client_id": "...",
    "client_secret": "...",
    "application_id": "...",
    "partner_id": "..."
  }
}
```

Prompts: partner `client_id`, `client_secret`, `application_id`, `partner_id`.
Typical output name: `config.partner`.

### create_mypos.py

```json
{
  "app": {"name": "KassaFu"},
  "mypos": {
    "gateway_url": "https://api-gateway.mypos.com",
    "merchant": {"client_id": "...", "client_secret": "..."}
  }
}
```

Prompts: `gateway_url` (default `https://api-gateway.mypos.com`), merchant
`client_id`, `client_secret`. The filename prompt's default suggestion is
`config.<terminal_id>`; the user types the real filename.

### create_sumup.py

```json
{
  "app": {"name": "KassaFu"},
  "sumup": {"api_key": "...", "merchant_code": "..."}
}
```

Prompts: `api_key`, `merchant_code`. Default suggestion: `config.<reader_id>`.

## Shared helper contract

`create_config.py`:

```python
def build_and_encrypt(questions, build_json, default_out, help_out) -> None
```

- `questions`: ordered list of `(label, secret, default)` tuples.
- `build_json`: callable receiving the collected answers, returns the dict.
- `default_out`: suggested output filename; `help_out`: usage note.
- Non-secret values are echoed for the user to verify; secrets are hidden.
- Writes `<out>.json`, encrypts to `<out>`, prints confirmation.

## Error handling

- Non-empty required values: reprompt if empty (secrets are re-entered hidden).
- Empty optional values (no default) are allowed only where a blank is
  meaningful (never for secrets).
- Encryption failures propagate with the `encrypt_file` message; the plaintext
  file already written is left in place so the credential entry is not lost.

## Out of scope

- No upload to the server — the scripts only produce the files; upload stays
  a manual step.
- No overwrite guard.
- No validation of credential format (e.g. `cli_`/`sec_` prefixes).