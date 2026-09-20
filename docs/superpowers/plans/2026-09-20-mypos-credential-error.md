# myPOS Credential Error UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When myPOS partner or merchant credentials are rejected, kassafu reports a distinct error code, zhongcan shows a translated "wrong credentials" message, refuses to start any payment, and re-pushes `/config` every 5 minutes to auto-recover once the credentials are fixed on the website.

**Architecture:** kassafu (Python) tracks OAuth auth failures on the myPOS gateway and returns `108014` (partner) / `108015` (merchant) from `/reader/status`. zhongcan (C++) maps those codes to two new `EpaymentState` values, gates `startPayment()`, shows only an error + OK in the payment dialog, and re-POSTs the stored remote config on a 5-minute timer while in the error states. UI strings are added to the sdl2ui lingual system in all 8 languages.

**Tech Stack:** Python 3 + httpx + unittest (kassafu); C++ + SDL + libcurl (zhongcan); Bazel build; JSON.

**Two git repositories are touched:**
- `/home/mensfort/workspace/kassafu` (Tasks 1-2)
- `/home/mensfort/workspace/zhongcan-project` (Tasks 3-9)

Each task commits only inside its own repository.

---

## File Map

**kassafu repo:**
- Modify `mypos_gateway.py` — track partner/merchant auth failures.
- Modify `mypos_terminal.py` — report error codes 108014/108015 in `check_status()` and `process_payment()`.
- Modify `tests/test_mypos_gateway.py`, `tests/test_mypos_terminal.py`.

**zhongcan-project repo:**
- Modify `sdl2ui/include_sdl_graphics/lingual.h` — two new `EtextId` values.
- Modify `sdl2ui/source_sdl_graphics/lingual.cpp` — two new names in the master list.
- Modify 8 files in `sdl2ui/source_sdl_graphics/lingual_{english,dutch,german,simplified,traditional,arabic,bahasa,turkisch}.cpp` — two translations each.
- Modify `zhongcan/include_network/payment_terminal.hpp` — two new enum states.
- Modify `zhongcan/source_network/payment_terminal.cpp` — error-code mapping + `getStatusText`.
- Modify `zhongcan/include_network/payment_terminal_kassafu.hpp` + `zhongcan/source_network/payment_terminal_kassafu.cpp` — core state machine.
- Modify `zhongcan/source_messagebox/message_box_card_payment.cpp` — dialog text + buttons.
- Modify `zhongcan/source_user_interface/card_payment_button.cpp` — button colours.

---

## Task 1: Track auth failures in the myPOS gateway

**Files:**
- Modify: `/home/mensfort/workspace/kassafu/mypos_gateway.py` (`__init__` ~`:71-78`, `_request_partner_token` `:99-136`, `_request_session` `:148-184`)
- Test: `/home/mensfort/workspace/kassafu/tests/test_mypos_gateway.py`

- [ ] **Step 1: Write the failing tests**

Append this class to `tests/test_mypos_gateway.py` (before the `if __name__ == "__main__":` block at the end):

```python
class AuthFailureTrackingTests(unittest.TestCase):
    def test_partner_400_sets_auth_failure(self):
        async def scenario():
            def handler(request):
                return httpx.Response(400, text="invalid client")

            gateway = make_gateway(handler)
            with self.assertRaises(MyPOSGatewayError):
                await gateway._get_partner_token()
            return gateway.auth_failure

        self.assertEqual(asyncio.run(scenario()), "partner")

    def test_partner_success_clears_auth_failure(self):
        async def scenario():
            state = {"fail": True}

            def handler(request):
                if state["fail"]:
                    state["fail"] = False
                    return httpx.Response(400, text="invalid client")
                return httpx.Response(200, json={"access_token": "tok_partner", "expires_in": 3600})

            gateway = make_gateway(handler)
            with self.assertRaises(MyPOSGatewayError):
                await gateway._get_partner_token()
            self.assertEqual(gateway.auth_failure, "partner")
            token = await gateway._get_partner_token()
            return token, gateway.auth_failure

        token, failure = asyncio.run(scenario())
        self.assertEqual(token, "tok_partner")
        self.assertIsNone(failure)

    def test_merchant_400_sets_auth_failure(self):
        async def scenario():
            def handler(request):
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "tok_partner", "expires_in": 3600})
                return httpx.Response(400, text="invalid merchant")

            gateway = make_gateway(handler)
            with self.assertRaises(MyPOSGatewayError):
                await gateway._get_session()
            return gateway.auth_failure

        self.assertEqual(asyncio.run(scenario()), "merchant")

    def test_merchant_success_clears_auth_failure(self):
        async def scenario():
            state = {"fail": True}

            def handler(request):
                if request.url.path == "/api/v1/oauth/token":
                    return httpx.Response(200, json={"access_token": "tok_partner", "expires_in": 3600})
                if state["fail"]:
                    state["fail"] = False
                    return httpx.Response(400, text="invalid merchant")
                return httpx.Response(200, json={"session": "session_abc", "expires_in": 360})

            gateway = make_gateway(handler)
            with self.assertRaises(MyPOSGatewayError):
                await gateway._get_session()
            self.assertEqual(gateway.auth_failure, "merchant")
            session = await gateway._get_session()
            return session, gateway.auth_failure

        session, failure = asyncio.run(scenario())
        self.assertEqual(session, "session_abc")
        self.assertIsNone(failure)

    def test_partner_500_does_not_set_auth_failure(self):
        async def scenario():
            def handler(request):
                return httpx.Response(500, text="boom")

            gateway = make_gateway(handler)
            with self.assertRaises(MyPOSGatewayError):
                await gateway._get_partner_token()
            return gateway.auth_failure

        self.assertIsNone(asyncio.run(scenario()))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_mypos_gateway.AuthFailureTrackingTests -v` (from `/home/mensfort/workspace/kassafu`)
