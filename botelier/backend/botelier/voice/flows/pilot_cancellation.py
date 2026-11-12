"""Reconcile native cancellation after earlier queued tool bookkeeping.

Pipecat 1.5.0 gives cancellation SystemFrames priority over the corresponding
in-progress ControlFrame. The assistant can therefore see cancellation too
early and retain a later IN_PROGRESS entry. Keep the SDK and mute policy
unchanged: an ordered control barrier repairs only the native assistant's
bookkeeping, using actual cancelled call IDs supplied by the native event.
"""

from dataclasses import dataclass

from pipecat.frames.frames import ControlFrame, FunctionCallCancelFrame, UninterruptibleFrame
from pipecat.processors.frame_processor import FrameDirection


@dataclass
class _CancellationBarrier(ControlFrame, UninterruptibleFrame):
    calls: tuple[tuple[str, str], ...] = ()


def reconcile_native_cancellation(
    *, llm, worker, context_aggregator, names, is_closed, native_prefix="",
):
    """Install call-owned hooks; never select a node or modify context internals."""
    names = frozenset(names)
    worker.add_reached_downstream_filter((_CancellationBarrier,))

    @llm.event_handler("on_function_calls_cancelled")
    async def cancelled(llm, calls):
        if is_closed() or worker.has_finished():
            return
        owned = tuple(dict.fromkeys(
            (call.function_name, call.tool_call_id)
            for call in calls if (
                call.function_name in names or (
                    native_prefix and isinstance(call.function_name, str)
                    and call.function_name.startswith(native_prefix)
                )
            )
        ))
        if owned:
            # Unlike another priority cancellation frame, this control frame
            # cannot overtake the already queued in-progress ControlFrame.
            await worker.queue_frame(_CancellationBarrier(calls=owned))

    @worker.event_handler("on_frame_reached_downstream")
    async def reached(worker, frame):
        if not isinstance(frame, _CancellationBarrier) or is_closed() or worker.has_finished():
            return
        for name, call_id in frame.calls:
            # Replay only at the assistant boundary, after all prior control
            # frames. Re-broadcasting upstream would make the user's mute
            # strategy remove an already-removed call ID. The native assistant
            # cancel handler is idempotent when its entry is already gone.
            await context_aggregator.assistant().queue_frame(
                FunctionCallCancelFrame(function_name=name, tool_call_id=call_id),
                FrameDirection.DOWNSTREAM,
            )
