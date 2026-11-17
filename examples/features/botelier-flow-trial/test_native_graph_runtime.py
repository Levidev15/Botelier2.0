"""Runtime contracts over the installed native FlowManager."""

import asyncio
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json

import pytest

from native_graph_io import (
    GraphCall, GraphProviders, NativeGraphPipelineCall, compile_full_catalog_flow,
    compile_guided_flow, compile_simple_flow, compile_transfer_flow,
    full_catalog_config,
)


def test_boundary_results_snapshot_mutable_values_and_confirmation():
    from botelier.voice.flows.native_execution import (
        NativeActionResult, NativeConfirmation, NativeTerminalResult,
    )

    variables = {"items": [{"name": "Standard"}]}
    llm_data = {"items": [{"name": "Standard"}]}
    result = NativeActionResult(True, variables=variables, llm_data=llm_data)
    variables["items"][0]["name"] = "changed"
    llm_data.clear()
    assert result.variables == {"items": [{"name": "Standard"}]}
    exposed = result.variables
    exposed["items"].clear()
    assert result.variables == {"items": [{"name": "Standard"}]}

    values = {"name": "Caller"}
    confirmation = NativeConfirmation("confirm", 7, json.dumps(values), ("name",))
    values["name"] = "changed"
    assert confirmation.values() == {"name": "Caller"}
    assert confirmation.confirmed_fields == ("name",)
    with pytest.raises((FrozenInstanceError, AttributeError)):
        confirmation.revision = 8

    assert NativeTerminalResult(True, completed=False).accepted
    with pytest.raises(ValueError):
        NativeActionResult(True, branch="invented")
    with pytest.raises(ValueError):
        NativeActionResult(True, branch="not_found")
    with pytest.raises(ValueError):
        NativeActionResult(False, branch="success")
    with pytest.raises(ValueError):
        NativeActionResult(True, variables=[])
    with pytest.raises(ValueError):
        NativeActionResult(True, llm_data=[])


def test_declared_defaults_are_typed_facts_with_progress_not_model_generated():
    async def scenario():
        from botelier.voice.flows.native_graph import compile_flow

        base = compile_simple_flow()
        config = base.config()
        config["variables"][0]["defaultValue"] = "Ada"
        call = GraphCall(compile_flow(config, base.identity))
        await call.adapter.start()
        assert call.adapter.facts == {"name": "Ada"}
        assert call.adapter.snapshot()["variables"]["name"] == {
            "type": "text", "required": True, "status": "collected",
        }
        await call.adapter.close()

    asyncio.run(scenario())


def test_explicit_mapped_outputs_work_without_mutating_the_original_flow_declarations():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult, NativeTerminalResult
        from botelier.voice.flows.native_graph import compile_flow

        base = compile_simple_flow()
        definition = base.config()
        definition["nodes"].extend([
            {"id": "lookup", "type": "api_request", "data": {"api": {
                "apiSource": "custom", "method": "GET",
                "url": "https://api.fixture.invalid/search",
                "responseMapping": {"offers": "rooms"},
            }}},
            {"id": "response", "type": "api_response", "data": {
                "responsePresentation": {
                    "arrayVariable": "offers", "introText": "Available options.",
                    "itemTemplate": "{{name}} costs {{price}}.",
                    "outroText": "", "noResultsText": "No options.",
                },
            }},
        ])
        next(edge for edge in definition["edges"] if edge["source"] == "name")["target"] = "lookup"
        definition["edges"].extend([
            {"id": "lookup-response", "source": "lookup", "sourceHandle": "success", "target": "response"},
            {"id": "lookup-error", "source": "lookup", "sourceHandle": "error", "target": "done"},
            {"id": "response-done", "source": "response", "sourceHandle": "has_results", "target": "done"},
            {"id": "response-empty", "source": "response", "sourceHandle": "no_results", "target": "done"},
        ])
        compiled = compile_flow(definition, base.identity)
        assert compiled.config() == definition
        assert {item.key: item.origin for item in compiled.variable_declarations} == {
            "name": "explicit", "offers": "output",
        }
        offers = [
            {"name": "Standard", "price": 0, "tax_inclusive": False},
            {"name": "Suite", "price": 125},
        ]

        async def execute(node, facts, *, confirmation):
            assert node.node_id == "lookup" and facts == {"name": "Ada"}
            return NativeActionResult(True, variables={"offers": offers})

        async def terminal(node, facts):
            return NativeTerminalResult(True, completed=True)

        call = GraphCall(compiled, execute_action=execute, terminal_handler=terminal)
        try:
            await call.adapter.start()
            call.user_turn("Ada")
            result = await call.invoke(next(iter(call.worker.tools)), {"name": "Ada"})
            assert result["status"] == "accepted"
            assert call.adapter.facts == {"name": "Ada", "offers": offers}
            assert call.adapter.snapshot()["variables"]["offers"]["status"] == "collected"
            copied = call.adapter._normalize_assignment("offers", offers)
            assert copied == offers and copied is not offers
            assert call.adapter.snapshot()["status"] == "completed"
        finally:
            await call.adapter.close()

    asyncio.run(scenario())