Expected: FAIL — `AttributeError: 'MyPOSGateway' object has no attribute 'auth_failure'`

- [ ] **Step 3: Implement the tracking in `mypos_gateway.py`**

In `__init__`, after `self._session_lock = asyncio.Lock()` add:

```python
        self._auth_failure = None  # "partner" / "merchant" when credentials are rejected
```

Add this property right after `_new_client` (after line 86):

```python
    @property
    def auth_failure(self) -> Optional[str]:
        """'partner' / 'merchant' when that credential set was rejected, else None."""
        return self._auth_failure
```

In `_request_partner_token`, in the success branch (after `self._partner_token_expires = ...`, before `return access_token`):

```python
            self._auth_failure = None
```

Replace the final raise of `_request_partner_token` (currently line 136) with:

```python
        if response.status_code in (400, 401, 403):
            self._auth_failure = "partner"
        raise MyPOSGatewayError(response.status_code, f"Token request failed: HTTP {response.status_code}: {response.text[:200]}")
```

In `_request_session`, in the success branch (after `self._session_expires = ...`, before `return session`):

```python
            self._auth_failure = None
```

Replace the final raise of `_request_session` (currently line 184) with:

```python
        if response.status_code in (400, 401, 403):
            self._auth_failure = "merchant"
        raise MyPOSGatewayError(response.status_code, detail)
```

- [ ] **Step 4: Run the full gateway test suite**

Run: `python3 -m unittest tests.test_mypos_gateway -v` (from `/home/mensfort/workspace/kassafu`)
Expected: all pass (existing + new).

- [ ] **Step 5: Commit (in the kassafu repo)**

```bash
git add mypos_gateway.py tests/test_mypos_gateway.py
git commit -m "feat: track myPOS partner/merchant auth failures on the gateway"
```

---

## Task 2: Report dedicated credential error codes from the myPOS terminal

**Files:**
- Modify: `/home/mensfort/workspace/kassafu/mypos_terminal.py` (imports `:29`, `_map_error_code` `:151-162`, `check_status` `:217-218`, `process_payment` `:259-267`)
- Test: `/home/mensfort/workspace/kassafu/tests/test_mypos_terminal.py`

- [ ] **Step 1: Write the failing tests**

Append this class to `tests/test_mypos_terminal.py`:

```python
class AuthErrorCodeTests(unittest.TestCase):
    def test_check_status_partner_credential_error(self):
        t = make_terminal()
        t.gateway.get_terminal = lambda terminal_id: (_ for _ in ()).throw(
            MyPOSGatewayError(400, "Token request failed: HTTP 400"))
        t.gateway.auth_failure = "partner"

        async def scenario():
            return await t.check_status()

        status = asyncio.run(scenario())
        self.assertEqual(status["error_code"], 108014)
        self.assertFalse(status["online"])

    def test_check_status_merchant_credential_error(self):
        t = make_terminal()
        t.gateway.get_terminal = lambda terminal_id: (_ for _ in ()).throw(
            MyPOSGatewayError(400, "Session request failed: HTTP 400"))
        t.gateway.auth_failure = "merchant"

        async def scenario():
            return await t.check_status()

        status = asyncio.run(scenario())
        self.assertEqual(status["error_code"], 108015)
        self.assertFalse(status["online"])

    def test_check_status_plain_error_keeps_generic_mapping(self):
        t = make_terminal()
        t.gateway.get_terminal = lambda terminal_id: (_ for _ in ()).throw(
            MyPOSGatewayError(404, "not found"))
        t.gateway.auth_failure = None

        async def scenario():
            return await t.check_status()

        self.assertEqual(asyncio.run(scenario())["error_code"], 108002)

    def test_process_payment_credential_error(self):
        t = make_terminal()
        t.gateway.create_payment_error = MyPOSGatewayError(400, "Token request failed: HTTP 400")
        t.gateway.auth_failure = "partner"

        async def scenario():
            return await t.process_payment("ORD-1", 100, "EUR")

        result = asyncio.run(scenario())
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], 108014)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_mypos_terminal.AuthErrorCodeTests -v` (from `/home/mensfort/workspace/kassafu`)
Expected: FAIL — `check_status`/`process_payment` still return 108007/108002.

