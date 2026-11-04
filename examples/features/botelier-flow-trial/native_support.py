"""Test-only pipeline boundaries around the actual installed FlowManager.

This records frame enqueue/context updates. It is not a pipeline executor,
LLM service, audio transport, application adapter, or playback simulator.
"""

from copy import deepcopy
import json
from types import SimpleNamespace

from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.flows import FlowManager, FlowsFunctionSchema
from pipecat.frames.frames import (
    LLMMessagesAppendFrame,
    LLMMessagesUpdateFrame,
    LLMSetToolsFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import FunctionCallParams


def function(name, handler, properties=None, required=None):
    return FlowsFunctionSchema(
        name=name,
        description="Synthetic offline contract fixture",
        properties=properties or {},
        required=required or [],
        handler=handler,
    )


def node(name, *, functions=(), instruction=None, **config):
    return {
        "name": name,
        "task_messages": [
            {"role": "developer", "content": instruction or "Synthetic " + name}
        ],
        "functions": list(functions),
        "respond_immediately": False,
        **config,
    }


class RecordingBoundary:
    def __init__(self):
        self.context = LLMContext()
        self.frames = []
        self.tools = {}
        self.events = {}

    def set_reached_downstream_filter(self, frame_types):
        self.observed_types = frame_types

    def event_handler(self, name):
        def register(handler):
            self.events[name] = handler
            return handler
        return register

    async def queue_frame(self, frame, direction=None):
        self.frames.append(frame)
        if isinstance(frame, LLMMessagesUpdateFrame):
            self.context.set_messages(deepcopy(frame.messages))
        elif isinstance(frame, LLMMessagesAppendFrame):
            self.context.add_messages(deepcopy(frame.messages))
        elif isinstance(frame, LLMSetToolsFrame):
            self.context.set_tools(frame.tools)
            self.tools = (
                {tool.name: tool for tool in frame.tools.standard_tools}
                if isinstance(frame.tools, ToolsSchema) else {}
            )

    async def queue_frames(self, frames, direction=None):
        for frame in frames:
            await self.queue_frame(frame, direction)


class NativeHarness:
    def __init__(self, *, globals=()):
        self.boundary = RecordingBoundary()
        self.active_calls = set()
        self.results = []
        self.pending_updates = []
        self.non_calling_llm = object()
        self.manager = FlowManager(
            llm=self.non_calling_llm,
            worker=self.boundary,
            context_aggregator=self,
            global_functions=list(globals),
        )

    def user(self):
        return SimpleNamespace(_context=self.boundary.context)

    def assistant(self):
        return self

    @property
    def has_function_calls_in_progress(self):
        return bool(self.active_calls)

    async def flush_context_updates(self):
        pending, self.pending_updates = self.pending_updates, []
        for callback in pending:
            await callback()

    async def invoke(self, name, args, *, defer_context=False):
        schema = self.boundary.tools[name]
        call_id = "synthetic-" + str(len(self.results))
        self.active_calls.add(call_id)
        self.boundary.context.add_message({
            "role": "assistant",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }],
        })

        async def result_callback(result, *, properties=None):
            self.results.append(deepcopy(result))
            self.boundary.context.add_message({
                "role": "tool", "tool_call_id": call_id, "content": json.dumps(result),
            })
            self.active_calls.discard(call_id)
            if properties and properties.on_context_updated:
                self.pending_updates.append(properties.on_context_updated)
            if not defer_context:
                await self.flush_context_updates()

        await schema.handler(FunctionCallParams(
            function_name=name,
            tool_call_id=call_id,
            arguments=args,
            llm=self.non_calling_llm,
            pipeline_worker=self.boundary,
            context=self.boundary.context,
            result_callback=result_callback,
        ))
        return self.results[-1]
