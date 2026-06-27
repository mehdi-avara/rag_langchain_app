"""Generic, module-agnostic AI Assistant core.

This package implements the assistant backbone described in the master plan §12
and the financial assistant prompt (docs/Phase_0/PROMPT_financial_assistant.md):

- ``models``      : the generic ``Draft`` and ``AgentRun`` tables.
- ``registry``    : the RBAC-filtered intent/tool registry (one source of truth).
- ``state``       : the LangGraph ``AgentState`` TypedDict.
- ``graph``       : the LangGraph control flow (router → handler → decide_next → end).
- ``runner``      : turn orchestration + SSE streaming + history persistence.
- ``service``     : draft CRUD (build via adapter, get/patch/committed/cancel).
- ``intake``      : file intake helper (VLM image blocks vs. extracted text).
- ``rbac``        : permission helpers (exactly the caller's access, never more).
- ``routes``      : the FastAPI endpoints (``/assistant/...``).

The financial module supplies *how to build* a payload and *which endpoint*
commits it via ``financial_management/assistant_tools.py``. The assistant never
performs domain writes — the frontend commits to the module's own endpoint.
"""

import logging
import os
import sys

# Ensure assistant.* logs (model selection, router calls, errors) are visible in
# the container stdout, even if the app doesn't configure root logging. Level is
# tunable via ASSISTANT_LOG_LEVEL (default INFO).
_assistant_logger = logging.getLogger("assistant")
if not _assistant_logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    _assistant_logger.addHandler(_handler)
    _assistant_logger.setLevel(getattr(logging, os.getenv("ASSISTANT_LOG_LEVEL", "INFO").upper(), logging.INFO))
    _assistant_logger.propagate = False

from .models import AgentRun, AgentRunStatus, Draft, DraftStatus

__all__ = [
    "AgentRun",
    "AgentRunStatus",
    "Draft",
    "DraftStatus",
]