- [ ] **Step 3: Implement in `mypos_terminal.py`**

Add `Optional` to the type-imports at the top of the file (currently line 28):

```python
from typing import Dict, Optional
```

Add a comment block and helper immediately after `_map_error_code` (after line 162):

```python
    # Dedicated credential-error codes consumed by the POS UI:
    # 108014 = partner credentials rejected by the gateway
    # 108015 = merchant credentials rejected by the gateway
    def _auth_error_code(self) -> Optional[int]:
        failure = getattr(self.gateway, "auth_failure", None)
        if failure == "partner":
            return 108014
        if failure == "merchant":
            return 108015
        return None
```

Replace the `except MyPOSGatewayError` body in `check_status` (currently lines 217-218) with:

```python
        except MyPOSGatewayError as e:
            return {"online": False, "ready": False, "error": e.detail,
                    "error_code": self._auth_error_code() or self._map_error_code(e.status)}
```

Replace the `except MyPOSGatewayError` body in `process_payment` (currently lines 259-267) with:

```python
        except MyPOSGatewayError as e:
            self.current_status = "failed"
            self._log_status_update(order_id, self.current_transaction_id or "", "failed", e.detail)
            return {
                "success": False,
                "status": "failed",
                "message": e.detail,
                "error_code": self._auth_error_code() or self._map_error_code(e.status),
            }
```

- [ ] **Step 4: Run the full test suite**

Run (from `/home/mensfort/workspace/kassafu`):
```bash
python3 -m unittest tests.test_mypos_gateway tests.test_mypos_terminal tests.test_kassafu_endpoints -v
```
Expected: all pass. (`FakeGateway` has no `auth_failure` attribute, so `getattr` returns `None`; existing `test_gateway_error_maps_error_code` still expects 108007.)

- [ ] **Step 5: Commit (kassafu repo)**

```bash
git add mypos_terminal.py tests/test_mypos_terminal.py
git commit -m "feat: report dedicated myPOS credential error codes 108014/108015"
```

---

## Task 3: Add the two text IDs to the lingual enum and master list

**Files:**
- Modify: `/home/mensfort/workspace/zhongcan-project/sdl2ui/include_sdl_graphics/lingual.h:440-453`
- Modify: `/home/mensfort/workspace/zhongcan-project/sdl2ui/source_sdl_graphics/lingual.cpp:664-674`

- [ ] **Step 1: Add the IDs to `lingual.h`**

In the `_PAYMENT_MSG_*` block, insert `_PAYMENT_MSG_MERCHANT_CREDENTIALS` between `_PAYMENT_MSG_INVALID_CONFIG` and `_PAYMENT_MSG_NOT_FOUND`:

```cpp
  _PAYMENT_MSG_INVALID_CONFIG, // Payment terminal error: invalid configuration
  _PAYMENT_MSG_MERCHANT_CREDENTIALS, // Payment terminal error: merchant credentials rejected by the gateway
  _PAYMENT_MSG_NOT_FOUND, // Payment terminal error: not found
```

and insert `_PAYMENT_MSG_PARTNER_CREDENTIALS` between `_PAYMENT_MSG_PAYMENT_QUEUED` and `_PAYMENT_MSG_READER_ERROR`:

```cpp
  _PAYMENT_MSG_PAYMENT_QUEUED, // Payment terminal message: payment queued
  _PAYMENT_MSG_PARTNER_CREDENTIALS, // Payment terminal error: partner credentials rejected by the gateway
  _PAYMENT_MSG_READER_ERROR, // Payment terminal error: reader error
```

- [ ] **Step 2: Add the names to `lingual.cpp`**

In the master name list, insert after the `_PAYMENT_MSG_INVALID_CONFIG` line:

