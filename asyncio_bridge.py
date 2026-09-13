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