"""Global assistant prompt fragments.

Domain-specific routing and extraction content belongs to each module's
``assistant_prompt.py`` metadata, not in this package.
"""

from .answer import answer_rules
from .base import global_rules
from .drafts import draft_rules
from .files import file_rules
from .router import module_router_rules, task_router_rules

__all__ = [
    "answer_rules",
    "draft_rules",
    "file_rules",
    "global_rules",
    "module_router_rules",
    "task_router_rules",
]
