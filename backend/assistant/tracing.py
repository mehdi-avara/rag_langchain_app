"""Fire-and-forget Langfuse tracing (PROMPT §9).

Tracing must never block or break the user path. If Langfuse is not installed or
not configured, every call here is a no-op. The repo already ships
``docker-compose-langfuse.yml``; set ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY``
/ ``LANGFUSE_HOST`` to enable.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_client = None
_initialised = False


def _get_client():
    global _client, _initialised
    if _initialised:
        return _client
    _initialised = True
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        _client = None
        return None
    try:  # pragma: no cover - optional dependency
        from langfuse import Langfuse

        _client = Langfuse()
    except Exception as exc:  # pragma: no cover
        logger.info("Langfuse tracing disabled: %s", exc)
        _client = None
    return _client


@contextmanager
def trace_run(name: str, **metadata):
    """Trace an assistant run; swallows all tracing errors."""
    client = _get_client()
    started = time.monotonic()
    trace = None
    if client is not None:  # pragma: no cover - only when configured
        try:
            trace = client.trace(name=name, metadata=metadata)
        except Exception:
            trace = None
    try:
        yield trace
    finally:
        if trace is not None:  # pragma: no cover
            try:
                trace.update(metadata={**metadata, "latency_seconds": time.monotonic() - started})
            except Exception:
                pass
