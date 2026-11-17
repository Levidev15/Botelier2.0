"""Actual native text pipeline with generalized graph and synthetic providers."""

from application_support import API_KEYS
from native_text_io import NativeTextFixture
from native_graph_io import simple_flow_config
import json


class NativeGraphTextFixture(NativeTextFixture):
    def __init__(self, replies=(), *, definition=None, **options):
        super().__init__(list(replies), **options)
        from botelier.voice.flows.native_graph import compile_flow

        self.definition = simple_flow_config() if definition is None else definition
        self.compiled = compile_flow(
            self.definition, self.compiled.identity,
        )

    async def make_host(self, call_sid, *, greeting="Offline greeting."):
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.native_text_host import NativeTextHost
        from botelier.voice.flows.pilot_contract import PilotIdentity

        def with_call_sid(compiled):
            identity = compiled.identity
            return PilotIdentity(
                account_id=identity.account_id,
                property_id=identity.property_id,
                tool_id=identity.tool_id,
                flow_version_id=identity.flow_version_id,
                call_sid=call_sid,
            )

        compiled = compile_flow(self.definition, with_call_sid(self.compiled))
        available_flows = None
        if self.available_flows is not None:
            available_flows = {}
            for flow_id, entry in self.available_flows.items():
                source = self.compiled if flow_id == str(self.compiled.identity.tool_id) else entry["compiled"]
                available_flows[flow_id] = {
                    **entry,
                    "compiled": compile_flow(
                        source.config(), with_call_sid(source),
                    ),
                }
            if str(compiled.identity.tool_id) in available_flows:
                available_flows[str(compiled.identity.tool_id)]["compiled"] = compiled

        host = NativeTextHost(
            compiled,
            config=self.config.model_copy(update={"greeting_message": greeting}),
            api_keys=API_KEYS,
            session_factory=self.session_factory,
            turn_timeout=self.turn_timeout,
            available_flows=available_flows,
        )
        self.hosts.append(host)
        await host.start()
        return host

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
