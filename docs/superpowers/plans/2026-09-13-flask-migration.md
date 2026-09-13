# Flask Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace FastAPI/uvicorn with Flask (served by waitress) in `kassafu.py`, keeping the HTTP contract identical and the async terminal stack untouched via a background asyncio-loop bridge; remove the unused `ccv.py`.

**Architecture:** A new `asyncio_bridge.py` runs a single daemon-thread asyncio event loop. Flask views dispatch async work onto that loop with `bridge.run()` (blocking, returns result) and `bridge.create_task()` (fire-and-forget, for the payment queue consumer). Terminal init also happens on the loop thread, preserving FastAPI's single-loop semantics. All `/pay`-queue state stays confined to the loop.

**Tech Stack:** Python 3.12, Flask 3.1.3, waitress 3.0.2, stdlib `unittest`, existing asyncio terminal/gateway stack (sumup SDK, httpx).

**Spec:** `docs/superpowers/specs/2026-09-13-flask-migration-design.md`

**Test command (all tasks):**
```bash
cd /home/mensfort/workspace/kassafu && source venv/bin/activate && python -m unittest discover -s tests -v
```

---

### Task 1: `asyncio_bridge.py` (bridge helpers + unit tests)

**Files:**
- Create: `tests/test_asyncio_bridge.py`
- Create: `asyncio_bridge.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_asyncio_bridge.py`:

```python
import asyncio
import unittest

from asyncio_bridge import bridge


class AsyncBridgeTests(unittest.TestCase):
    def test_run_executes_coroutine_on_bridge_loop(self):
        async def add(a, b):
            return a + b

        self.assertEqual(bridge.run(add(2, 3)), 5)

    def test_run_re_raises_coroutine_exceptions(self):
        async def boom():
            raise ValueError("nope")

        with self.assertRaises(ValueError):
            bridge.run(boom())

    def test_call_in_loop_binds_asyncio_objects_to_bridge_loop(self):
        queue = bridge.call_in_loop(asyncio.Queue)

        async def put_get():
            await queue.put("x")
            return await queue.get()

        self.assertEqual(bridge.run(put_get()), "x")

    def test_create_task_schedules_without_waiting(self):
        done = []

        async def worker():
            await asyncio.sleep(0)
            done.append(True)

        future = bridge.create_task(worker())
        future.result(timeout=5)
        self.assertEqual(done, [True])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `source venv/bin/activate && python -m unittest tests.test_asyncio_bridge -v`
Expected: `ModuleNotFoundError: No module named 'asyncio_bridge'`

- [ ] **Step 3: Write the minimal implementation**

Create `asyncio_bridge.py`:

```python
"""Bridge a background asyncio event loop to synchronous Flask handlers.

The terminal stack (sumup_terminal, mypos_terminal, mypos_gateway) is fully
async. Flask is synchronous, so all async work is dispatched onto a single
daemon thread running asyncio. The loop starts lazily on first use, keeping
module import side-effect free for tests.
"""

import asyncio
import threading