def test_real_flow_manager_runs_initial_greeting_then_only_current_collection_tool():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeTerminalResult

        async def terminal(node, facts):
            return NativeTerminalResult(True, completed=False)

        call = GraphCall(compile_simple_flow(), terminal_handler=terminal)
        await call.adapter.start()
        assert call.adapter.manager.current_node == "name"
        assert call.adapter.snapshot()["current_node"] == "name"
        assert [frame.text for frame in call.worker.frames
                if frame.__class__.__name__ == "TTSSpeakFrame"] == [
                    "Welcome to the fixture.", "What is your name?",
                ]
        assert len(call.worker.tools) == 1
        name, = call.worker.tools
        assert name.startswith("native_name_")
        call.user_turn("Ada")
        result = await call.invoke(name, {"name": "Ada"})
        assert result["status"] == "accepted"
        assert call.adapter.manager.current_node == "done"
        assert call.adapter.snapshot()["current_node"] == "done"
        assert call.adapter.facts["name"] == "Ada"
        assert call.adapter.snapshot()["status"] == "terminal_pending"
        await call.adapter.close()

    asyncio.run(scenario())


def test_callback_inputs_are_detached_and_failed_terminal_does_not_complete():
    async def scenario():
        seen = []

        async def terminal(node, facts):
            seen.append(deepcopy(facts))
            facts["name"] = "tampered"
            from botelier.voice.flows.native_execution import NativeTerminalResult
            return NativeTerminalResult(False, completed=True)

        call = GraphCall(compile_simple_flow(), terminal_handler=terminal)
        await call.adapter.start()
        name, = call.worker.tools
        call.user_turn("Ada")
        await call.invoke(name, {"name": "Ada"})
        assert seen == [{"name": "Ada"}]
        assert call.adapter.facts == {"name": "Ada"}
        assert call.adapter.snapshot()["completed"] is False
        await call.adapter.close()

    asyncio.run(scenario())


def test_actual_pipecat_pipeline_orders_guided_collection_and_terminal_speech():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeTerminalResult
        from node_contract_io import speech, tool_delta, tool_result

        holder = {}
        terminal_calls = []

        async def terminal(node, facts):
            call = holder["call"]
            closing = "Thanks, Ada."
            await call.wait_until(lambda: closing in speech(call))
            terminal_calls.append((node.node_id, deepcopy(facts)))
            return NativeTerminalResult(True, completed=True)

        call = NativeGraphPipelineCall(
            compile_simple_flow(), providers=GraphProviders([
                tool_delta("collect_name", {"name": "Ada"}),
            ]), terminal_handler=terminal,
        )
        holder["call"] = call
        async with call:
            await call.activate()
            await call.providers.user_turn("Ada")
            await call.wait_until(lambda: call.adapter.manager.current_node == "done")
            assert terminal_calls == [("done", {"name": "Ada"})]
            assert call.adapter.snapshot()["completed"] is True
            assert speech(call)[-2:] == ["What is your name?", "Thanks, Ada."]
            assert tool_result(call)["status"] == "accepted"
            assert sum(bool(item.get("stream")) for item in call.providers.requests) == 1
            await call.finish("graceful_end")
            call.assert_clean()

    asyncio.run(scenario())


