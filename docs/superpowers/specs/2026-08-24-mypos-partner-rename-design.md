# myPOS Config Rename: `integration` → `partner` (Portal-Aligned Names)

**Date:** 2026-08-24
**Status:** Approved by user
**Goal:** Make the myPOS config section mirror the partners.mypos.com integration summary page verbatim, eliminating recurring "which credential goes where" confusion.

## Background

The current schema splits the four Partners Portal values across two places:

```json
"mypos": {
  "integration": {"client_id": "...", "client_secret": "..."},
  "partner_id": "...",
  "application_id": "..."
}
```

This caused repeated misconfiguration during bring-up (credentials pasted into the wrong block, secret formats mixed up). The portal page (`partners.mypos.com/…/integrations/<id>/summary`) presents all four values together as **Client ID, Client Secret, Application ID, Partner ID**.

## New Schema

```json
"mypos": {
  "gateway_url": "https://api-gateway.mypos.com",
  "partner": {
    "client_id": "client_…",
    "client_secret": "secret_…",
    "application_id": "mps-app-…",
    "partner_id": "mps-p-…"
  },
  "merchant": {
    "client_id": "cli_…",
    "client_secret": "sec_…"
  },
  "terminal_id": "80569179"
}
```

Rules:

1. The `partner` object contains exactly the four fields shown on the Partners Portal summary page, with the portal's field names.
2. The `merchant` object keeps its existing shape (`client_id`, `client_secret`) for merchant-approval credentials.
3. `gateway_url` and `terminal_id` are not shown on the portal page and remain top-level in the `mypos` section.
4. A config still using the old `"integration"` key must fail terminal init with an explicit message: `"mypos.partner missing (was 'integration')"` — no silent fallback.

## Changes

| File | Change |
|---|---|
| `mypos_gateway.py` | Read credentials from `config["partner"]`; read `partner_id`/`application_id` from within that object instead of top-level |
| `mypos_terminal.py` | Required-field validation targets the new layout; missing `partner` produces the explicit rename message |
| `tests/test_mypos_gateway.py`, `tests/test_mypos_terminal.py`, `tests/test_kassafu_config.py` | Fixtures use the new layout; add one test asserting the old `integration` key yields the rename error |
| Docs | Update live reference material only (README, config templates). Historical spec/plan documents stay untouched — they record past decisions. |

## Out of Scope

- Updating the live deployment at `~/zhongcan/config.json` — user handles that manually after this ships.
- Format validation of credential prefixes (`client_*` vs `cli_*`) — declined for now.
- SumUp config untouched.

## Verification

- Full unit suite green.
- Booting kassafu with `--config config.mypos.json` (updated to new layout) reaches the same runtime state as before the rename: token step succeeds against production gateway; session step fails only due to pending merchant credentials.
