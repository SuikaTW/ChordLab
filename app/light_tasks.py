"""Bounded, independent pool for short media jobs, never the analysis queue."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading


class PoolBusy(RuntimeError):
    pass


class LightTaskPool:
    def __init__(self, workers=2, capacity=8):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="chordlab-media")
        self.capacity = threading.BoundedSemaphore(capacity)

    async def run(self, function, *args):
        if not self.capacity.acquire(blocking=False):
            raise PoolBusy("播放準備繁忙，請稍後再試")
        try:
            future = self.executor.submit(function, *args)
        except BaseException:
            self.capacity.release()
            raise
        future.add_done_callback(lambda _: self.capacity.release())
        # Keep capacity until work really finishes, including cancelled requests.
        return await asyncio.shield(asyncio.wrap_future(future))
