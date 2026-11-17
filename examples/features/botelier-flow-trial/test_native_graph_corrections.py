"""Actual serialized native conversation corrections, without providers."""

import asyncio

import pytest

from native_graph_text_io import NativeGraphTextFixture
from native_graph_io import simple_flow_config
from node_contract_io import tool_delta


def correction_flow():
    definition = simple_flow_config()
    definition["variables"].extend([
        {"key": "email", "type": "email"},
        {"key": "prepared_link", "type": "text"},
    ])
    definition["nodes"].extend([
        {"id": "email", "type": "collect_slot", "data": {
            "slot": {"variableKey": "email", "type": "email", "prompt": "What is your email?"},
        }},
        {"id": "prepare", "type": "set_variable", "data": {
            "setVariable": {
                "variableKey": "prepared_link", "valueType": "template",
                "value": "draft-{{name}}",
            },
        }},
        {"id": "confirm", "type": "confirmation", "data": {
            "confirmation": {
                "summaryTemplate": "You said {{name}}, {{email}}.",
                "confirmPrompt": "Are these details correct?",
                "variablesToConfirm": ["name", "email", "prepared_link"],
                "allowEdit": True, "editPrompt": "What should change?",
                "deliveryMode": "static",
            },
        }},
        {"id": "edit_name", "type": "collect_slot", "data": {
            "slot": {"variableKey": "name", "prompt": "What name should I use instead?"},
        }},
    ])
    definition["edges"] = [
        {"id": "start-name", "source": "start", "target": "name"},
        {"id": "name-email", "source": "name", "target": "email"},
        {"id": "email-prepare", "source": "email", "target": "prepare"},
        {"id": "prepare-confirm", "source": "prepare", "target": "confirm"},
        {"id": "confirm-edit", "source": "confirm", "sourceHandle": "edit", "target": "edit_name"},
        {"id": "edit-prepare", "source": "edit_name", "target": "prepare"},
        {"id": "confirm-done", "source": "confirm", "sourceHandle": "confirmed", "target": "done"},
    ]
    return definition


def test_edit_keeps_unrelated_caller_facts_and_invalidates_prepared_outputs():
    async def scenario():
        async with NativeGraphTextFixture([
            tool_delta("collect_name", {"name": "Ada"}),
            tool_delta("collect_email", {"email": "guest@example.invalid"}),
            tool_delta("collect_confirm", {"response": "edit"}),
            tool_delta("collect_edit_name", {"name": "Grace"}),
            tool_delta("collect_confirm", {"response": "yes"}),
        ], definition=correction_flow()) as fixture:
            await fixture.host.start()
            await fixture.host.send("My name is Ada.")
            await fixture.host.send("My email is guest@example.invalid.")
            assert fixture.host.adapter.facts["prepared_link"] == "draft-Ada"

            changed = await fixture.host.send("Edit.")
            assert fixture.host.snapshot()["current_node"] == "edit_name"
            assert fixture.host.adapter.facts["email"] == "guest@example.invalid"
            assert "prepared_link" not in fixture.host.adapter.facts
            assert fixture.host.adapter._confirmation is None
            assert [message["content"] for message in changed["messages"]] == [
                "What name should I use instead?",
            ]

            await fixture.host.send("Use Grace instead.")
            assert fixture.host.adapter.facts == {
                "name": "Grace", "email": "guest@example.invalid",
                "prepared_link": "draft-Grace",
            }
            completed = await fixture.host.send("Yes.")
            assert fixture.host.snapshot()["is_complete"] is True
            assert [message["content"] for message in completed["messages"]] == ["Thanks, Grace."]
            assert len(fixture.providers.requests) == 5
            assert fixture.providers.business_requests == []

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_polite_complete_confirmation_does_not_require_repeating_literal_yes():
    async def scenario():
        async with NativeGraphTextFixture([
            tool_delta("collect_name", {"name": "Ada"}),
            tool_delta("collect_email", {"email": "guest@example.invalid"}),
            tool_delta("collect_confirm", {"response": "yes"}),
            "Please confirm yes or no.",
        ], definition=correction_flow()) as fixture:
            await fixture.host.start()
            await fixture.host.send("My name is Ada.")
            await fixture.host.send("My email is guest@example.invalid.")
            result = await fixture.host.send("Yes, please.")
            assert fixture.host.snapshot()["is_complete"] is True
            assert [message["content"] for message in result["messages"]] == ["Thanks, Ada."]
            assert len(fixture.providers.requests) == 3

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_natural_edit_request_only_enters_the_configured_nonmutating_edit_branch():
    async def scenario():
        async with NativeGraphTextFixture([
            tool_delta("collect_name", {"name": "Ada"}),
            tool_delta("collect_email", {"email": "guest@example.invalid"}),
            tool_delta("collect_confirm", {"response": "edit"}),
            "Please say edit if you need a change.",
        ], definition=correction_flow()) as fixture:
            await fixture.host.start()
            await fixture.host.send("My name is Ada.")
            await fixture.host.send("My email is guest@example.invalid.")
            await fixture.host.send("I need to change my name.")
            assert fixture.host.snapshot()["current_node"] == "edit_name"
            assert fixture.host.adapter._confirmation is None
            assert fixture.host.adapter.facts["email"] == "guest@example.invalid"
            assert "prepared_link" not in fixture.host.adapter.facts
            assert len(fixture.providers.requests) == 3
            assert fixture.providers.business_requests == []

    asyncio.run(asyncio.wait_for(scenario(), 15))


@pytest.mark.parametrize(("caller", "answer", "allowed"), [
    ("Yes, please.", "yes", True),
    ("Absolutely!", "yes", True),
    ("Yes, but change the dates.", "yes", False),
    ("Yes please, but only if it costs less.", "yes", False),
    ("No, not yes.", "yes", False),
    ("Absolutely not.", "yes", False),
    ("Do not change anything.", "yes", False),
    ("Yes or no?", "yes", False),
    ("No, thank you.", "no", True),
])
def test_consent_matches_whole_safe_phrases_not_positive_substrings(caller, answer, allowed):
    from botelier.voice.flows.native_adapter import NativeFlowAdapter

    assert NativeFlowAdapter._same_confirmation(caller, answer) is allowed