def test_full_catalog_order_selection_confirmation_actions_and_terminal():
    async def scenario():
        from botelier.voice.flows.native_execution import (
            NativeActionResult, NativeConfirmation, NativeTerminalResult,
        )

        action_order = []
        terminal_calls = []
        rooms = [
            {"name": "First room", "price": 50},
            {"name": "Second room", "price": 90},
        ]

        async def execute_action(node, facts, *, confirmation):
            action_order.append((node.node_id, deepcopy(facts), confirmation))
            if node.node_id == "lookup":
                return NativeActionResult(
                    True, variables={"items": rooms},
                    llm_data={"items": rooms, "count": 2},
                )
            if node.node_id == "capability":
                assert isinstance(confirmation, NativeConfirmation)
                return NativeActionResult(True)
            if node.node_id == "save":
                assert isinstance(confirmation, NativeConfirmation)
                return NativeActionResult(True)
            raise AssertionError("Unexpected action node")

        async def terminal(node, facts):
            terminal_calls.append((node.node_id, deepcopy(facts)))
            return NativeTerminalResult(True, completed=True)

        call = GraphCall(
            compile_full_catalog_flow(), execute_action=execute_action,
            terminal_handler=terminal,
        )
        await call.adapter.start()

        def active_tool(prefix=None):
            tools = list(call.worker.tools.values())
            assert len(tools) == 1
            if prefix:
                assert tools[0].name.startswith(prefix)
            return tools[0]

        call.user_turn("fixtures")
        await call.invoke_schema(active_tool("native_query_"), {"query": "fixtures"})
        call.user_turn("Ada")
        await call.invoke_schema(active_tool("native_form_"), {"name": "Ada"})
        call.user_turn("ada@example.com")
        form_result = await call.invoke_schema(
            active_tool("native_form_"), {"email": "ada@example.com"},
        )
        assert form_result["data"] == {"items": rooms, "count": 2}
        assert call.adapter.manager.current_node == "picker"
        assert call.adapter.facts["derived"] == "Ada"
        assert call.adapter.facts["channel"] == "lookup"
        assert call.adapter.facts["items"] == rooms
        assert call.adapter.manager.state["native_llm_data"] == {
            "items": rooms, "count": 2,
        }

        picker_schema, = call.worker.tools.values()
        call.user_turn("I meant first room and second room")
        rejected = await call.invoke_schema(picker_schema, {
            "ordinal": 1, "label": "Second room",
        })
        assert rejected == {"status": "rejected", "reason": "selection_invalid"}
        assert call.adapter.snapshot()["retries"] == {"picker.selection": 1}
        assert "selected_price" not in call.adapter.facts

        call.user_turn("Second room")
        assert next(iter(call.worker.tools)) == picker_schema.name
        await call.invoke_schema(active_tool("native_picker_"), {
            "ordinal": 2, "label": "Second room",
        })
        assert call.adapter.manager.current_node == "confirm"
        assert call.adapter.facts["selected_name"] == "Second room"
        assert call.adapter.facts["selected_price"] == 90
        call.user_turn("yes")
        await call.invoke_schema(active_tool("native_confirm_"), {"response": "yes"})
        assert call.adapter.manager.current_node == "end"
        assert call.adapter.snapshot()["status"] == "completed"
        assert action_order == [
            ("lookup", {
                "query": "fixtures", "name": "Ada", "email": "ada@example.com",
                "derived": "Ada", "channel": "lookup",
            }, None),
            ("capability", {
                "query": "fixtures", "name": "Ada", "email": "ada@example.com",
                "derived": "Ada", "channel": "lookup", "items": rooms,
                "selected_name": "Second room", "selected_price": 90,
            }, action_order[1][2]),
            ("save", {
                "query": "fixtures", "name": "Ada", "email": "ada@example.com",
                "derived": "Ada", "channel": "lookup", "items": rooms,
                "selected_name": "Second room", "selected_price": 90,
            }, action_order[2][2]),
        ]
        confirmation = action_order[1][2]
        assert isinstance(confirmation, NativeConfirmation)
        assert confirmation.node_id == "confirm"
        assert confirmation.values() == {"name": "Ada", "selected_price": 90}
        assert terminal_calls == [("end", call.adapter.facts)]
        assert call.adapter.facts["selected_price"] == 90
        await call.adapter.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "utterance",
    [
        "yes, but I need to change the room",
        "No, not yes; I need to change the room",
    ],
)
def test_actual_pipeline_rejects_qualified_or_negative_yes_before_write(utterance):
    async def scenario():
        from node_contract_io import tool_delta

        action_nodes = []
        rooms = [
            {"name": "First room", "price": 50},
            {"name": "Second room", "price": 90},
        ]

        async def execute(node, facts, *, confirmation):
            action_nodes.append(node.node_id)
            from botelier.voice.flows.native_execution import NativeActionResult
            if node.node_id == "lookup":
                return NativeActionResult(
                    True, variables={"items": rooms},
                    llm_data={"items": rooms, "count": 2},
                )
            return NativeActionResult(True)

        call = NativeGraphPipelineCall(
            compile_full_catalog_flow(),
            providers=GraphProviders([
                tool_delta("collect_query", {"query": "fixtures"}),
                tool_delta("collect_name", {"name": "Ada"}),
                tool_delta("collect_email", {"email": "ada@example.com"}),
                tool_delta("select_room", {"ordinal": 2, "label": "Second room"}),
                tool_delta("confirm", {"response": "yes"}),
                "Please confirm yes or no.",
            ]),
            execute_action=execute,
        )
        async with call:
            await call.activate()
            def native_tools():
                return {
                    item.name for item in getattr(
                        call.created[4].tools, "standard_tools", (),
                    ) if item.name.startswith("native_")
                }

            await call.wait_until(lambda: bool(native_tools()))
            turns = ("fixtures", "Ada", "ada@example.com", "Second room", utterance)
            expected_nodes = ("form", "form", "picker", "confirm", "confirm")
            for index, (turn, expected_node) in enumerate(zip(turns, expected_nodes)):
                previous_tools = native_tools()
                await call.providers.user_turn(turn, turn_index=index)
                if index < len(turns) - 1:
                    await call.wait_until(lambda: (
                        call.adapter.manager.current_node == expected_node
                        and native_tools() != previous_tools
                    ))
                else:
                    await call.wait_until(lambda: len([
                        item for item in call.created[4].messages
                        if item.get("role") == "tool"
                    ]) >= index + 1)
            messages = [
                item for item in call.created[4].messages if item.get("role") == "tool"
            ]
            assert json.loads(messages[-1]["content"]) == {
                "status": "rejected", "reason": "caller_response_mismatch",
            }
            assert call.adapter.manager.current_node == "confirm"
            assert action_nodes == ["lookup"]
            await call.finish("graceful_end")
            call.assert_clean()

    asyncio.run(scenario())