```cpp
	{ "_PAYMENT_MSG_INVALID_CONFIG", _PAYMENT_MSG_INVALID_CONFIG },
	{ "_PAYMENT_MSG_MERCHANT_CREDENTIALS", _PAYMENT_MSG_MERCHANT_CREDENTIALS },
```

and after the `_PAYMENT_MSG_PAYMENT_QUEUED` line:

```cpp
	{ "_PAYMENT_MSG_PAYMENT_QUEUED", _PAYMENT_MSG_PAYMENT_QUEUED },
	{ "_PAYMENT_MSG_PARTNER_CREDENTIALS", _PAYMENT_MSG_PARTNER_CREDENTIALS },
```

- [ ] **Step 3: Verify the new IDs exist**

Run: `grep -c "CREDENTIALS" /home/mensfort/workspace/zhongcan-project/sdl2ui/include_sdl_graphics/lingual.h`
Expected: output `4` (CONFIRM_CREDENTIALS + the 2 new + COUNT) — at minimum the two new IDs print.

Actually run: `grep -n "_PAYMENT_MSG_MERCHANT_CREDENTIALS\|_PAYMENT_MSG_PARTNER_CREDENTIALS" /home/mensfort/workspace/zhongcan-project/sdl2ui/include_sdl_graphics/lingual.h /home/mensfort/workspace/zhongcan-project/sdl2ui/source_sdl_graphics/lingual.cpp`
Expected: 4 matched lines, both IDs in both files.

- [ ] **Step 4: Commit (zhongcan-project repo)**

```bash
git add sdl2ui/include_sdl_graphics/lingual.h sdl2ui/source_sdl_graphics/lingual.cpp
git commit -m "feat: add wrong-credentials text ids to lingual system"
```

---

## Task 4: Translate "wrong credentials" in all 8 languages

**Files:** 8 files under `/home/mensfort/workspace/zhongcan-project/sdl2ui/source_sdl_graphics/lingual_*.cpp` (english, dutch, german, simplified, traditional, arabic, bahasa, turkisch)

All 8 files use the same two insertion points:
- **Merchant** entry: insert AFTER the `_PAYMENT_MSG_INVALID_CONFIG` line, BEFORE `_PAYMENT_MSG_NOT_FOUND`.
- **Partner** entry: insert AFTER the `_PAYMENT_MSG_PAYMENT_QUEUED` line, BEFORE `_PAYMENT_MSG_READER_ERROR`.

Indentation: english/dutch/german/simplified/traditional/bahasa/turkisch use 4 spaces; **arabic uses a tab**. In each file the existing anchor line keeps its exact text (shown as the first line of each block).

- [ ] **Step 1: english — `lingual_english.cpp` (anchors `:446`, `:450`)**

```cpp
    { _PAYMENT_MSG_INVALID_CONFIG, "Missing or invalid configuration" },
    { _PAYMENT_MSG_MERCHANT_CREDENTIALS, "Wrong merchant credentials" },
```
```cpp
    { _PAYMENT_MSG_PAYMENT_QUEUED, "Payment queued" },
    { _PAYMENT_MSG_PARTNER_CREDENTIALS, "Wrong partner credentials" },
```

- [ ] **Step 2: dutch — `lingual_dutch.cpp` (anchors `:444`, `:448`)**

```cpp
    { _PAYMENT_MSG_INVALID_CONFIG, "Ontbrekende of ongeldige configuratie" },
    { _PAYMENT_MSG_MERCHANT_CREDENTIALS, "Verkeerde merchant-gegevens" },
```
```cpp
    { _PAYMENT_MSG_PAYMENT_QUEUED, "Betaling in wachtrij" },
    { _PAYMENT_MSG_PARTNER_CREDENTIALS, "Verkeerde partner-gegevens" },
```

- [ ] **Step 3: german — `lingual_german.cpp` (anchors `:444`, `:448`)**

```cpp
    { _PAYMENT_MSG_INVALID_CONFIG, "Fehlende oder ungültige Konfiguration" },
    { _PAYMENT_MSG_MERCHANT_CREDENTIALS, "Falsche Händler-Zugangsdaten" },
```
```cpp
    { _PAYMENT_MSG_PAYMENT_QUEUED, "Zahlung in Warteschlange" },
    { _PAYMENT_MSG_PARTNER_CREDENTIALS, "Falsche Partner-Zugangsdaten" },
```

- [ ] **Step 4: simplified — `lingual_simplified.cpp` (anchors `:444`, `:448`)**

```cpp
    { _PAYMENT_MSG_INVALID_CONFIG, "配置缺失或无效" },
    { _PAYMENT_MSG_MERCHANT_CREDENTIALS, "商户凭据错误" },
```
```cpp
    { _PAYMENT_MSG_PAYMENT_QUEUED, "支付已排队" },
    { _PAYMENT_MSG_PARTNER_CREDENTIALS, "合作伙伴凭据错误" },
```

