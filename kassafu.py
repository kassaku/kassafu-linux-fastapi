#!/usr/bin/env python3
"""
KassaFu - Payment bridge between POS and SumUp Solo terminal

Copyright (c) 2026 Houkes Horeca Applications

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import asyncio
import json
import sys
import logging
from typing import Optional

import httpx

from flask import Flask, request
from werkzeug.exceptions import HTTPException
from waitress import serve

from asyncio_bridge import bridge
from sumup_terminal import SumUpTerminal
from mypos_terminal import MyPOSTerminal
from encrypt_partner import (
    PARTNER_URL_DEFAULT,
    PartnerConfigError,
    decrypt_blob,
)

TERMINAL_CLASSES = {
    "sumup": SumUpTerminal,
    "mypos": MyPOSTerminal,
}

def load_config_from_file(config_path: str) -> dict:
    """Load configuration from JSON file"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded configuration from {config_path}")
        return config
    except FileNotFoundError:
        logger.error(f"Config file {config_path} not found")
        logger.error(f"   Please create {config_path} with your terminal credentials")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {config_path}: {e}")
        sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('kassafu.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

config = {}

PORT = 8888

terminal: Optional[object] = None
payment_queue = None
active_payment = False

KASSAFU_INTERFACE = {}


def _get_terminal_class(terminal_type: str):
    t = terminal_type.lower()
    cls = TERMINAL_CLASSES.get(t)
    if not cls:
        logger.warning(f"Unknown terminal type '{terminal_type}', falling back to sumup")
        cls = SumUpTerminal
    return cls


def _resolve_terminal_type(cfg: dict) -> str:
    terminal_type = cfg.get("app", {}).get("terminal_type")
    if terminal_type:
        t = str(terminal_type).lower()
        if t in TERMINAL_CLASSES:
            return t
        logger.warning(f"Unknown terminal type '{terminal_type}', falling back to section detection")

    has_sumup = "sumup" in cfg
    has_mypos = "mypos" in cfg

    if has_mypos and not has_sumup:
        return "mypos"

    if has_sumup and has_mypos:
        logger.warning("Both 'sumup' and 'mypos' sections configured, defaulting to sumup")
    elif not has_sumup:
        logger.warning("No 'sumup' or 'mypos' section found, defaulting to sumup")
    return "sumup"


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


def _apply_runtime_config(new_config: dict):
    """Replace runtime config and hot-swap the terminal implementation.

    Returns (success, detail): detail is the active terminal type on success,
    an error message on failure. Globals are only mutated on success.
    """
    global config, terminal, TERMINAL_TYPE

    if not isinstance(new_config, dict):
        return False, "Configuration must be a JSON object"

    term_type = _resolve_terminal_type(new_config)
    term_cls = _get_terminal_class(term_type)

    candidate = term_cls()
    if not candidate.init(new_config):
        detail = f"Failed to initialize {term_type} terminal with supplied configuration"
        logger.error(detail)
        return False, detail

    config = new_config
    TERMINAL_TYPE = term_type
    terminal = candidate

    logger.info(f"Terminal switched to '{term_type}' via runtime configuration")
    return True, term_type


async def _apply_config_atomic(new_config: dict):
    """Check for an active payment and hot-swap the terminal in one loop turn.

    Kept on the bridge loop with no await between the guard and the swap so a
    concurrent payment cannot interleave the two, matching FastAPI's atomicity.
    """
    if active_payment:
        return {
            "success": False,
            "message": "Payment in progress, configuration rejected",
            "error_code": 108012,
        }, 409

    ok, detail = _apply_runtime_config(new_config)
    if not ok:
        return {"detail": detail}, 400

    return {"success": True, "terminal_type": detail}, 200


TERMINAL_TYPE = "sumup"


async def _maybe_discover(term, terminal_type: str):
    """Run reader/terminal discovery when supported and no id is configured yet."""
    if hasattr(term, 'discover_reader') and hasattr(term, 'reader_id'):
        if not term.reader_id:
            logger.info("No reader ID provided, discovering...")
            await term.discover_reader()
            if not term.reader_id:
                logger.warning(f"No {terminal_type} terminal found. Please check your configuration.")
    elif hasattr(term, 'terminal_id'):
        if not term.terminal_id:
            logger.info("No terminal ID provided, discovering...")
            await term.discover_reader()


app = Flask(__name__)
app.json.ensure_ascii = False


@app.errorhandler(Exception)
def _handle_unhandled_exception(exc):
    if isinstance(exc, HTTPException):
        return exc
    logger.exception("Unhandled exception serving request")
    return {"detail": "Internal server error"}, 500


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


async def process_payment_queue():
    """Process queued payments one at a time"""
    global active_payment, terminal

    while True:
        payment_data = await payment_queue.get()
        active_payment = True
        try:
            result = await terminal.process_payment(
                order_id=payment_data['order_id'],
                amount_cents=payment_data['amount_cents'],
                currency=payment_data.get('currency', 'EUR')
            )
            logger.info(f"Payment result: {result}")
        except Exception as e:
            logger.error(f"Error processing queued payment: {e}")
        finally:
            active_payment = False
            payment_queue.task_done()


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


TRANSACTION_LOG = "transactions.log"


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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="KassaFu Payment Bridge")
    parser.add_argument("--server", action="store_true", help="Run in server mode")
    parser.add_argument("--config", type=str, help="Configuration file path (optional manual seed)")
    parser.add_argument("--port", type=int, help="Override port (default: 8888)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose HTTP logging (masked secrets)")
    parser.add_argument("--key", type=str, help="Partner encryption key (terminal testing)")
    args = parser.parse_args()

    if args.debug:
        import os
        os.environ["KASSAFU_HTTP_DEBUG"] = "1"

    if args.key:
        KASSAFU_PARTNER_KEY = args.key

    if args.config:
        config = load_config_from_file(args.config)

    port = args.port if args.port else 8888

    if args.server:
        _startup()
        serve(app, host="127.0.0.1", port=port)
    else:
        print("Usage: python3 kassafu.py --server")
        print("Optional: --config /path/to/config.json")
        print("Optional: --port 8888")
