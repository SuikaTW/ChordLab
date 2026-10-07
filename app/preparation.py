"""Bounded download prefetch; CPU analysis retains its independent FIFO queue."""
from concurrent.futures import ThreadPoolExecutor
import threading


class DownloadPreparation:
    def __init__(self, workers=2, capacity=8):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="chordlab-download")
        self.capacity = capacity
        self.lock = threading.Lock()
        self.futures = {}

    def submit(self, key, function, *args):
        with self.lock:
            if key in self.futures or len(self.futures) >= self.capacity:
                return False
            self.futures[key] = self.executor.submit(function, *args)
            return True

    def take(self, key):
        with self.lock:
            return self.futures.pop(key, None)

    def cancel(self, key):
        with self.lock:
            future = self.futures.pop(key, None)
        return future.cancel() if future is not None else False