- [ ] **Step 5: traditional — `lingual_traditional.cpp` (anchors `:444`, `:448`)**

```cpp
    { _PAYMENT_MSG_INVALID_CONFIG, "配置缺失或無效" },
    { _PAYMENT_MSG_MERCHANT_CREDENTIALS, "商戶憑據錯誤" },
```
```cpp
    { _PAYMENT_MSG_PAYMENT_QUEUED, "支付已排隊" },
    { _PAYMENT_MSG_PARTNER_CREDENTIALS, "合作夥伴憑據錯誤" },
```

- [ ] **Step 6: arabic — `lingual_arabic.cpp` (anchors `:445`, `:449`, TAB indentation)**

```cpp
	{ _PAYMENT_MSG_INVALID_CONFIG, "إعدادات غير صالحة" },
	{ _PAYMENT_MSG_MERCHANT_CREDENTIALS, "بيانات اعتماد التاجر غير صحيحة" },
```
```cpp
	{ _PAYMENT_MSG_PAYMENT_QUEUED, "تم وضع عملية الدفع في قائمة الانتظار" },
	{ _PAYMENT_MSG_PARTNER_CREDENTIALS, "بيانات اعتماد الشريك غير صحيحة" },
```

- [ ] **Step 7: bahasa — `lingual_bahasa.cpp` (anchors `:444`, `:448`)**

```cpp
    { _PAYMENT_MSG_INVALID_CONFIG, "Konfigurasi hilang atau tidak valid" },
    { _PAYMENT_MSG_MERCHANT_CREDENTIALS, "Kredensial merchant salah" },
```
```cpp
    { _PAYMENT_MSG_PAYMENT_QUEUED, "Pembayaran dalam antrean" },
    { _PAYMENT_MSG_PARTNER_CREDENTIALS, "Kredensial partner salah" },
```

- [ ] **Step 8: turkisch — `lingual_turkisch.cpp` (anchors `:444`, `:448`)**

```cpp
    { _PAYMENT_MSG_INVALID_CONFIG, "Eksik veya geçersiz yapılandırma" },
    { _PAYMENT_MSG_MERCHANT_CREDENTIALS, "Satıcı kimlik bilgileri hatalı" },
```
```cpp
    { _PAYMENT_MSG_PAYMENT_QUEUED, "Ödeme sıraya alındı" },
    { _PAYMENT_MSG_PARTNER_CREDENTIALS, "Ortak kimlik bilgileri hatalı" },
```

- [ ] **Step 9: Verify each new ID resolves to text in every language**

Run:
```bash
for lang in english dutch german simplified traditional arabic bahasa turkisch; do
  f=/home/mensfort/workspace/zhongcan-project/sdl2ui/source_sdl_graphics/lingual_$lang.cpp
  grep -q "_PAYMENT_MSG_PARTNER_CREDENTIALS" "$f" && grep -q "_PAYMENT_MSG_MERCHANT_CREDENTIALS" "$f" && echo "$lang OK" || echo "$lang MISSING"
done
```
Expected: all 8 `OK`.

- [ ] **Step 10: Commit (zhongcan-project repo)**

```bash
git add sdl2ui/source_sdl_graphics/lingual_*.cpp
git commit -m "feat: translate wrong-credentials messages in 8 languages"
```

---

## Task 5: Add the two payment states and their text mapping

**Files:**
- Modify: `/home/mensfort/workspace/zhongcan-project/zhongcan/include_network/payment_terminal.hpp:14-27`
- Modify: `/home/mensfort/workspace/zhongcan-project/zhongcan/source_network/payment_terminal.cpp:13-33`, `:120-134`

- [ ] **Step 1: Add the enum values (preserve numeric values)**

In `EpaymentState`, insert the two new values immediately AFTER `CONFIRM_CREDENTIALS` and BEFORE `WAIT_FOR_SUMUP_READER`:

```cpp
	CONFIRM_CREDENTIALS, // Trying to configure the payment terminal
	PARTNER_CREDENTIALS_INVALID, // Partner credentials rejected by the gateway
	MERCHANT_CREDENTIALS_INVALID, // Merchant credentials rejected by the gateway
	WAIT_FOR_SUMUP_READER, // Waiting for a compatible reader
```

Keep comments/indentation consistent with the surrounding enum.

- [ ] **Step 2: Map states to text IDs in `paymentMsgIdToTextId`**

In `payment_terminal.cpp`, `paymentMsgIdToTextId` (`:13-33`), add two cases before `default` (after the existing `case _PAYMENT_MSG_CONFIRM_CREDENTIALS:` line):