def test_initial_wait_node_injects_configured_system_prompt_once():
    async def scenario():
        from botelier.voice.flows.native_graph import compile_flow

        config = compile_simple_flow().config()
        config["nodes"][0]["data"]["waitForResponse"] = True
        compiled = compile_flow(config, compile_simple_flow().identity)
        call = GraphCall(compiled)
        config = call.adapter._node_config("start", source_visit=None)
        messages = config["task_messages"]
        private = [
            item for item in messages
            if item.get("role") == "developer"
            and item.get("content") == "Keep the greeting private guidance."
        ]
        assert len(private) == 1

    asyncio.run(scenario())


def test_retry_and_stale_schema_rejection_keep_facts_and_effects_owned():
    async def scenario():
        config = full_catalog_config()
        slot = next(node for node in config["nodes"] if node["id"] == "query")["data"]["slot"]
        slot.update(type="email", maxRetries=1, retryPrompt="Use a valid email.")
        config["variables"][0]["type"] = "email"
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.pilot_contract import PilotIdentity

        compiled = compile_flow(config, PilotIdentity(
            account_id="a", property_id="p", tool_id="t",
            flow_version_id="v", call_sid="c",
        ))
        call = GraphCall(compiled)
        await call.adapter.start()
        retained = next(iter(call.worker.tools.values()))
        call.user_turn("not-an-email")
        first = await call.invoke_schema(retained, {"query": "not-an-email"})
        assert first == {"status": "rejected", "reason": "validation"}
        assert call.adapter.facts == {}
        assert call.adapter.snapshot()["retries"] == {"query.query": 1}
        call.user_turn("still-not-an-email")
        second = await call.invoke_schema(retained, {"query": "still-not-an-email"})
        assert second == {"status": "rejected", "reason": "retry_exhausted"}
        assert call.adapter.snapshot()["status"] == "failed"
        assert call.adapter.facts == {}

        await call.adapter.close()

    asyncio.run(scenario())


