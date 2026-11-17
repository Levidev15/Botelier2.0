"""General native graph through real model SDK, aggregators and text host."""

import asyncio

import pytest

from native_graph_text_io import NativeGraphTextFixture
from native_dev_voice_io import ALT_TOOL_ID, NativeDevRecords, TOOL_ID, VERSION_ID
from node_contract_io import tool_delta
from pilot_io import PilotProviders


class _HeldModelProviders(PilotProviders):
    def __init__(self, replies):
        super().__init__(replies)
        self.request_started = asyncio.Event()
        self.release_request = asyncio.Event()
        self.request_cancelled = False

    async def http(self, request):
        if str(request.url) == "https://api.openai.com/v1/chat/completions":
            self.request_started.set()
            try:
                await self.release_request.wait()
            except asyncio.CancelledError:
                self.request_cancelled = True
                raise
        return await super().http(request)

    def release_blocked_io(self):
        self.release_request.set()
        super().release_blocked_io()


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


def test_text_host_waits_for_successful_consumer_ack_after_real_context_fence():
    async def scenario():
        async with NativeGraphTextFixture() as fixture:
            original_build = fixture.host._build_pipeline
            acknowledgements = 0

            def build_with_delayed_ack():
                nonlocal acknowledgements
                original_build()
                adapter = fixture.host.adapter
                original_ack = adapter.acknowledge_consumed_node

                def acknowledge():
                    nonlocal acknowledgements
                    acknowledgements += 1
                    if acknowledgements == 1:
                        # Simulate the SDK's first downstream/context fence
                        # completing before the manager reports the entered
                        # replacement node. A later real state-change signal
                        # permits a second acknowledgment attempt.
                        asyncio.get_running_loop().call_later(
                            0.01, fixture.host._changed.set,
                        )
                        return False
                    return original_ack()

                adapter.acknowledge_consumed_node = acknowledge

            fixture.host._build_pipeline = build_with_delayed_ack
            result = await fixture.host.start()
            assert acknowledgements >= 2
            assert [item["content"] for item in result["messages"]] == [
                "Welcome to the fixture.", "What is your name?",
            ]
            assert fixture.host.snapshot()["pending_slot"] == "name"

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