class AsyncBridge:
    """Owns one background asyncio event loop thread."""

    def __init__(self):
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._thread_main,
                args=(loop,),
                name="kassafu-async",
                daemon=True,
            )
            thread.start()
            self._loop = loop
            self._thread = thread

    @staticmethod
    def _thread_main(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def run(self, coro):
        """Run an awaitable on the loop thread and block until it completes.

        Returns the coroutine's result. Exceptions from the coroutine are
        re-raised in the calling thread.
        """
        self._ensure_started()
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def create_task(self, coro):
        """Schedule an awaitable on the loop thread without waiting on it.

        Returns the concurrent.futures.Future wrapping the task.
        """
        self._ensure_started()
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def call_in_loop(self, fn, *args, **kwargs):
        """Run a plain sync callable on the loop thread and return its result.

        Used for constructing asyncio objects (e.g. asyncio.Queue) so they
        bind to the bridge loop, and for terminal init() calls so they happen
        on the same thread as the async payment work.
        """
        async def _wrapper():
            return fn(*args, **kwargs)

        return self.run(_wrapper())


bridge = AsyncBridge()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `source venv/bin/activate && python -m unittest tests.test_asyncio_bridge -v`
Expected: all 4 tests pass

- [ ] **Step 5: Commit**

```bash
git add asyncio_bridge.py tests/test_asyncio_bridge.py
git commit -m "feat: add background asyncio bridge for sync Flask handlers"
```

---

### Task 2: Swap dependencies (requirements.txt + install)

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Replace FastAPI/uvicorn with Flask/waitress**

`requirements.txt` currently contains (exact):
```
fastapi==0.104.1
uvicorn==0.24.0
requests==2.31.0
python-dotenv==1.0.0
httpx>=0.28.1
sumup
```

Replace with:
```
flask==3.1.3
waitress==3.0.2
requests==2.31.0
python-dotenv==1.0.0
httpx>=0.28.1
sumup
```

- [ ] **Step 2: Install the new deps in the venv**

Run: `source venv/bin/activate && pip install -r requirements.txt`
Expected: installs cleanly (flask 3.1.3, waitress 3.0.2 already present)

Run: `source venv/bin/activate && python -c "import flask, waitress; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: swap fastapi/uvicorn for flask/waitress"
```

---

### Task 3: Failing Flask endpoint tests (red)

**Files:**
- Create: `tests/test_kassafu_endpoints.py`

- [ ] **Step 1: Write the endpoint contract tests**

Create `tests/test_kassafu_endpoints.py`:

```python
import asyncio
import os
import tempfile
import unittest

import kassafu
from kassafu import bridge

SUMUP_CONFIG = {
    "sumup": {
        "api_key": "sup_sk_test",
        "merchant_code": "M1234567",
        "reader_id": "rdr_test123",
    }
}


def _reset_state():
    kassafu.config = {}
    kassafu.terminal = None
    kassafu.TERMINAL_TYPE = "sumup"
    kassafu.active_payment = False
    kassafu.payment_queue = bridge.call_in_loop(asyncio.Queue)


class FakeTerminal:
    """Async terminal stand-in so routes are exercised without live I/O."""

    def __init__(self):
        self.is_ready = True
        self.reader_id = "rdr_test123"
        self.current_order_id = None
        self.current_transaction_id = None
        self.current_amount_cents = None
        self.current_currency = None
        self.current_status = None
        self.current_card_scheme = None
        self.current_card_last_4 = None

    async def process_payment(self, order_id, amount_cents, currency="EUR"):
        return {"success": True, "status": "pending", "order_id": order_id, "error_code": 0}

    async def cancel_payment(self, order_id):
        return {"success": True}

    async def clear_display(self):
        pass

    async def check_status(self):
        return {"status": "online", "reader_id": self.reader_id, "error_code": 0}

    async def get_transaction_status(self, transaction_id):
        return "PENDING"

    def get_config(self):
        return {
            "app": {"mode": "test"},
            "sumup": {"merchant_code": "M1234567", "reader_id": self.reader_id},
        }


class PayEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_missing_required_field_returns_400(self):
        r = self.client.post("/pay", json={"order_id": "O1"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["detail"], "Missing field: amount_cents")

    def test_terminal_not_ready_returns_503(self):
        r = self.client.post(
            "/pay", json={"order_id": "O1", "amount_cents": 100, "currency": "EUR"}
        )
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["detail"], "Terminal not ready")

    def test_pay_success(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.post(
            "/pay", json={"order_id": "O1", "amount_cents": 100, "currency": "EUR"}
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["order_id"], "O1")

    def test_pay_queued_when_active_payment(self):
        kassafu.terminal = FakeTerminal()
        kassafu.active_payment = True
        r = self.client.post(
            "/pay", json={"order_id": "O1", "amount_cents": 100, "currency": "EUR"}
        )
        self.assertEqual(r.status_code, 202)
        body = r.get_json()
        self.assertEqual(body["success"], False)
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["error_code"], 108012)


class PaymentStatusEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_no_terminal_returns_503(self):
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["error_code"], 108008)

    def test_idle_when_no_active_payment(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "idle")
        self.assertEqual(body["error_code"], 0)

    def test_completed_payment(self):
        term = FakeTerminal()
        term.current_order_id = "O1"
        term.current_status = "paid"
        term.current_amount_cents = 100
        term.current_currency = "EUR"
        term.current_card_scheme = "visa"
        term.current_card_last_4 = "1234"
        kassafu.terminal = term
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "paid")
        self.assertEqual(body["order_id"], "O1")
        self.assertEqual(body["error_code"], 0)

    def test_not_found_order(self):
        term = FakeTerminal()
        term.current_order_id = "O2"
        kassafu.terminal = term
        r = self.client.get("/payment/status?order_id=O1")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "not_found")
        self.assertEqual(body["error_code"], 108002)


class CancelEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_delete_cancel_success(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.delete("/payment/cancel?order_id=O1")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])

    def test_get_cancel_also_works(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.get("/payment/cancel?order_id=O1")
        self.assertEqual(r.status_code, 200)

    def test_missing_order_id_returns_400(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.delete("/payment/cancel")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["detail"], "Missing order_id query parameter")


class ConfigEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_get_config_without_terminal(self):
        r = self.client.get("/config")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["app"]["mode"], "sumup")

    def test_post_config_applies_sumup_config(self):
        r = self.client.post("/config", json=SUMUP_CONFIG)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["terminal_type"], "sumup")
        self.assertIsNotNone(kassafu.terminal)

    def test_post_config_rejected_during_active_payment(self):
        kassafu.active_payment = True
        r = self.client.post("/config", json=SUMUP_CONFIG)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error_code"], 108012)

    def test_post_config_non_dict_returns_400(self):
        r = self.client.post("/config", json="nope")
        self.assertEqual(r.status_code, 400)
        self.assertIn("JSON object", r.get_json()["detail"])


class HealthAndMiscEndpointTests(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self.client = kassafu.app.test_client()

    def test_health_unconfigured(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "unconfigured")
        self.assertFalse(body["terminal_ready"])
        self.assertIsNone(body["mode"])

    def test_reader_status_no_terminal(self):
        r = self.client.get("/reader/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["error_code"], 108010)

    def test_reader_status_online(self):
        kassafu.terminal = FakeTerminal()
        r = self.client.get("/reader/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "online")

    def test_payment_history_reads_log(self):
        kassafu.terminal = FakeTerminal()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write('{"order_id": "O1"}\n{"order_id": "O2"}\n')
            log_path = f.name
        try:
            original = kassafu.TRANSACTION_LOG
            kassafu.TRANSACTION_LOG = log_path
            try:
                r = self.client.get("/payment/history?limit=10")
                self.assertEqual(r.status_code, 200)
                items = r.get_json()["items"]
                self.assertEqual([i["order_id"] for i in items], ["O2", "O1"])
            finally:
                kassafu.TRANSACTION_LOG = original
        finally:
            os.unlink(log_path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails (red)**

Run: `source venv/bin/activate && python -m unittest tests.test_kassafu_endpoints -v`
Expected: `AttributeError: 'FastAPI' object has no attribute 'test_client'` (or similar) — every `setUp` fails because `kassafu.app` is still FastAPI.

- [ ] **Step 3: Commit**

```bash
git add tests/test_kassafu_endpoints.py
git commit -m "test: add Flask endpoint contract tests (red)"
```

---

### Task 4: Convert `kassafu.py` to Flask + waitress

**Files:**
- Modify: `kassafu.py` (see exact regions below; line numbers refer to the pre-change file)

Work through Steps 1–10. After each step run the full suite:
`source venv/bin/activate && python -m unittest discover -s tests -v`
Intermediate reds are fine until Step 10; the file only reaches a green state once all steps are done.

- [ ] **Step 1: Replace imports**

Current (lines 26–38):
```python
import asyncio
import json
import sys
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

from sumup_terminal import SumUpTerminal
from mypos_terminal import MyPOSTerminal
```

Replace with:
```python
import asyncio
import json
import sys
import logging
from typing import Optional

from flask import Flask, request
from waitress import serve

from asyncio_bridge import bridge
from sumup_terminal import SumUpTerminal
from mypos_terminal import MyPOSTerminal
```

- [ ] **Step 2: Change the payment queue global**

Current (lines 74–76):
```python
terminal: Optional[object] = None
payment_queue = asyncio.Queue()
active_payment = False
```

Replace with:
```python
terminal: Optional[object] = None
payment_queue = None
active_payment = False
```

- [ ] **Step 3: Replace `lifespan` + FastAPI app with Flask app + startup**

Current (lines 154–178):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global terminal, TERMINAL_TYPE

    if any(name in config for name in TERMINAL_CLASSES):
        TERMINAL_TYPE = _resolve_terminal_type(config)
        logger.info(f"KassaFu starting with terminal type '{TERMINAL_TYPE}' on port {PORT}")

        candidate = _get_terminal_class(TERMINAL_TYPE)()
        if not candidate.init(config):
            logger.error(f"Failed to initialize {TERMINAL_TYPE} terminal - continuing unconfigured")
        else:
            terminal = candidate
            await _maybe_discover(terminal, TERMINAL_TYPE)
    else:
        logger.info("KassaFu started without configuration - waiting for POST /config")

    asyncio.create_task(process_payment_queue())

    yield

    logger.info("KassaFu shutting down")


app = FastAPI(lifespan=lifespan)
```

Replace with:
```python
app = Flask(__name__)


def _startup():
    """Initialize the terminal, payment queue and queue consumer.

    Runs once before the WSGI server starts serving. Terminal init and the
    queue consumer run on the bridge loop, exactly as they did on FastAPI's
    single event loop.
    """
    global terminal, TERMINAL_TYPE, payment_queue

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


def _is_active_payment() -> bool:
    """True while the queue consumer is processing a payment (loop thread)."""
    return active_payment
```

- [ ] **Step 4: Convert `/pay` to a sync handler over `_handle_pay`**

Current (lines 202–234):
```python
@app.post("/pay")
async def pay(payment_data: dict):
    """Accept payment request from POS"""
    global active_payment, terminal

    required = ['order_id', 'amount_cents', 'currency']
    for field in required:
        if field not in payment_data:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")

    if not terminal or not terminal.is_ready:
        raise HTTPException(status_code=503, detail="Terminal not ready")

    if active_payment:
        logger.info(f"Queueing payment for {payment_data['order_id']}")
        await payment_queue.put(payment_data)
        return JSONResponse(
            status_code=202,
            content={
                "success": False,
                "status": "queued",
                "message": "Payment in progress, request queued",
                "error_code": 108012
            }
        )

    result = await terminal.process_payment(
        order_id=payment_data['order_id'],
        amount_cents=payment_data['amount_cents'],
        currency=payment_data.get('currency', 'EUR')
    )

    return result
```

Replace with:
```python
async def _handle_pay(payment_data: dict):
    """Async payment handling: queue behind an active payment or process now.

    Runs on the bridge loop so active_payment and payment_queue stay confined
    to the loop thread, exactly as they were under FastAPI.
    """
    global active_payment, terminal

    if active_payment:
        logger.info(f"Queueing payment for {payment_data['order_id']}")
        await payment_queue.put(payment_data)
        return (
            {
                "success": False,
                "status": "queued",
                "message": "Payment in progress, request queued",
                "error_code": 108012,
            },
            202,
        )

    result = await terminal.process_payment(
        order_id=payment_data['order_id'],
        amount_cents=payment_data['amount_cents'],
        currency=payment_data.get('currency', 'EUR'),
    )
    return result, 200


@app.post("/pay")
def pay():
    """Accept payment request from POS"""
    payment_data = request.get_json(silent=True)
    if not isinstance(payment_data, dict):
        payment_data = {}

    required = ['order_id', 'amount_cents', 'currency']
    for field in required:
        if field not in payment_data:
            return {"detail": f"Missing field: {field}"}, 400

    if not terminal or not terminal.is_ready:
        return {"detail": "Terminal not ready"}, 503

    return bridge.run(_handle_pay(payment_data))
```

- [ ] **Step 5: Convert `/payment/history`**

Current (lines 240–262):
```python
@app.get("/payment/history")
async def get_payment_history(limit: int = 20):
    """Return the last N transactions from the transaction log"""
    try:
        with open(TRANSACTION_LOG, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {"items": [], "error_code": 0}

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entries.append(entry)
            if len(entries) >= limit:
                break
        except json.JSONDecodeError:
            continue

    return {"items": entries, "error_code": 0}
```

Replace with:
```python
@app.get("/payment/history")
def get_payment_history():
    """Return the last N transactions from the transaction log"""
    limit = request.args.get("limit", default=20, type=int)

    try:
        with open(TRANSACTION_LOG, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return {"items": [], "error_code": 0}

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entries.append(entry)
            if len(entries) >= limit:
                break
        except json.JSONDecodeError:
            continue

    return {"items": entries, "error_code": 0}
```

- [ ] **Step 6: Convert `/payment/status` to `_payment_status` + sync handler**

Current (lines 265–354) is the full async `get_payment_status`. Replace it with:
```python
async def _payment_status(order_id: str):
    """Get payment status for an order (runs on the bridge loop)."""
    global terminal

    if not terminal:
        return {"status": "error", "message": "Terminal not ready", "error_code": 108008}, 503

    if not terminal.current_order_id:
        return {
            "status": "idle",
            "message": "No active payment",
            "error_code": 0,
        }, 200

    if terminal.current_order_id != order_id:
        return {
            "status": "not_found",
            "message": f"No payment found for order {order_id}",
            "error_code": 108002,
        }, 200

    if terminal.current_status in ["paid", "failed", "cancelled"]:
        return {
            "status": terminal.current_status,
            "order_id": terminal.current_order_id,
            "amount": terminal.current_amount_cents / 100,
            "currency": terminal.current_currency,
            "card_scheme": terminal.current_card_scheme,
            "card_last_4": terminal.current_card_last_4,
            "message": "Payment completed" if terminal.current_status == "paid" else "Payment failed",
            "error_code": 0 if terminal.current_status == "paid" else 108009,
        }, 200

    if terminal.current_transaction_id:
        transaction_status = await terminal.get_transaction_status(terminal.current_transaction_id)

        if transaction_status == "SUCCESSFUL":
            terminal.current_status = "paid"
            terminal._log_status_update(order_id, terminal.current_transaction_id or "", "paid")
            logger.info(f"Payment for order {order_id} completed")
            return {
                "status": "paid",
                "order_id": terminal.current_order_id,
                "amount": terminal.current_amount_cents / 100,
                "currency": terminal.current_currency,
                "card_scheme": terminal.current_card_scheme,
                "card_last_4": terminal.current_card_last_4,
                "message": "Payment completed successfully",
                "error_code": 0,
            }, 200

        elif transaction_status in ["FAILED", "CANCELLED"]:
            terminal.current_status = "failed"
            terminal._log_status_update(order_id, terminal.current_transaction_id or "", "failed")

            error_message = "Card rejected - please try another payment method"
            logger.warning(f"Payment for order {order_id} {transaction_status}")

            return {
                "status": "failed",
                "order_id": terminal.current_order_id,
                "amount": terminal.current_amount_cents / 100,
                "currency": terminal.current_currency,
                "message": error_message,
                "error_code": 108009,
            }, 200

        else:
            return {
                "status": "pending",
                "order_id": terminal.current_order_id,
                "amount": terminal.current_amount_cents / 100,
                "currency": terminal.current_currency,
                "error_code": 0,
            }, 200

    return {
        "status": "pending",
        "order_id": terminal.current_order_id,
        "amount": terminal.current_amount_cents / 100,
        "currency": terminal.current_currency,
        "error_code": 0,
    }, 200


@app.get("/payment/status")
def get_payment_status():
    """
    Get payment status for an order.
    POS calls this every few seconds to check if payment is complete.
    """
    order_id = request.args.get("order_id", "")
    return bridge.run(_payment_status(order_id))
```

- [ ] **Step 7: Convert `/payment/cancel` to `_cancel_payment` + sync handler**

Current (lines 357–376):
```python
@app.api_route("/payment/cancel", methods=["GET", "DELETE"])
async def cancel_payment(order_id: str):
    global terminal

    if not terminal:
        return JSONResponse(status_code=503, content={"status": "error", "message": "Terminal not ready", "error_code": 108008})

    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order_id query parameter")

    result = await terminal.cancel_payment(order_id)

    if terminal and hasattr(terminal, 'clear_display'):
        await terminal.clear_display()

    if not result.get("success"):
        return JSONResponse(status_code=404 if result.get("status") == "not_found" else 200, content=result)

    logger.info(f"Payment for order {order_id} cancelled via API")
    return result
```

Replace with:
```python
async def _cancel_payment(order_id: str):
    """Cancel an active payment (runs on the bridge loop)."""
    global terminal

    if not terminal:
        return {"status": "error", "message": "Terminal not ready", "error_code": 108008}, 503

    if not order_id:
        return {"detail": "Missing order_id query parameter"}, 400

    result = await terminal.cancel_payment(order_id)

    if terminal and hasattr(terminal, 'clear_display'):
        await terminal.clear_display()

    if not result.get("success"):
        return result, (404 if result.get("status") == "not_found" else 200)

    logger.info(f"Payment for order {order_id} cancelled via API")
    return result, 200


@app.route("/payment/cancel", methods=["GET", "DELETE"])
def cancel_payment():
    order_id = request.args.get("order_id", "")
    return bridge.run(_cancel_payment(order_id))
```

- [ ] **Step 8: Convert `/health` and `/reader/status`**

Current `/health` (lines 379–395):
```python
@app.get("/health")
async def health():
    """Health check endpoint"""
    if not terminal:
        return {
            "status": "unconfigured",
            "mode": None,
            "terminal_ready": False,
            "error_code": 0
        }

    return {
        "status": "healthy",
        "mode": TERMINAL_TYPE,
        "terminal_ready": terminal.is_ready,
        "error_code": 0
    }
```

Replace with:
```python
@app.get("/health")
def health():
    """Health check endpoint"""
    if not terminal:
        return {
            "status": "unconfigured",
            "mode": None,
            "terminal_ready": False,
            "error_code": 0
        }

    return {
        "status": "healthy",
        "mode": TERMINAL_TYPE,
        "terminal_ready": terminal.is_ready,
        "error_code": 0
    }
```

Current `/reader/status` (lines 398–417):
```python
@app.get("/reader/status")
async def get_reader_status():
    """Check if the terminal is online and ready"""
    if not terminal:
        return {
            "status": "error",
            "message": "No terminal configured",
            "error_code": 108010
        }

    reader_id = getattr(terminal, 'reader_id', None) or getattr(terminal, 'terminal_id', None)
    if not reader_id:
        return {
            "status": "error",
            "message": "No terminal configured",
            "error_code": 108010
        }

    status = await terminal.check_status()
    return status
```

Replace with:
```python
@app.get("/reader/status")
def get_reader_status():
    """Check if the terminal is online and ready"""
    if not terminal:
        return {
            "status": "error",
            "message": "No terminal configured",
            "error_code": 108010
        }

    reader_id = getattr(terminal, 'reader_id', None) or getattr(terminal, 'terminal_id', None)
    if not reader_id:
        return {
            "status": "error",
            "message": "No terminal configured",
            "error_code": 108010
        }

    return bridge.run(terminal.check_status())
```

- [ ] **Step 9: Convert `/config` GET and POST**

Current (lines 420–452):
```python
@app.get("/config")
async def get_config():
    """Return the current runtime configuration (API key excluded)"""
    if not terminal:
        return {"app": {"mode": TERMINAL_TYPE}}
    cfg = terminal.get_config()
    cfg["app"]["mode"] = TERMINAL_TYPE
    return cfg


@app.post("/config")
async def update_config(new_config: dict):
    """Replace runtime configuration and hot-swap the terminal (in-memory only)"""
    if active_payment:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "message": "Payment in progress, configuration rejected",
                "error_code": 108012,
            },
        )

    ok, detail = _apply_runtime_config(new_config)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)

    try:
        await _maybe_discover(terminal, TERMINAL_TYPE)
    except Exception as exc:  # discovery problems must not fail an applied config
        logger.warning(f"Post-swap discovery failed: {exc}")

    return {"success": True, "terminal_type": detail}
```

Replace with:
```python
@app.get("/config")
def get_config():
    """Return the current runtime configuration (API key excluded)"""
    if not terminal:
        return {"app": {"mode": TERMINAL_TYPE}}
    cfg = terminal.get_config()
    cfg["app"]["mode"] = TERMINAL_TYPE
    return cfg


@app.post("/config")
def update_config():
    """Replace runtime configuration and hot-swap the terminal (in-memory only)"""
    if bridge.call_in_loop(_is_active_payment):
        return (
            {
                "success": False,
                "message": "Payment in progress, configuration rejected",
                "error_code": 108012,
            },
            409,
        )

    new_config = request.get_json(silent=True)

    ok, detail = bridge.call_in_loop(_apply_runtime_config, new_config)
    if not ok:
        return {"detail": detail}, 400

    try:
        bridge.run(_maybe_discover(terminal, TERMINAL_TYPE))
    except Exception as exc:  # discovery problems must not fail an applied config
        logger.warning(f"Post-swap discovery failed: {exc}")

    return {"success": True, "terminal_type": detail}
```

- [ ] **Step 10: Convert the `__main__` server entry point**

Current (lines 455–479), specifically:
```python
    if args.server:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    else:
        print("Usage: python3 kassafu.py --server")
        print("Optional: --config /path/to/config.json")
        print("Optional: --port 8888")
```

Replace with:
```python
    if args.server:
        _startup()
        serve(app, host="127.0.0.1", port=port)
    else:
        print("Usage: python3 kassafu.py --server")
        print("Optional: --config /path/to/config.json")
        print("Optional: --port 8888")
```

- [ ] **Step 11: Run full suite (should be green now)**

Run: `source venv/bin/activate && python -m unittest discover -s tests -v`
Expected: 46 existing tests + 4 bridge tests + 19 endpoint tests all pass.

Also verify no leftover FastAPI imports:
Run: `rg -n "fastapi|uvicorn|HTTPException|JSONResponse|asynccontextmanager" kassafu.py`
Expected: no matches.

- [ ] **Step 12: Smoke-test the real server**

Start the server with the disabled (network-free) config from the repo:

```bash
source venv/bin/activate
python kassafu.py --server --config config.sumup.json >/tmp/opencode/kassafu_flask.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8888/health
curl -s -X POST http://127.0.0.1:8888/pay -H 'Content-Type: application/json' -d '{"order_id":"smoke1","amount_cents":100,"currency":"EUR"}' | head -c 300
kill %1
```

Expected: `/health` → `200`; `/pay` → `503` JSON `{"detail":"Terminal not ready"}` (the sandbox reader config should not connect during smoke; if it does reach SumUp and returns a payment result, also acceptable). Verify the process exits.

- [ ] **Step 13: Commit**

```bash
git add kassafu.py
git commit -m "feat: migrate kassafu server from FastAPI to Flask + waitress"
```

---

### Task 5: Remove ccv.py, update deployment + docs

**Files:**
- Delete: `ccv.py`
- Modify: `install.sh`
- Modify: `create_deb`
- Modify: `API.md`
- Modify: `README.md`

- [ ] **Step 1: Delete `ccv.py`**

Run: `git rm ccv.py`
Expected: `rm 'ccv.py'`

- [ ] **Step 2: Remove ccv from `install.sh`**

Current (line 27):
```bash
cp "$SCRIPT_DIR/ccv.py" "$INSTALL_DIR/"
```

Remove that entire line.

- [ ] **Step 3: Remove ccv from `create_deb`**

Current:
```bash
cp kassafu.py mypos_terminal.py mypos_gateway.py sumup_terminal.py ccv.py "$ROOT/"
```
becomes:
```bash
cp kassafu.py mypos_terminal.py mypos_gateway.py sumup_terminal.py "$ROOT/"
```

and:
```bash
for f in kassafu.py mypos_terminal.py mypos_gateway.py sumup_terminal.py ccv.py install.sh; do
```
becomes:
```bash
for f in kassafu.py mypos_terminal.py mypos_gateway.py sumup_terminal.py install.sh; do
```

- [ ] **Step 4: Update `API.md` tech bullets**

Line 4: `It exposes a REST API built with FastAPI to process payments, monitor terminal status, and manage configuration.`
→ `It exposes a REST API built with Flask to process payments, monitor terminal status, and manage configuration.`

Line 33: `* FastAPI-powered REST API`
→ `* Flask-powered REST API`

Lines 47–48:
```
* FastAPI
* Uvicorn
```
→
```
* Flask
* Waitress
```

- [ ] **Step 5: Add a CCV/terminal-extension note to `README.md`**

After the "Supported payment terminals" table (after line 104, which ends with the myPOS row), add:

```markdown

> Note: An earlier CCV Cloud Connect handler (`ccv.py`) was an unused shell and
> has been removed. To add a terminal back: implement one module exposing the
> terminal interface (`init`, `process_payment`, `check_status`, `get_config`,
> `is_ready`, ...) and add a `TERMINAL_CLASSES` entry keyed by its config
> section name; the server auto-detects it from the pushed config.
```

- [ ] **Step 6: Verify deployment/service files need no edits**

Run: `rg -n "uvicorn|fastapi|ccv" service/ setup.sh run.sh .env.example`
Expected: no matches.

- [ ] **Step 7: Final full test suite**

Run: `source venv/bin/activate && python -m unittest discover -s tests -v`
Expected: all tests pass (46 existing + 4 bridge + 19 endpoint).

- [ ] **Step 8: Commit**

```bash
git add -u
git add README.md API.md create_deb install.sh
git commit -m "chore: remove unused ccv.py shell, update docs for Flask stack"
```

---

## Self-review notes

- **Spec coverage:** each spec decision maps to a task — bridge (T1), deps (T2), endpoint contract preserved via tests (T3), Flask conversion of every route + lifecycle (T4), ccv removal + docs (T5). Manual test scripts and `service/` unit were confirmed unchanged.
- **Placeholder scan:** all steps carry complete code and commands; no TBD/TODO.
- **Type consistency:** bridge API (`run`, `create_task`, `call_in_loop`) used identically in T1 tests and T4; helper coroutines `_handle_pay`, `_payment_status`, `_cancel_payment`, `_is_active_payment` are defined in the same task that uses them; `payment_queue` is `None` initially and only set in `_startup`/tests.