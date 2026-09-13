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

    def test_call_in_loop_runs_sync_callable_on_bridge_loop(self):
        async def capture_loop():
            return asyncio.get_running_loop()

        bridge_loop = bridge.run(capture_loop())
        loop_in_call = bridge.call_in_loop(asyncio.get_running_loop)
        self.assertIs(loop_in_call, bridge_loop)

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