def test_text_host_alternate_action_uses_entered_flow_runner_and_closes_both():
    async def scenario():
        from botelier.voice.flows.native_graph import compile_flow
        from botelier.voice.flows.pilot_contract import PilotIdentity

        records = NativeDevRecords(extra_published_flow=True)
        root_identity = PilotIdentity(
            account_id=records.assistant.account_id,
            property_id=records.assistant.property_id,
            tool_id=TOOL_ID, flow_version_id=VERSION_ID,
            call_sid="offline-text-alternate-action",
        )
        child_version = records.rows["AdditionalFlowVersions"][0]
        child_identity = PilotIdentity(
            account_id=root_identity.account_id,
            property_id=root_identity.property_id,
            tool_id=ALT_TOOL_ID, flow_version_id=str(child_version.id),
            call_sid=root_identity.call_sid,
        )
        root = compile_flow(records.rows["FlowVersion"].flow_config, root_identity)
        child = compile_flow(child_version.flow_config, child_identity)
        available_flows = {
            ALT_TOOL_ID: {
                "compiled": child, "name": "Alternate fixture",
                "description": "Alternate flow",
            },
        }
        providers = PilotProviders([
            tool_delta("collect_select_flow", {"tool_id": ALT_TOOL_ID}),
            tool_delta("collect_query", {"query": "alternate"}),
        ])
        async with NativeGraphTextFixture(
            providers=providers,
            definition=records.rows["FlowVersion"].flow_config,
            identity=root_identity,
            available_flows=available_flows,
            session_factory=records.session,
        ) as fixture:
            assert root.node("lookup").node_id == child.node("lookup").node_id
            await fixture.host.start()
            selection = await fixture.host.send("Use the alternate fixture workflow.")
            assert "Alternate workflow." in " ".join(
                item["content"] for item in selection["messages"]
            )
            assert fixture.host.adapter.compiled is child
            assert fixture.host.adapter.execute_action.__self__ is (
                fixture.host._action_runners[ALT_TOOL_ID]
            )
            result = await fixture.host.send("Find the alternate fixture.")
            assert fixture.host.adapter.compiled is child
            assert fixture.host.adapter.execute_action.__self__ is (
                fixture.host._action_runners[ALT_TOOL_ID]
            )
            assert fixture.host.snapshot()["current_node"] == "failure"
            assert "The fixture service is unavailable." in " ".join(
                item["content"] for item in result["messages"]
            )
            assert providers.business_requests == []
            assert all(session.closed for session in records.sessions)
            await fixture.host.close()
            assert all(runner._closed for runner in fixture.host._action_runners.values())

    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_text_host_rejects_overlapping_send_and_allows_original_turn_to_finish():
    async def scenario():
        providers = _HeldModelProviders([
            tool_delta("collect_name", {"name": "Ada"}),
        ])
        async with NativeGraphTextFixture(providers=providers) as fixture:
            host = fixture.host
            await host.start()
            first_turn = asyncio.create_task(host.send("My name is Ada."))
            await asyncio.wait_for(providers.request_started.wait(), 2)
            with pytest.raises(host.error_type) as error:
                await host.send("This overlapping turn must not be queued.")
            assert error.value.code == "busy"
            assert not host.closed
            providers.release_request.set()
            result = await asyncio.wait_for(first_turn, 5)
            assert result["messages"][-1]["content"] == "Thanks, Ada."
            assert host.snapshot()["collected_slots"] == {"name": "Ada"}
            assert len(providers.requests) == 1

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_text_host_provider_turn_timeout_cancels_request_and_closes_worker():
    async def scenario():
        providers = _HeldModelProviders([
            tool_delta("collect_name", {"name": "Ada"}),
        ])
        async with NativeGraphTextFixture(
            providers=providers, turn_timeout=0.05,
        ) as fixture:
            host = fixture.host
            await host.start()
            turn = asyncio.create_task(host.send("My name is Ada."))
            await asyncio.wait_for(providers.request_started.wait(), 2)
            with pytest.raises(host.error_type) as error:
                await asyncio.wait_for(turn, 3)
            assert error.value.code == "timeout"
            assert providers.request_cancelled
            assert host.closed
            assert host._runner_task.done()

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_text_host_startup_cancellation_closes_adapter_and_owned_runner():
    async def scenario():
        async with NativeGraphTextFixture() as fixture:
            host = fixture.host
            entered = asyncio.Event()
            never = asyncio.Event()
            original_build = host._build_pipeline

            def build_with_held_adapter_start():
                original_build()
                original_start = host.adapter.start

                async def held_start():
                    entered.set()
                    await never.wait()
                    return await original_start()

                host.adapter.start = held_start

            host._build_pipeline = build_with_held_adapter_start
            starting = asyncio.create_task(host.start())
            await asyncio.wait_for(entered.wait(), 3)
            starting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await starting
            assert host.closed
            assert host.adapter.closed
            assert host._runner_task.done()
            assert all(runner._closed for runner in host._action_runners.values())

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_text_host_turn_cancellation_closes_worker_and_cancels_provider_request():
    async def scenario():
        providers = _HeldModelProviders([
            tool_delta("collect_name", {"name": "Ada"}),
        ])
        async with NativeGraphTextFixture(providers=providers) as fixture:
            host = fixture.host
            await host.start()
            turn = asyncio.create_task(host.send("My name is Ada."))
            await asyncio.wait_for(providers.request_started.wait(), 2)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
            assert providers.request_cancelled
            assert host.closed and host._runner_task.done()

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_text_hosts_keep_independent_state_when_one_host_closes():
    async def scenario():
        providers = PilotProviders([
            tool_delta("collect_name", {"name": "Ada"}),
            tool_delta("collect_name", {"name": "Grace"}),
        ])
        async with NativeGraphTextFixture(providers=providers) as fixture:
            first = fixture.host
            second = await fixture.make_host("offline-text-independent-host")
            await first.start()
            first_result = await first.send("My name is Ada.")
            assert first_result["messages"][-1]["content"] == "Thanks, Ada."
            assert first.snapshot()["collected_slots"] == {"name": "Ada"}
            assert second.snapshot()["collected_slots"] == {}
            await first.close()
            second_result = await second.send("My name is Grace.")
            assert second_result["messages"][-1]["content"] == "Thanks, Grace."
            assert second.snapshot()["collected_slots"] == {"name": "Grace"}
            assert not second.closed

    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_text_host_unsupported_provider_rejection_closes_without_starting():
    async def scenario():
        async with NativeGraphTextFixture() as fixture:
            host = fixture.host
            host.config.llm_provider = "unsupported-provider"
            with pytest.raises(host.error_type) as error:
                await host.start()
            assert error.value.code == "unsupported_provider"
            assert host.closed
            assert host._worker is None
            assert fixture.providers.requests == []

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_text_host_initialization_failure_closes_partially_owned_runners(monkeypatch):
    async def scenario():
        import botelier.voice.flows.native_text_host as native_text_host

        async with NativeGraphTextFixture() as fixture:
            host = fixture.host

            def fail_adapter(*_args, **_kwargs):
                raise RuntimeError("synthetic adapter construction failure")

            monkeypatch.setattr(native_text_host, "NativeFlowAdapter", fail_adapter)
            with pytest.raises(host.error_type) as error:
                await host.start()
            assert error.value.code == "initialization"
            assert host.closed
            assert host.adapter is None
            assert host._runner_task is None
            assert host._action_runners
            assert all(runner._closed for runner in host._action_runners.values())

    asyncio.run(asyncio.wait_for(scenario(), 15))
