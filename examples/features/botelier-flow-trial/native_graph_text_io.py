"""Actual native text pipeline with generalized graph and synthetic providers."""

from native_text_io import NativeTextFixture
from native_graph_io import simple_flow_config
import json


class NativeGraphTextFixture(NativeTextFixture):
    def __init__(self, replies=(), *, definition=None, **options):
        super().__init__(list(replies), **options)
        from botelier.voice.flows.native_graph import compile_flow

        self.compiled = compile_flow(
            simple_flow_config() if definition is None else definition,
            self.compiled.identity,
        )

    async def __aenter__(self):
        await super().__aenter__()
        self.boundary_trace = []
        original_idle = self.host._native_idle

        def traced_idle():
            host, adapter = self.host, self.host.adapter
            state = {
                "node": adapter.snapshot()["current_node"],
                "status": adapter.snapshot()["status"],
                "responses": [host._response_ends, host._expected_model_ends, host._model_inflight],
                "calls": len(host._active_calls),
                "transitions": host._transition_expected,
                "updates": host._observer.node_updates,
                "pending_speech": len(host._observer._pending_node_speeches),
                "claim": adapter._claim is not None,
                "owned_task": adapter._owned_task is not None,
                "pending_entry": adapter._pending_entry is not None,
                "assistant_calls": host._context_aggregator.assistant().has_function_calls_in_progress,
            }
            if not self.boundary_trace or self.boundary_trace[-1] != state:
                self.boundary_trace.append(state)
                self.boundary_trace = self.boundary_trace[-32:]
            return original_idle()

        self.host._native_idle = traced_idle
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if exc is not None:
            print("NATIVE_TEXT_BOUNDARIES=" + json.dumps(self.boundary_trace))
        return await super().__aexit__(exc_type, exc, traceback)
