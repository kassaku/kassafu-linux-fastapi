# Flask Migration Design

Date: 2026-09-13
Status: Approved

## Goal

Replace FastAPI/uvicorn with Flask for the KassaFu payment bridge server while
keeping the HTTP contract identical and leaving the async terminal/gateway
stack untouched.

## Problem

`kassafu.py` is FastAPI/uvicorn based. The terminal stack
(`sumup_terminal.py`, `mypos_terminal.py`, `mypos_gateway.py`, the async
`sumup` SDK) is deeply async (httpx.AsyncClient, asyncio queues and tasks,
`await`-based payment flows). A naive Flask rewrite would either require
porting all of that tested async code to `requests`/threading, or losing the
queue-based payment serialization behavior the POS relies on.

Additionally `ccv.py` is an orphaned, non-working FastAPI shell for a separate
CCV terminal: nothing deploys it, no config file has a `ccv` section (so the
terminal never initializes), and its default port 8080 collides on the target
machine. It is an empty shell and out of scope for now.

## User-approved decisions

1. Migrate `kassafu.py` to Flask; `ccv.py` is removed for now.
2. Keep the terminal/gateway async internals unchanged and bridge them from
   the sync Flask request layer (no rewrite to `requests`/threading).
3. Serve from a production WSGI server (`waitress`) instead of uvicorn.
4. Preserve the exact HTTP contract: paths, JSON field names, status codes
   (400 missing fields, 202 queued, 409 config during payment, 503 terminal
   not ready), and `error_code` values.
5. Allow adding a terminal such as CCV back later with a small change; the
   extension point is `TERMINAL_CLASSES` plus the async bridge.
6. Existing tests stay green; add Flask endpoint tests written before the
   conversion (TDD).

## Design

### `asyncio_bridge.py` (new)

A small module owning a single background asyncio event loop:

- A daemon thread runs `asyncio.new_event_loop()` + `loop.run_forever()`.
- `run(coro) -> result`: submit to the loop via
  `asyncio.run_coroutine_threadsafe(coro, loop).result()`; blocks the calling
  Flask thread until finished. Used by every endpoint that needs `await`.
- `create_task(coro)`: schedule a coroutine on the loop without waiting. Used
  to start the payment-queue consumer at startup.
- `ensure_future`/task accessors only run coroutines in the loop thread, so
  the async domain stays single-threaded as today.

The module imports cleanly with no side effects (loop thread starts lazily on
first use or at server start, not at import), so tests importing `kassafu`
under unittest keep working.

### `kassafu.py` conversion

- Replace FastAPI imports with Flask: `app = Flask(__name__)`.
- All routes become synchronous `def` handlers:
  - JSON bodies via `request.get_json()`
  - query params via `request.args`
  - path params via `/<string:...>` placeholders
  - error responses returned as `jsonify(...), <code>` tuples with the same
    JSON shapes and `error_code` values as FastAPI produced.
- Startup (terminal init, discovery, `process_payment_queue` task) moves from
  FastAPI `lifespan` into the `--server` entry point, executed before the
  server starts. `--config`, `--port`, `--debug` flags keep working.
- The `/pay` branch that reads/updates `active_payment` and enqueues into
  `payment_queue` moves into a coroutine run through the bridge, so all
  mutations of that shared state happen on the loop thread (same concurrency
  semantics as FastAPI's single event loop).
- `process_payment_queue()` (replaces `asyncio.create_task` at startup) is
  scheduled via `bridge.create_task`; the queue consumer itself is unchanged.
  For testability, the queue is created lazily on the loop thread rather than
  at module import time.
- Sync-only endpoints (`/health`, `/payment/history`, `GET /config`) read
  state directly; simple attribute reads of terminal state are GIL-safe.

### Server and deployment

- `requirements.txt`: remove `fastapi==0.104.1` and `uvicorn==0.24.0`; add
  `flask` and `waitress`. Keep `requests`, `python-dotenv`, `httpx`, `sumup`.
- `kassafu.py --server` starts `waitress.serve(app, host="127.0.0.1",
  port=port)`.
- Update `install.sh`, `create_deb`, `service/kassafu.service`, `setup.sh`,
  `run.sh` for the dependency change. The systemd service command
  (`kassafu.py --server`) is unchanged.

### ccv.py removal

- Delete `ccv.py` and its references in `install.sh`/`create_deb`.
- Document in `README.md`/`API.md` that CCV support was an unused shell and
  was removed, and that adding a terminal back means: one module implementing
  the terminal interface + a `TERMINAL_CLASSES` entry (the existing
  auto-detection registry already picks new sections up).

## Testing

- Existing suites stay green: `tests/test_mypos_gateway.py`,
  `tests/test_mypos_terminal.py` (async, untouched),
  `tests/test_kassafu_config.py` (imports `kassafu`; still works under Flask).
- Add Flask endpoint tests in `tests/test_kassafu_endpoints.py` (stdlib
  unittest, `app.test_client()`), written first:
  - `/health` unconfigured shape
  - `/pay` missing fields → 400
  - `/pay` terminal not ready → 503
  - `/pay` queued → 202 with `error_code` 108012
  - `/payment/status` idle / completed / not found shapes
  - `/payment/cancel` via GET and DELETE
  - `/config` GET shape and POST apply/hot-swap (reusing
    `_apply_runtime_config` test fixtures)
  - `/payment/history` reads `transactions.log`
- Manual scripts (`test_reader_status_*.py`, `test_real_payment.py`) talk to
  the HTTP API only and keep working unchanged.

## Files changed

- new: `asyncio_bridge.py`
- modified: `kassafu.py` (Flask conversion)
- modified: `requirements.txt`
- modified: `tests/test_kassafu_config.py`
- new: `tests/test_kassafu_endpoints.py`
- modified: `install.sh`, `create_deb`, `service/kassafu.service`, `setup.sh`,
  `run.sh`, `README.md`/`API.md`
- deleted: `ccv.py`

Out of scope: porting terminal internals off asyncio, persistence,
multi-terminal concurrency, anything for the CCV terminal (future work).