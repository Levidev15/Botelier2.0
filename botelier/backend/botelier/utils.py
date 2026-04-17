"""Process-wide utilities shared across Botelier backend modules.

Currently exposes a single helper, :func:`log_task_exception`, used as an
``asyncio.Task.add_done_callback`` to surface tracebacks from
fire-and-forget background tasks (Task #116).

A bare ``asyncio.create_task(coro)`` swallows any exception raised outside
of the coroutine's own ``try/except`` blocks — the task object is garbage
collected without the traceback ever reaching a logger. This helper closes
that observability gap. Usage::

    task = asyncio.create_task(my_coro(), name="prewarm:CA123")
    task.add_done_callback(log_task_exception)

The callback is intentionally synchronous and tolerant of every shape an
``asyncio.Task`` can finish in:

* Successful completion -> no log line (would be noisy on every call).
* ``CancelledError`` -> debug log only (cooperative cancellation is
  expected on shutdown / connect-complete).
* Any other exception -> ``logger.exception`` with the task name so the
  traceback lands in the standard log sink.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger


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
        logger.debug(
            f"background task '{task.get_name()}' raised CancelledError"
        )
        return
    logger.opt(exception=exc).error(
        f"background task '{task.get_name()}' failed with unhandled "
        f"{type(exc).__name__}: {exc}"
    )