def test_explicit_edit_clears_stale_derived_values_and_never_replays_spent_action():
    async def scenario():
        from botelier.voice.flows.native_execution import (
            NativeActionResult, NativeTerminalResult,
        )

        action_calls = []

        async def execute(node, facts, *, confirmation):
            action_calls.append(node.node_id)
            return NativeActionResult(True, variables={"items": [
                {"name": "Only room", "price": 12},
            ]})

        async def terminal(node, facts):
            return NativeTerminalResult(True, completed=False)

        call = GraphCall(
            compile_full_catalog_flow(), execute_action=execute,
            terminal_handler=terminal,
        )
        await call.adapter.start()

        def tool(prefix):
            schema, = call.worker.tools.values()
            assert schema.name.startswith(prefix)
            return schema

        call.user_turn("x")
        await call.invoke_schema(tool("native_query_"), {"query": "x"})
        call.user_turn("Name")
        await call.invoke_schema(tool("native_form_"), {"name": "Name"})
        call.user_turn("name@example.com")
        await call.invoke_schema(tool("native_form_"), {"email": "name@example.com"})
        call.user_turn("First room")
        await call.invoke_schema(tool("native_picker_"), {"ordinal": 1})
        call.user_turn("edit")
        await call.invoke_schema(tool("native_confirm_"), {"response": "edit"})
        assert call.adapter.manager.current_node == "correct"
        assert "items" not in call.adapter.facts
        assert "selected_price" not in call.adapter.facts
        assert "name" not in call.adapter.facts
        call.user_turn("Corrected")
        await call.invoke_schema(tool("native_correct_"), {"name": "Corrected"})
        assert call.adapter.facts["name"] == "Corrected"
        assert "items" not in call.adapter.facts
        assert "selected_price" not in call.adapter.facts
        assert call.adapter._confirmation is None
        assert action_calls == ["lookup"]
        await call.adapter.close()

    asyncio.run(scenario())


def test_actual_pipeline_executes_the_full_in_order_native_catalog():
    async def scenario():
        from botelier.voice.flows.native_execution import (
            NativeActionResult, NativeConfirmation, NativeTerminalResult,
        )
        from node_contract_io import speech, tool_delta

        holder = {}
        action_nodes = []
        terminal_nodes = []
        rooms = [
            {"name": "First room", "price": 50},
            {"name": "Second room", "price": 90},
        ]

        async def execute(node, facts, *, confirmation):
            action_nodes.append(node.node_id)
            if node.node_id == "lookup":
                return NativeActionResult(
                    True, variables={"items": rooms},
                    llm_data={"items": rooms, "count": 2},
                )
            assert isinstance(confirmation, NativeConfirmation)
            return NativeActionResult(True)

        async def terminal(node, facts):
            call = holder["call"]
            await call.wait_until(lambda: "Thanks, Ada." in speech(call))
            terminal_nodes.append((node.node_id, deepcopy(facts)))
            return NativeTerminalResult(True, completed=True)

        call = NativeGraphPipelineCall(
            compile_full_catalog_flow(),
            providers=GraphProviders([
                tool_delta("collect_query", {"query": "fixtures"}),
                tool_delta("collect_name", {"name": "Ada"}),
                tool_delta("collect_email", {"email": "ada@example.com"}),
                tool_delta("select_room", {"ordinal": 2, "label": "Second room"}),
                tool_delta("confirm", {"response": "yes"}),
            ]),
            execute_action=execute, terminal_handler=terminal,
        )
        holder["call"] = call
        async with call:
            await call.activate()
            def native_tools():
                tools = getattr(call.created[4], "tools", None)
                return {
                    item.name for item in getattr(tools, "standard_tools", ())
                    if item.name.startswith("native_")
                }

            await call.wait_until(lambda: bool(native_tools()))
            turns = (
                ("fixtures", "form"),
                ("Ada", "form"),
                ("ada@example.com", "picker"),
                ("Second room", "confirm"),
                ("yes", "end"),
            )
            for index, (turn, expected_node) in enumerate(turns):
                prior_tools = native_tools()
                await call.providers.user_turn(turn, turn_index=index)
                await call.wait_until(lambda: (
                    call.adapter.manager.current_node == expected_node
                    and (
                        expected_node == "end"
                        or native_tools() != prior_tools
                    )
                ))
            await call.wait_until(lambda: (
                call.adapter.manager.current_node == "end"
                and call.adapter.snapshot()["completed"]
            ))
            assert action_nodes == ["lookup", "capability", "save"]
            assert terminal_nodes == [("end", call.adapter.facts)]
            assert call.adapter.facts["selected_name"] == "Second room"
            assert call.adapter.facts["selected_price"] == 90
            assert sum(bool(item.get("stream")) for item in call.providers.requests) == 5
            assert speech(call)[-1] == "Thanks, Ada."
            context_messages = call.created[4].get_messages()
            developer_text = "\n".join(
                message.get("content", "") for message in context_messages
                if message.get("role") == "developer"
            )
            assert developer_text.count("Private fixture policy; do not quote it.") == 1
            assert "Private initial policy." not in developer_text
            assert "Privately present results for Ada." not in developer_text
            assert all(any(
                message.get("role") == "user" and turn in message.get("content", "")
                for message in context_messages
            ) for turn in ("fixtures", "Ada", "ada@example.com", "Second room", "yes"))
            assert sum(message.get("role") == "tool" for message in context_messages) == 5
            await call.finish("graceful_end")
            call.assert_clean()

    asyncio.run(scenario())


