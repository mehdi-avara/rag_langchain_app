"""Simple per-user / per-company rate guard (PROMPT §9).

A lightweight in-process sliding-window counter. It is intentionally minimal —
exceeding the limit raises the catalogued ``ASSISTANT_RATE_LIMITED``. For a
multi-process deployment this should be backed by Redis; the call site stays the
same.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from Models import User

from .errors import rate_limited

_WINDOW_SECONDS = int(os.getenv("ASSISTANT_RATE_WINDOW_SECONDS", "60"))
_MAX_PER_USER = int(os.getenv("ASSISTANT_RATE_MAX_PER_USER", "30"))
_MAX_PER_COMPANY = int(os.getenv("ASSISTANT_RATE_MAX_PER_COMPANY", "300"))

_lock = threading.Lock()
_user_hits: Dict[int, Deque[float]] = defaultdict(deque)
_company_hits: Dict[int, Deque[float]] = defaultdict(deque)


def _prune(bucket: Deque[float], now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def check_and_consume(user: User) -> None:
    now = time.monotonic()
    with _lock:
        ubucket = _user_hits[user.id]
        _prune(ubucket, now)
        if len(ubucket) >= _MAX_PER_USER:
            raise rate_limited("Per-user assistant rate limit exceeded")

        if user.company_id is not None:
            cbucket = _company_hits[user.company_id]
            _prune(cbucket, now)
            if len(cbucket) >= _MAX_PER_COMPANY:
                raise rate_limited("Per-company assistant rate limit exceeded")
            cbucket.append(now)

        ubucket.append(now)


def reset() -> None:  # test helper
    with _lock:
        _user_hits.clear()
        _company_hits.clear()
