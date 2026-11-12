"""Force native queue-reset windows rather than relying on favorable timing."""

import asyncio

from pipecat.frames.frames import (
    InterruptionFrame, LLMMessagesUpdateFrame, LLMSetToolsFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from node_contract_io import PRESENTATION, speech, tool_delta, wait_for_speech
from pilot_io import PilotCall, PilotProviders, native_schema


def control_source(call):
    # Node messages/tools are consumed by the actual user aggregator, before
    # reaching the LLM's clock processor. Hold the real predecessor instead.
    processors = call.created[0].processors
    return processors[processors.index(call.created[3].user()) - 1]


async def interrupt_paused_source(call, source):
    handled = asyncio.Event()

    @source.event_handler("on_after_process_frame")
    async def processed(processor, frame):
        if isinstance(frame, InterruptionFrame):
            handled.set()

    # Deliver the actual system frame to the paused receiver. Calling its
    # broadcast_interruption() directly would reset the pause event without
    # exercising normal receiver cancellation/restart, stranding that waiter.
    await source.queue_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await call.wait_until(handled.is_set)
    await source.resume_processing_frames()


def test_native_node_messages_and_tools_survive_interruption_while_queued():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
            tool_delta("collect_choice", {"choice": "Standard"}, call_id="choice-call"),
            "The selection is captured; no booking has been made.",
        ], status="hold")
        async with PilotCall(providers=providers) as call:
            await call.activate()
            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(lambda: providers.business_started.is_set())
            clock = control_source(call)
            await clock.pause_processing_frames()
            providers.release_business.set()
            await call.wait_until(lambda: (
                call.adapter.manager.current_node == "choice"
                and clock.has_queued_frame(LLMMessagesUpdateFrame)
                and clock.has_queued_frame(LLMSetToolsFrame)
            ))
            # Real native interruption resets this paused normal-frame queue.
            # The spoken result must remain interruptible; node control must not.
            await interrupt_paused_source(call, clock)
            await call.wait_for_node("choice")
            guidance = [
                message["content"] for message in call.created[4].messages
                if message.get("role") == "developer"
            ]
            assert any("Current saved flow node: choice." in text for text in guidance)
            assert not any("Current saved flow node: query." in text for text in guidance)
            assert PRESENTATION not in speech(call)
            await providers.user_turn("The Standard option.", turn_index=1)
            await wait_for_speech(call, "The selection is captured; no booking has been made.")
            assert call.adapter.facts["choice"] == "Standard"
            assert len(providers.business_requests) == 1
            assert PRESENTATION not in speech(call)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())


def test_native_cancellation_barrier_survives_another_interruption_while_queued():
    async def scenario():
        from botelier.voice.flows.pilot_cancellation import _CancellationBarrier

        providers = PilotProviders([
            tool_delta("collect_query", {"query": "standard"}),
            "The pending lookup was interrupted.",
        ], status="hold")
        async with PilotCall(providers=providers) as call:
            observed = []

            await call.activate()
            query_function_name = native_schema(call, "query").name

            @call.created[1].event_handler("on_frame_reached_downstream")
            async def reached(worker, frame):
                if isinstance(frame, _CancellationBarrier):
                    observed.append(frame.calls)

            await providers.user_turn("Please check the standard fixture.")
            await call.wait_until(lambda: providers.business_started.is_set())
            clock = control_source(call)
            await clock.pause_processing_frames()
            await call.created[2].queue_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
            await call.wait_until(lambda: (
                providers.business_cancelled and clock.has_queued_frame(_CancellationBarrier)
            ))
            await interrupt_paused_source(call, clock)
            await call.wait_until(lambda: bool(observed))
            assert observed == [((query_function_name, "node-contract-call"),)]
            await call.wait_until(lambda: not call.created[3].assistant().has_function_calls_in_progress)
            await providers.user_turn("Stop; that was the wrong fixture.", turn_index=1)
            await wait_for_speech(call, "The pending lookup was interrupted.")
            assert call.adapter.manager.current_node == "query"
            assert call.adapter.facts == {"query": "standard"}
            assert len(providers.business_requests) == 1
            assert PRESENTATION not in speech(call)
            await call.finish("graceful_end")
            call.assert_clean()
    asyncio.run(scenario())
