"""Graceful-shutdown finalizer for live calls (Task #116).

Extracted from ``main.py`` so it can be unit-tested without dragging the
full FastAPI/pipecat import graph. ``main.py`` calls
:func:`finalize_active_calls_on_shutdown` from its ``shutdown`` event
handler.

Why a dedicated module?

* ``main.py`` imports ``botelier.api.websockets`` at module load, which
  in turn imports ``voice.engine`` and pipecat. Tests that need to
  exercise the finalizer should not have to load that whole tree —
  keeping the helper here lets test files import only what they need.
* The lazy ``from botelier.api.websockets import call_handler`` inside
  the function preserves the original behavior: the finalizer never
  loads the websocket module unless it is actually invoked at shutdown.
"""

from __future__ import annotations

import asyncio


# Per-call shutdown finalization budget — keeps total deploy block bounded.
SHUTDOWN_PER_CALL_TIMEOUT = 2.0
SHUTDOWN_TOTAL_TIMEOUT = 10.0


async def finalize_active_calls_on_shutdown(
    session_factory, call_handler=None
) -> None:
    """Finalize every in-flight call before the worker exits.

    On uvicorn restart (deploy / reload / SIGTERM), in-memory call state
    dies and live WebSockets are torn down. Without this hook, any call
    that was in-progress lingers in the DB as ``in_progress`` for up to
    five minutes until the sweeper's next tick. This pollutes analytics
    and the live-call panel on the dashboard.

    For each active call SID we:

    1. Run ``CallLogger.complete_call(forced_by="shutdown")`` so the row
       reaches a terminal status with a ``finalization_forced`` event
       (``details.source == "shutdown"``) — distinguishable from
       sweeper-closed rows in the leak-rate dashboard.
    2. Cancel the corresponding pipeline so no further frames are pushed
       through a dead transport.

    The whole hook is bounded by ``SHUTDOWN_TOTAL_TIMEOUT`` so a slow DB
    or a stuck pipeline cancellation cannot block deploys indefinitely.

    Args:
        session_factory: Zero-arg callable returning a fresh SQLAlchemy
            ``Session`` (typically ``SessionLocal``). Passed in rather
            than imported so tests can inject mocks without touching
            ``database.py`` globals.
        call_handler: Optional ``CallHandler`` instance. When ``None``,
            it is lazily imported from ``botelier.api.websockets`` —
            this keeps the production call site (main.py) terse while
            allowing tests to inject a stub without touching the
            websockets module at all.
    """
    if call_handler is None:
        try:
            from botelier.api.websockets import call_handler as _call_handler
            call_handler = _call_handler
        except Exception as e:
            print(f"⚠️  shutdown finalizer: could not import call_handler: {e}")
            return

    active_sids = list(
        set(call_handler.active_calls.keys())
        | set(call_handler.call_tasks.keys())
    )
    if not active_sids:
        return

    print(f"🛑 Finalizing {len(active_sids)} active call(s) on shutdown")

    async def _finalize_one(sid: str) -> None:
        # 1. Row finalization (synchronous DB work via to_thread).
        def _do_complete() -> None:
            db = session_factory()
            try:
                from botelier.services.call_logger import CallLogger
                CallLogger(db).complete_call(
                    call_sid=sid, forced_by="shutdown"
                )
            finally:
                db.close()

        try:
            await asyncio.wait_for(
                asyncio.to_thread(_do_complete),
                timeout=SHUTDOWN_PER_CALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print(f"⚠️  shutdown finalizer: complete_call timed out for {sid}")
        except Exception as e:
            print(f"⚠️  shutdown finalizer: complete_call failed for {sid}: {e}")

        # 2. Cancel the pipeline so the runner unblocks promptly.
        try:
            await asyncio.wait_for(
                call_handler.cancel_call_pipeline(sid),
                timeout=SHUTDOWN_PER_CALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print(f"⚠️  shutdown finalizer: cancel_call_pipeline timed out for {sid}")
        except Exception as e:
            print(f"⚠️  shutdown finalizer: cancel_call_pipeline failed for {sid}: {e}")

    try:
        await asyncio.wait_for(
            asyncio.gather(
                *[_finalize_one(sid) for sid in active_sids],
                return_exceptions=True,
            ),
            timeout=SHUTDOWN_TOTAL_TIMEOUT,
        )
        print(f"✅ Shutdown finalizer completed for {len(active_sids)} call(s)")
    except asyncio.TimeoutError:
        print(
            f"⚠️  Shutdown finalizer hit total timeout "
            f"({SHUTDOWN_TOTAL_TIMEOUT}s) — sweeper will pick up stragglers"
        )