def test_guided_message_advances_only_after_actual_generated_speech_finishes():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeTerminalResult
        from node_contract_io import speech

        holder = {}
        terminal_calls = []

        async def terminal(node, facts):
            call = holder["call"]
            await call.wait_until(
                lambda: "Guided message finished." in speech(call),
            )
            terminal_calls.append(node.node_id)
            return NativeTerminalResult(True, completed=True)

        call = NativeGraphPipelineCall(
            compile_guided_flow(),
            providers=GraphProviders(["The guided message."]),
            terminal_handler=terminal,
        )
        holder["call"] = call
        async with call:
            await call.activate()
            await call.wait_until(lambda: (
                call.adapter.manager.current_node == "end"
                and call.adapter.snapshot()["completed"]
            ))
            assert terminal_calls == ["end"]
            assert speech(call)[-3:] == [
                "Static opening.", "The guided message.", "Guided message finished.",
            ]
            assert sum(bool(item.get("stream")) for item in call.providers.requests) == 1
            await call.finish("graceful_end")
            call.assert_clean()

    asyncio.run(scenario())


async def _reach_full_catalog_picker(call, name="Ada"):
    await call.adapter.start()
    for node_prefix, value, arguments in (
        ("native_query_", "fixtures", {"query": "fixtures"}),
        ("native_form_", name, {"name": name}),
        ("native_form_", "ada@example.com", {"email": "ada@example.com"}),
    ):
        call.user_turn(value)
        schema, = call.worker.tools.values()
        assert schema.name.startswith(node_prefix)
        await call.invoke_schema(schema, arguments)
    assert call.adapter.manager.current_node == "picker"


def test_api_auth_error_and_empty_result_use_only_configured_safe_branches():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult, NativeTerminalResult

        for action_result, expected_message, expected_node in (
            (
                NativeActionResult(
                    False, branch="auth_error", failure_reason="auth_denied",
                ),
                "The fixture rejected authorization.",
                "end",
            ),
            (
                NativeActionResult(True, variables={"items": []}, llm_data={"items": []}),
                "No fixture options.",
                "end",
            ),
        ):
            action_nodes = []

            async def execute(node, facts, *, confirmation):
                action_nodes.append(node.node_id)
                return action_result

            async def terminal(node, facts):
                return NativeTerminalResult(True, completed=True)

            call = GraphCall(
                compile_full_catalog_flow(), execute_action=execute,
                terminal_handler=terminal,
            )
            await call.adapter.start()
            for prefix, value, arguments in (
                ("native_query_", "fixtures", {"query": "fixtures"}),
                ("native_form_", "Ada", {"name": "Ada"}),
                ("native_form_", "ada@example.com", {"email": "ada@example.com"}),
            ):
                call.user_turn(value)
                schema, = call.worker.tools.values()
                assert schema.name.startswith(prefix)
                await call.invoke_schema(schema, arguments)
            assert call.adapter.manager.current_node == expected_node
            assert action_nodes == ["lookup"]
            assert call.adapter.facts.get("items") == ([] if action_result.success else None)
            spoken = [frame.text for frame in call.worker.frames
                      if frame.__class__.__name__ == "TTSSpeakFrame"]
            assert expected_message in spoken
            assert "fixture unavailable exception" not in " ".join(spoken)
            assert call.adapter.snapshot()["completed"] is True
            await call.adapter.close()

    asyncio.run(scenario())


