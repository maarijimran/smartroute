"""Exact-match response cache (research guide 4.12).

In-memory and per process: answers never touch the database or leave the host.
Keys include the user id and privacy mode, so one user never receives another
user's cached answer. Confidential requests are never cached (see pipeline).
"""

import threading
import time
from collections import OrderedDict

MAX_ENTRIES = 2000


class ResponseCache:
    def __init__(self):
        self._data: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, value = item
            if expires < time.time():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def put(self, key: str, value: dict, ttl_s: int) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl_s, value)
            self._data.move_to_end(key)
            while len(self._data) > MAX_ENTRIES:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


response_cache = ResponseCache()
