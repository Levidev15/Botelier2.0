import asyncio
import json

import httpx


def test_accepted_http_write_with_missing_required_mapping_stays_pending(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow

            requests = []

            async def controlled_transport(_transport, request):
                requests.append(request)
                return httpx.Response(200, json={}, request=request)

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "amount", "type": "number"},
                    {"key": "reference", "type": "text"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "confirm", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Confirm {{amount}}.",
                            "confirmPrompt": "Proceed?",
                            "variablesToConfirm": ["amount"],
                            "allowEdit": False,
                        },
                    }},
                    {"id": "write", "type": "api_request", "data": {"api": {
                        "apiSource": "custom", "method": "POST",
                        "url": "https://api.fixture.invalid/reserve",
                        "bodyTemplate": '{"amount":{{amount}}}',
                        "responseMapping": {"reference": "$.reference"},
                        "timeout": 2, "retryCount": 0,
                    }}},
                    {"id": "done", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [
                    {"id": "start-confirm", "source": "start", "target": "confirm"},
                    {"id": "confirmed-write", "source": "confirm", "target": "write",
                     "sourceHandle": "confirmed"},
                    {"id": "write-done", "source": "write", "target": "done",
                     "sourceHandle": "success"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            facts = {"amount": 0}
            consent = NativeConfirmation(
                "confirm", 2, json.dumps(facts), ("amount",),
            )

            denied = await runner.execute(compiled.node("write"), facts)
            assert denied.failure_reason == "confirmation_required"
            assert requests == []
            preview_runner = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            preview_denied = await preview_runner.execute(
                compiled.node("write"), facts,
            )
            assert preview_denied.failure_reason == "confirmation_required"
            preview = await preview_runner.execute(
                compiled.node("write"), facts, confirmation=consent,
            )
            assert preview.failure_reason == "preview_required"
            assert requests == []
            first = await runner.execute(
                compiled.node("write"), facts, confirmation=consent,
            )
            second = await runner.execute(
                compiled.node("write"), facts, confirmation=consent,
            )
            assert first.failure_reason == "effect_outcome_unknown"
            assert second.failure_reason == "effect_outcome_unknown"
            assert len(requests) == 1

    asyncio.run(scenario())