def test_failed_record_callback_is_truthful_and_does_not_complete_or_advance():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult, NativeTerminalResult

        calls = []

        async def execute(node, facts, *, confirmation):
            calls.append(node.node_id)
            if node.node_id == "lookup":
                return NativeActionResult(True, variables={"items": [
                    {"name": "First room", "price": 50},
                ]})
            if node.node_id == "capability":
                return NativeActionResult(True)
            return NativeActionResult(
                False, branch="error", failure_reason="write_rejected",
            )

        async def terminal(node, facts):
            return NativeTerminalResult(True, completed=True)

        call = GraphCall(
            compile_full_catalog_flow(), execute_action=execute,
            terminal_handler=terminal,
        )
        await _reach_full_catalog_picker(call)
        call.user_turn("First room")
        schema, = call.worker.tools.values()
        await call.invoke_schema(schema, {"ordinal": 1, "label": "First room"})
        call.user_turn("yes")
        schema, = call.worker.tools.values()
        result = await call.invoke_schema(schema, {"response": "yes"})
        assert result == {"status": "error", "reason": "write_rejected"}
        assert calls == ["lookup", "capability", "save"]
        assert call.adapter.snapshot()["status"] == "failed"
        assert call.adapter.snapshot()["completed"] is False
        assert call.adapter.manager.current_node == "confirm"
        await call.adapter.close()

    asyncio.run(scenario())


def test_option_picker_clears_missing_writes_atomically():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeTerminalResult
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.pilot_contract import PilotIdentity

        config = {
            "initial_node": "start",
            "variables": [
                {"key": "items", "type": "text"},
                {"key": "selected_room", "type": "text"},
                {"key": "price", "type": "number"},
            ],
            "nodes": [
                {"id": "start", "type": "initial", "data": {
                    "greeting": "", "waitForResponse": False,
                }},
                {"id": "pick", "type": "option_picker", "data": {
                    "optionPicker": {
                        "sourceVariable": "items", "labelPath": "name",
                        "prompt": "Choose a room.",
                        "writes": [
                            {"variableKey": "selected_room", "path": "name"},
                            {"variableKey": "price", "path": "price"},
                        ],
                    },
                }},
                {"id": "end", "type": "end", "data": {"closingMessage": "Done."}},
            ],
            "edges": [
                {"id": "start-pick", "source": "start", "target": "pick"},
                {"id": "pick-end", "source": "pick", "target": "end",
                 "sourceHandle": "selected"},
            ],
        }
        compiled = compile_flow(config, PilotIdentity(
            account_id="a", property_id="p", tool_id="t",
            flow_version_id="v", call_sid="c",
        ))

        async def terminal(node, facts):
            return NativeTerminalResult(True, completed=False)

        call = GraphCall(compiled, terminal_handler=terminal)
        await call.adapter.start()
        call.adapter.manager.state["facts"].update({
            "items": [{"name": "Only room"}], "price": 99,
        })
        call.user_turn("Only room")
        schema, = call.worker.tools.values()
        await call.invoke_schema(schema, {"label": "Only room"})
        assert call.adapter.facts["selected_room"] == "Only room"
        assert call.adapter.facts["price"] is None
        assert call.adapter.manager.current_node == "end"
        await call.adapter.close()

    asyncio.run(scenario())


def test_transfer_pre_message_precedes_terminal_callback_and_is_not_completion_proof():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeTerminalResult

        observed = []

        async def terminal(node, facts):
            assert node.type == "transfer"
            assert call.worker.frames[-1].text == "Connecting you to the fixture team."
            observed.append(node.node_id)
            return NativeTerminalResult(True, completed=False)

        call = GraphCall(compile_transfer_flow(), terminal_handler=terminal)
        await call.adapter.start()
        call.user_turn("human")
        schema, = call.worker.tools.values()
        await call.invoke_schema(schema, {"request": "human"})
        assert observed == ["transfer"]
        assert call.adapter.manager.current_node == "transfer"
        assert call.adapter.snapshot()["status"] == "terminal_pending"
        assert call.adapter.snapshot()["completed"] is False
        await call.adapter.close()

    asyncio.run(scenario())


def test_stale_schema_cannot_mutate_facts_after_native_transition():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeTerminalResult

        async def terminal(node, facts):
            return NativeTerminalResult(True, completed=False)

        call = GraphCall(compile_simple_flow(), terminal_handler=terminal)
        await call.adapter.start()
        schema, = call.worker.tools.values()
        call.user_turn("Ada")
        await call.invoke_schema(schema, {"name": "Ada"})
        assert call.adapter.manager.current_node == "done"
        call.user_turn("Grace")
        stale = await call.invoke_schema(schema, {"name": "Grace"})
        assert stale == {"status": "rejected", "reason": "busy_or_stale"}
        assert call.adapter.facts["name"] == "Ada"
        await call.adapter.close()

    asyncio.run(scenario())