```cpp
	case _PAYMENT_MSG_PARTNER_CREDENTIALS: return EpaymentState::PARTNER_CREDENTIALS_INVALID;
	case _PAYMENT_MSG_MERCHANT_CREDENTIALS: return EpaymentState::MERCHANT_CREDENTIALS_INVALID;
```

- [ ] **Step 3: Add display text in `getStatusText`**

In `getStatusText` (`:120-134`), add cases next to the other state names so the status line shows the right message:

```cpp
	case EpaymentState::PARTNER_CREDENTIALS_INVALID: return lingual(_PAYMENT_MSG_PARTNER_CREDENTIALS);
	case EpaymentState::MERCHANT_CREDENTIALS_INVALID: return lingual(_PAYMENT_MSG_MERCHANT_CREDENTIALS);
```

(Follow the exact pattern used by the neighbouring `case` statements.)

- [ ] **Step 4: Compile check**

Run: `bazel build //zhongcan:zhongcan` (from `/home/mensfort/workspace/zhongcan-project`)
Expected: build succeeds.

- [ ] **Step 5: Commit (zhongcan-project repo)**

```bash
git add zhongcan/include_network/payment_terminal.hpp zhongcan/source_network/payment_terminal.cpp
git commit -m "feat: add credential-invalid payment states and text mapping"
```

---

## Task 6: Gate payments, detect the codes, and auto-recover every 5 minutes

**Files:**
- Modify: `/home/mensfort/workspace/zhongcan-project/zhongcan/include_network/payment_terminal_kassafu.hpp` (`:10` area — after `bool m_fastPolling;`)
- Modify: `/home/mensfort/workspace/zhongcan-project/zhongcan/source_network/payment_terminal_kassafu.cpp` (constructor `:6-16`, `setRemoteConfig` `:50-74`, `startPayment` `:76-92`, `update` `:110-172`, `handleReaderStatus` `:250-265`)

- [ ] **Step 1: Add members + method declaration to the header**

After `bool m_fastPolling;` add:

```cpp
	std::string m_remoteDeviceId;
	std::string m_remoteClientUrl;
	std::string m_remoteClientKey;
	std::string m_remotePartnerUrl;
	std::string m_remotePartnerKey;
	Ctimeout m_credentialRetryTimer; // 5-minute retry while credentials are invalid
```

And add the method declaration next to the existing private helpers:

```cpp
	void sendRemoteConfig();
```

