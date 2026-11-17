"""Live voice wiring for the admitted native flow adapter."""

from types import SimpleNamespace

from botelier.voice.flows.native_adapter import NativeFlowAdapter
from botelier.voice.flows.native_execution import NativeTerminalResult
from botelier.voice.flows.native_graph import CompiledFlow


def create_native_voice_runtime(
    selection, *, call_handler, llm, worker, context_aggregator,
    call_sid, stream_sid, from_number, to_number, twilio_account_sid,
    twilio_auth_token, account_name, assistant_timezone, session_factory,
    action_runner=None, global_functions=(),
    available_flows=None,
):
    """Build one native manager, scoped action runner, and terminal host bridge."""
    compiled = selection.compiled
    if not isinstance(compiled, CompiledFlow):
        raise TypeError("native_compiled_flow_required")

    from botelier.voice.function_mapper import FunctionMapper

    mapper = FunctionMapper(
        call_sid=call_sid,
        stream_sid=stream_sid,
        from_number=from_number,
        to_number=to_number,
        twilio_account_sid=twilio_account_sid,
        twilio_auth_token=twilio_auth_token,
        call_handler=call_handler,
        account_id=compiled.identity.account_id,
        account_name=account_name,
        property_id=compiled.identity.property_id,
        assistant_timezone=assistant_timezone,
        session_factory=session_factory,
    )

    execute_action = None
    if action_runner is None and any(
        node.type in {"api_request", "capability", "save_record"}
        for node in compiled.nodes
    ):
        from botelier.voice.flows.native_actions import NativeActionRunner

        action_runner = NativeActionRunner(
            compiled, session_factory, execution_mode="execute", channel="voice",
        )
    if action_runner is not None:
        execute_action = action_runner.execute

    terminal_handler = _terminal_handler(mapper, llm, worker)
    adapter = NativeFlowAdapter(
        compiled,
        llm=llm,
        worker=worker,
        context_aggregator=context_aggregator,
        execute_action=execute_action,
        terminal_handler=terminal_handler,
        global_functions=global_functions,
        available_flows=available_flows,
        direct_speech_observer=mapper._capture_direct_speech,
    )
    terminal_handler.adapter = adapter
    return adapter, mapper, action_runner


def _terminal_handler(mapper, llm, worker):
    async def handle_terminal(node, facts):
        from botelier.voice.flows.native_values import render_text

        data = node.data()
        if node.type == "end":
            message = render_text(data.get("closingMessage", ""), facts)
            tool = SimpleNamespace(
                name=f"native_end_{node.node_id}",
                description="Complete the configured native flow.",
                config={"goodbye_message": message},
            )
            _, handler = mapper._map_end_call(tool)
        elif node.type == "transfer":
            transfer = data.get("transfer", {})
            message = render_text(transfer.get("preTransferMessage", ""), facts)
            mode = transfer.get("transferMode")
            if mode is None:
                mode = "warm" if transfer.get("warmTransfer", True) else "cold"
            tool = SimpleNamespace(
                name=f"native_transfer_{node.node_id}",
                description="Transfer the call using its configured destination.",
                config={
                    "phone_number": transfer.get("phoneNumber", ""),
                    "pre_transfer_message": message,
                    "transfer_mode": mode,
                },
            )
            _, handler = mapper._map_transfer_call(tool)
        else:
            return NativeTerminalResult(False, failure_reason="terminal_type_invalid")

        async def result_callback(result=None, *args, **kwargs):
            # The mapper's transfer primitive reports its eventual, truthful
            # result here. It already owns its call event and caller messaging.
            adapter = getattr(handle_terminal, "adapter", None)
            if adapter is not None:
                adapter.observe_terminal_result(node.node_id, result)
            return None

        params = SimpleNamespace(
            llm=llm,
            pipeline_worker=worker,
            result_callback=result_callback,
            function_name=tool.name,
            arguments={},
        )
        await handler(params)
        if worker.has_finished():
            return NativeTerminalResult(False, failure_reason="call_ended")
        # The end/transfer primitive now owns playback and the deferred carrier
        # action. Scheduling it is only a pending terminal outcome, not proof of
        # hangup, transfer acceptance, or a human connection.
        return NativeTerminalResult(True, completed=False)

    handle_terminal.owns_speech = True
    return handle_terminal


__all__ = ["create_native_voice_runtime"]