def test_duplicate_call_and_close_during_delayed_action_cannot_commit_late_result():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.pilot_contract import PilotIdentity

        config = {
            "initial_node": "start",
            "variables": [{"key": "name", "type": "text"}],
            "nodes": [
                {"id": "start", "type": "initial", "data": {
                    "greeting": "", "waitForResponse": False,
                }},
                {"id": "name", "type": "collect_slot", "data": {
                    "slot": {"variableKey": "name", "prompt": "Your name?"},
                }},
                {"id": "lookup", "type": "api_request", "data": {"api": {
                    "apiSource": "custom", "method": "GET",
                    "url": "https://fixture.invalid/lookup", "timeout": 2,
                    "retryCount": 0,
                }}},
                {"id": "end", "type": "end", "data": {"closingMessage": "Done."}},
            ],
            "edges": [
                {"id": "start-name", "source": "start", "target": "name"},
                {"id": "name-lookup", "source": "name", "target": "lookup"},
                {"id": "lookup-ok", "source": "lookup", "target": "end",
                 "sourceHandle": "success"},
                {"id": "lookup-error", "source": "lookup", "target": "end",
                 "sourceHandle": "error"},
            ],
        }
        compiled = compile_flow(config, PilotIdentity(
            account_id="a", property_id="p", tool_id="t",
            flow_version_id="v", call_sid="c",
        ))
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def execute(node, facts, *, confirmation):
            assert facts == {"name": "Ada"}
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return NativeActionResult(True, variables={"name": "too_late"})

        call = GraphCall(compiled, execute_action=execute)
        await call.adapter.start()
        schema, = call.worker.tools.values()
        call.user_turn("Ada")
        active = asyncio.create_task(call.invoke_schema(schema, {"name": "Ada"}))
        await asyncio.wait_for(started.wait(), timeout=1)

        call.user_turn("Other")
        duplicate = await call.invoke_schema(schema, {"name": "Other"})
        assert duplicate == {"status": "rejected", "reason": "busy_or_stale"}
        await call.adapter.close()
        with pytest.raises(asyncio.CancelledError):
            await active
        assert cancelled.is_set()
        assert call.adapter.facts == {"name": "Ada"}
        assert "too_late" not in repr(call.adapter.facts)
        assert call.adapter.snapshot()["status"] == "closed"

    asyncio.run(scenario())


def test_revisit_budget_fails_visibly_before_reentering_a_wait_cycle():
    async def scenario():
        from botelier.voice.flows.native_execution import NativeTerminalResult
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.pilot_contract import PilotIdentity

        config = {
            "initial_node": "start",
            "variables": [{"key": "request", "type": "text"}],
            "nodes": [
                {"id": "start", "type": "initial", "data": {
                    "greeting": "", "waitForResponse": False,
                }},
                {"id": "request", "type": "collect_slot", "data": {
                    "slot": {"variableKey": "request", "prompt": "Again?"},
                }},
                {"id": "route", "type": "condition", "data": {
                    "condition": {
                        "variable": "request", "operator": "equals", "value": "again",
                    },
                }},
                {"id": "end", "type": "end", "data": {"closingMessage": "Done."}},
            ],
            "edges": [
                {"id": "start-request", "source": "start", "target": "request"},
                {"id": "request-route", "source": "request", "target": "route"},
                {"id": "route-repeat", "source": "route", "target": "request",
                 "sourceHandle": "true"},
                {"id": "route-end", "source": "route", "target": "end",
                 "sourceHandle": "false"},
            ],
        }
        compiled = compile_flow(config, PilotIdentity(
            account_id="a", property_id="p", tool_id="t",
            flow_version_id="v", call_sid="c",
        ))

        async def terminal(node, facts):
            return NativeTerminalResult(True, completed=False)

        call = GraphCall(compiled, terminal_handler=terminal)
        await call.adapter.start()
        for index in range(compiled.max_revisits + 1):
            schema, = call.worker.tools.values()
            call.user_turn("again")
            result = await call.invoke_schema(schema, {"request": "again"})
            if index < compiled.max_revisits:
                assert result["status"] == "accepted"
                assert call.adapter.snapshot()["status"] == "running"
            else:
                assert result == {"status": "error", "reason": "execution_budget"}
                assert call.adapter.snapshot()["status"] == "failed"
                assert call.adapter.snapshot()["failure_reason"] == "execution_budget"
                assert call.adapter.manager.current_node == "request"
        await call.adapter.close()

    asyncio.run(scenario())