Match the types (`std::string` vs the header's existing string alias/type) used by the rest of the file.

- [ ] **Step 2: Store the config in `setRemoteConfig`**

In `setRemoteConfig` (`:50-74`), in addition to building + enqueueing the existing command, store the received values in the new members (use the same final URLs as the enqueued command, so the prefix logic is untouched):

```cpp
	m_remoteDeviceId = deviceId; // adjust to the actual parameter name
	m_remoteClientUrl = clientUrl;
	m_remoteClientKey = clientKey;
	m_remotePartnerUrl = partnerUrl;
	m_remotePartnerKey = partnerKey;
```

- [ ] **Step 3: Implement `sendRemoteConfig()`**

Implement the method in the source file next to `setRemoteConfig`, following the exact style of the existing command-enqueueing code:

```cpp
void CpaymentTerminalKassafu::sendRemoteConfig()
{
	// POST http://127.0.0.1:8888/config with JSON body:
	// {"id": m_remoteDeviceId, "client_url": m_remoteClientUrl,
	//  "client_key": m_remoteClientKey, "partner_url": m_remotePartnerUrl,
	//  "partner_key": m_remotePartnerKey}
	// callback_key = "set_config", timeout 5 s.
	// The response callback is intentionally unhandled (responses are dropped).
}
```

Use the same HTTP/JSON helpers as the existing `setRemoteConfig` command. Note: the `set_config` response stays unhandled — this re-push is fire-and-forget.

- [ ] **Step 4: Gate `startPayment`**

At the very top of `startPayment` (`:76-92`), return `false` (matching the existing failure path) when credentials are invalid:

```cpp
	if (m_currentState == EpaymentState::PARTNER_CREDENTIALS_INVALID ||
		m_currentState == EpaymentState::MERCHANT_CREDENTIALS_INVALID) {
		return false;
	}
```

- [ ] **Step 5: Poll + auto-recover in `update`**

In `update` (`:110-172`), extend the polling list (`:124-148`) so both new states keep polling reader status (add them to the same branch that includes `WAIT_FOR_SUMUP_READER` / the configured states):

```cpp
	case EpaymentState::PARTNER_CREDENTIALS_INVALID:
	case EpaymentState::MERCHANT_CREDENTIALS_INVALID:
		// keep polling /reader/status so the state clears once fixed
		[[fallthrough]]; // follow the existing group pattern instead if that is what the file uses
```

Also manage the 5-minute retry timer in `update` (placed with the other timer handling):

```cpp
	// While credentials are invalid: send config immediately on entry,
	// then re-send every 5 minutes until the state clears.
	if (m_currentState == EpaymentState::PARTNER_CREDENTIALS_INVALID ||
		m_currentState == EpaymentState::MERCHANT_CREDENTIALS_INVALID) {
		if (m_credentialRetryTimer.Expired()) {
			sendRemoteConfig();
			m_credentialRetryTimer.Set(5 * 60 * 1000); // 5 minutes
		}
	} else if (m_credentialRetryTimer.Busy()) {
		m_credentialRetryTimer.Clear();
	}
```

Match the `Ctimeout` API actually used elsewhere in the file (e.g. `Set`/`Expired`/`Busy`/`Clear` vs the naming used by the existing timers).

- [ ] **Step 6: Detect the error codes in `handleReaderStatus`**

In `handleReaderStatus` (`:250-265`), where the status JSON (including `error_code`) is parsed, map the codes before the existing `online`/`ready` handling:

```cpp
	int errorCode = ...; // read "error_code" from the status parse as already done
	if (errorCode == 108014) { m_currentState = EpaymentState::PARTNER_CREDENTIALS_INVALID; return; }
	if (errorCode == 108015) { m_currentState = EpaymentState::MERCHANT_CREDENTIALS_INVALID; return; }
```

Insert these checks BEFORE the existing state transitions so a credential error always wins over the generic device-issue path.

- [ ] **Step 7: Compile check**

Run: `bazel build //zhongcan:zhongcan` (from `/home/mensfort/workspace/zhongcan-project`)
Expected: build succeeds. Fix any naming/API mismatches found during compilation.

- [ ] **Step 8: Commit (zhongcan-project repo)**

```bash
git add zhongcan/include_network/payment_terminal_kassafu.hpp zhongcan/source_network/payment_terminal_kassafu.cpp
git commit -m "feat: gate payments and auto-recover on myPOS credential errors"
```

---

## Task 7: Show the message and a single OK button in the payment dialog

**Files:**
- Modify: `/home/mensfort/workspace/zhongcan-project/zhongcan/source_messagebox/message_box_card_payment.cpp` (`stateToTextId` `:20-37`, `paintButtons` `:117`+, `buildMessage`)

- [ ] **Step 1: Map the new states to their text IDs**

In `stateToTextId` (`:20-37`), add:

```cpp
	case EpaymentState::PARTNER_CREDENTIALS_INVALID: return _PAYMENT_MSG_PARTNER_CREDENTIALS;
	case EpaymentState::MERCHANT_CREDENTIALS_INVALID: return _PAYMENT_MSG_MERCHANT_CREDENTIALS;
```

- [ ] **Step 2: Render the terminal message as the detail line**

In `buildMessage`, the existing logic already uses `session.message` as the detail when `messageId == stateId`; the status line from step 3 of the mapping (`getStatusText`) fills the message. No extra change required beyond confirming both new states flow through the existing `messageId == stateId` path. If the file computes `messageId` via `paymentMsgIdToTextId`, verify it now resolves for the new states.

- [ ] **Step 3: Show only the OK button**

In `paintButtons` (the branch that currently draws PAUSE/Pay cash/Cancel for interactive states, around `:117`), add a group for the two inert states that draws ONLY the OK button (dismiss). Follow the existing single-button pattern used by other inert states:

```cpp
	case EpaymentState::PARTNER_CREDENTIALS_INVALID:
	case EpaymentState::MERCHANT_CREDENTIALS_INVALID:
		// show message + dismiss/OK only (no retry, no pay-cash, no cancel)
		break;
```

Place it with the other "OK only" states so no other buttons are drawn in these states.

- [ ] **Step 4: Compile check**

Run: `bazel build //zhongcan:zhongcan` (from `/home/mensfort/workspace/zhongcan-project`)
Expected: build succeeds.

- [ ] **Step 5: Commit (zhongcan-project repo)**

```bash
git add zhongcan/source_messagebox/message_box_card_payment.cpp
git commit -m "feat: show wrong-credentials message with OK button in payment dialog"
```

---

## Task 8: Keep the payment button in the busy/neutral colour

**Files:**
- Modify: `/home/mensfort/workspace/zhongcan-project/zhongcan/source_user_interface/card_payment_button.cpp` (`onLoop` colour switch around `:160`)

- [ ] **Step 1: Extend the WAIT_DRIVER_CONNECTED/CONFIRM_CREDENTIALS colour group**

In `onLoop`, the switch that sets the button colour groups `WAIT_DRIVER_CONNECTED` and `CONFIRM_CREDENTIALS` together. Add the two new states to that same group so the physical button stays in the neutral/busy colour (no pay-cash highlight):

```cpp
	case EpaymentState::PARTNER_CREDENTIALS_INVALID:
	case EpaymentState::MERCHANT_CREDENTIALS_INVALID:
```

- [ ] **Step 2: Compile check**

Run: `bazel build //zhongcan:zhongcan` (from `/home/mensfort/workspace/zhongcan-project`)
Expected: build succeeds.

- [ ] **Step 3: Commit (zhongcan-project repo)**

```bash
git add zhongcan/source_user_interface/card_payment_button.cpp
git commit -m "feat: keep payment button neutral in credential-error states"
```

---

## Final verification and wrap-up

- [ ] **Step 1: Full Python test suite (kassafu repo)**

Run (from `/home/mensfort/workspace/kassafu`):
```bash
python3 -m unittest discover -s tests -v
```
Expected: all tests pass.

- [ ] **Step 2: Final C++ build (zhongcan-project repo)**

Run: `bazel build //zhongcan:zhongcan` (from `/home/mensfort/workspace/zhongcan-project`)
Expected: build succeeds with no new warnings for the changed files.

- [ ] **Step 3: Confirm all intended changes are committed**

In `/home/mensfort/workspace/kassafu`: `git status` clean; 2 new commits (Tasks 1-2) on top of `79fb82a`.
In `/home/mensfort/workspace/zhongcan-project`: 6 new commits (Tasks 3-8) on branch `HHA-45-reservation-direct-first`.

- [ ] **Step 4: Show smoke-test steps to the user (do NOT run the live stack)**

Summarize the manual verification the user can do when they choose to deploy:
1. Break the myPOS partner or merchant credential on the website / in the deploy config.
2. Restart the stack; start a payment in the POS UI.
3. Expect the "Wrong partner/merchant credentials" message (`108014`/`108015` path), payment blocked, only OK to dismiss.
4. Fix the credentials on the website; within ~5 minutes the terminal must recover automatically (config re-pushed) and payments work again.

Also note: the live deployment `~/zhongcan` (kassafu on `127.0.0.1:8888`) was intentionally left untouched; deployment is the user's step.

- [ ] **Step 5: Review the finished work**

Use superpowers:requesting-code-review, then superpowers:finishing-a-development-branch to decide how to integrate the branches (merge/PR per repository).

---

## Self-review notes (for the plan author)

- **Test-first:** Tasks 1 and 2 are pure TDD (failing tests written in Step 1 before any implementation). C++ tasks use compile-check-instead (no test harness in zhongcan for the UI state machine), consistent with how the repo is tested.
- **Gate placement:** the payment gate lives only in `CpaymentTerminalKassafu::startPayment`; the simulation terminal is intentionally untouched so dev/simulation flows still work.
- **Numeric enum safety:** Task 5 inserts new states after `CONFIRM_CREDENTIALS` so existing numeric `EpaymentState` values (persisted/queued) do not shift.
- **Detection is code-based:** kassafu sets `_auth_failure` only on HTTP 400/401/403 from `/api/v1/oauth/token` (partner) or `/api/v1/auth/session` (merchant). 5xx and transport errors never reclassify; any success clears the flag. zhongcan keys off the numeric `error_code` (108014/108015), never error-string matching.
- **Recovery is fire-and-forget:** `sendRemoteConfig()` re-POSTs `/config` with `callback_key="set_config"` and deliberately drops the response (existing behaviour), so recovery cannot wedge on a bad reply. The 5-minute timer restarts while the state is invalid and clears otherwise.
- **Simulation/coverage caveat:** `FakeGateway` in `tests/test_mypos_terminal.py` has no `auth_failure` attribute by design; implementations must use `getattr(self.gateway, "auth_failure", None)` so existing tests keep passing unchanged.
- **Line numbers are references:** the code block shapes (constructor `:6-16`, `setRemoteConfig` `:50-74`, etc.) were gathered from the working tree; if the file drifted, match by surrounding context, not the exact number.
- **Translation anchors:** both new lingual entries reuse existing anchor lines (`INVALID_CONFIG`, `PAYMENT_QUEUED`) that already exist in every language file; insertion keeps `NOT_FOUND`/`READER_ERROR` order intact. Arabic file uses TAB indentation; the other 7 use 4 spaces.