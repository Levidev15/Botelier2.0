"""Process-wide utilities shared across Botelier backend modules.

Exposes:

* :func:`log_task_exception` — done-callback that surfaces tracebacks from
  fire-and-forget background tasks.
* :func:`sanitize_function_name` — converts an arbitrary display name into a
  name that satisfies the OpenAI function-name constraint
  ``^[a-zA-Z0-9_-]{1,64}$``.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from loguru import logger


def sanitize_function_name(name: str) -> str:
    """Convert an arbitrary tool display name into a valid OpenAI function name.

    OpenAI requires function names to match ``^[a-zA-Z0-9_-]{1,64}$``.
    This helper is deliberately one-way — the original display name is never
    altered in the database; only the name sent to the OpenAI API is sanitized.

    Transformation rules (applied in order):
    1. Strip leading/trailing whitespace.
    2. Replace spaces and hyphens with underscores.
    3. Remove every character that is not ``[a-zA-Z0-9_]``.
    4. Collapse consecutive underscores into one.
    5. If the result does not start with a letter, prepend ``fn_``.
    6. Truncate to 64 characters.
    7. If the result is empty after all of the above, return ``fn_tool``.
    """
    if not name:
        return "fn_tool"
    result = name.strip()
    result = re.sub(r"[ \-]", "_", result)
    result = re.sub(r"[^a-zA-Z0-9_]", "", result)
    result = re.sub(r"_+", "_", result)
    result = result.strip("_")
    if result and not result[0].isalpha():
        result = "fn_" + result
    result = result[:64]
    return result or "fn_tool"


def log_task_exception(task: "asyncio.Task[Any]") -> None:
    """Done-callback that logs unhandled exceptions from background tasks.

    Attach via ``task.add_done_callback(log_task_exception)`` to any
    fire-and-forget ``asyncio.create_task`` site. Safe to attach
    unconditionally — does nothing on success or cooperative cancellation.
    """
    if task.cancelled():
        logger.debug(f"background task '{task.get_name()}' cancelled")
        return
    exc = task.exception()
    if exc is None:
        return
    if isinstance(exc, asyncio.CancelledError):
        logger.debug(f"background task '{task.get_name()}' raised CancelledError")
        return
    logger.opt(exception=exc).error(
        f"background task '{task.get_name()}' failed with unhandled {type(exc).__name__}: {exc}"
    )
