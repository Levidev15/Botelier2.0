"""General native graph through real model SDK, aggregators and text host."""

import asyncio

from native_graph_text_io import NativeGraphTextFixture
from node_contract_io import tool_delta


def test_general_text_host_uses_native_graph_and_records_each_prompt_exactly_once():
    async def scenario():
        from botelier.voice.flows.native_adapter import NativeFlowAdapter

        async with NativeGraphTextFixture() as fixture:
            result = await fixture.host.start()
            assert isinstance(fixture.host.adapter, NativeFlowAdapter)
            assert [item["content"] for item in result["messages"]] == [
                "Welcome to the fixture.", "What is your name?",
            ]
            assert fixture.providers.requests == []
            assert fixture.providers.business_requests == []
            history = [
                item["content"] for item in fixture.host.context.get_messages()
                if item.get("role") == "assistant" and isinstance(item.get("content"), str)
            ]
            assert history == ["Welcome to the fixture.", "What is your name?"]
            assert fixture.host.snapshot()["current_node"] == "name"
            assert fixture.host.snapshot()["pending_slot"] == "name"
            assert fixture.host.snapshot()["is_complete"] is False

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_general_text_host_finishes_truthfully_at_end_without_audio_or_carrier():
    async def scenario():
        async with NativeGraphTextFixture([
            tool_delta("collect_name", {"name": "Ada"}),
        ]) as fixture:
            await fixture.host.start()
            result = await fixture.host.send("My name is Ada.")
            assert [item["content"] for item in result["messages"]] == ["Thanks, Ada."]
            snapshot = fixture.host.snapshot()
            assert snapshot["current_node"] == "done"
            assert snapshot["collected_slots"] == {"name": "Ada"}
            assert snapshot["is_complete"] is True
            assert snapshot["progress"] == {"collected": 1, "total": 1, "percentage": 100}
            assert fixture.host.adapter.snapshot()["status"] == "completed"
            assert len(fixture.providers.requests) == 1
            assert fixture.providers.business_requests == []

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_guided_start_speech_finishes_and_advances_before_start_response_returns():
    async def scenario():
        from native_graph_io import simple_flow_config

        definition = simple_flow_config()
        definition["nodes"].insert(1, {
            "id": "explain", "type": "message", "data": {
                "message": "The fixture is ready.", "deliveryMode": "guided",
                "waitForResponse": False,
            },
        })
        definition["edges"][0]["target"] = "explain"
        definition["edges"].append({"id": "explain-name", "source": "explain", "target": "name"})
        async with NativeGraphTextFixture(
            ["The fixture is ready."], definition=definition,
        ) as fixture:
            result = await fixture.host.start()
            assert [item["content"] for item in result["messages"]] == [
                "Welcome to the fixture.", "The fixture is ready.", "What is your name?",
            ]
            assert fixture.host.snapshot()["current_node"] == "name"
            assert fixture.host._model_inflight == 0
            assert fixture.host._response_ends == 1
            history = [
                item["content"] for item in fixture.host.context.get_messages()
                if item.get("role") == "assistant" and isinstance(item.get("content"), str)
            ]
            assert history == [
                "Welcome to the fixture.", "The fixture is ready.", "What is your name?",
            ]

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_confirmation_rejection_can_be_retried_without_repeating_the_node():
    async def scenario():
        from native_graph_io import simple_flow_config

        definition = simple_flow_config()
        definition["nodes"].insert(-1, {
            "id": "confirm", "type": "confirmation", "data": {
                "confirmation": {
                    "summaryTemplate": "You said {{name}}.",
                    "confirmPrompt": "Please say yes or no.",
                    "variablesToConfirm": ["name"],
                    "allowEdit": False, "deliveryMode": "static",
                },
            },
        })
        next(edge for edge in definition["edges"] if edge["source"] == "name")["target"] = "confirm"
        definition["edges"].append({
            "id": "confirm-done", "source": "confirm", "target": "done",
            "sourceHandle": "confirmed",
        })
        qualified = tool_delta("collect_confirm", {"response": "yes"})
        qualified["tool_calls"][0]["id"] = "qualified-confirmation"
        agreed = tool_delta("collect_confirm", {"response": "yes"})
        agreed["tool_calls"][0]["id"] = "current-confirmation"
        async with NativeGraphTextFixture([
            tool_delta("collect_name", {"name": "Ada"}),
            qualified,
            "Please confirm yes or no.",
            agreed,
        ], definition=definition) as fixture:
            await fixture.host.start()
            await fixture.host.send("My name is Ada.")
            rejected = await fixture.host.send("Yes, but change the name.")
            assert fixture.host.snapshot()["current_node"] == "confirm"
            assert fixture.host.adapter._confirmation is None
            assert [item["content"] for item in rejected["messages"]] == [
                "Please confirm yes or no.",
            ]
            assert len(fixture.providers.requests) == 3

            accepted = await fixture.host.send("Yes!")
            assert fixture.host.snapshot()["is_complete"] is True
            # The completed terminal entry must not retain reusable consent.
            assert fixture.host.adapter._confirmation is None
            assert fixture.host.snapshot()["collected_slots"] == {"name": "Ada"}
            assert [item["content"] for item in accepted["messages"]] == ["Thanks, Ada."]
            assert len(fixture.providers.requests) == 4
            assert fixture.providers.business_requests == []

    asyncio.run(asyncio.wait_for(scenario(), 15))
