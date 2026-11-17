"""Unknown native action outcomes must not become another external write."""

import asyncio
from datetime import datetime, timedelta
import importlib
import importlib.util
import json
import uuid
from uuid import UUID

import pytest

from native_effect_io import NativeEffectsFixture


def ledger_api():
    name = "botelier.voice.flows.native_effect_ledger"
    assert importlib.util.find_spec(name) is not None, "Strict native effect deduplication is missing"
    return importlib.import_module(name)


def test_native_effect_fixture_is_disposable_owned_storage():
    async def scenario():
        async with NativeEffectsFixture() as fixture:
            db = fixture.factory()
            try:
                assert str(db.bind.url) == "sqlite://"
                assert db.query(fixture.effect_models["OperationIdempotency"]).count() == 0
                assert fixture.identity.account_id == fixture.account_id
            finally:
                db.close()
    asyncio.run(scenario())


def test_two_native_workers_share_a_claim_and_completed_result_without_plaintext_payloads():
    api = ledger_api()

    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult

        async with NativeEffectsFixture() as fixture:
            first = api.NativeEffectLedger(fixture.factory, fixture.identity)
            other = api.NativeEffectLedger(fixture.factory, fixture.identity)
            arguments = {"recipient": "guest@example.test", "body": "Private reservation"}
            claim = first.claim("send_link", arguments)
            assert claim.outcome == "execute"
            pending = other.claim("send_link", arguments)
            assert pending.outcome == "blocked"
            assert pending.failure_reason == "effect_outcome_unknown"
            result = NativeActionResult(
                True, variables={"delivery_status": "accepted"},
                llm_data={"delivery_status": "accepted"},
            )
            assert first.complete(claim, result, outcome_known=True)
            replay = other.claim("send_link", arguments)
            assert replay.outcome == "replay"
            assert replay.result.variables == result.variables
            db = fixture.factory()
            try:
                row = db.query(fixture.effect_models["OperationIdempotency"]).one()
                assert row.expires_at is None
                assert isinstance(row.result.get("sealed"), str)
                assert "accepted" not in json.dumps(row.result)
                assert "guest@example.test" not in json.dumps(row.result)
            finally:
                db.close()

    asyncio.run(scenario())


def test_expired_or_abandoned_native_claim_never_takes_over_an_ambiguous_write():
    api = ledger_api()

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            ledger = api.NativeEffectLedger(fixture.factory, fixture.identity)
            assert ledger.claim("booking", {"room": "r2"}).outcome == "execute"
            db = fixture.factory()
            try:
                row = db.query(fixture.effect_models["OperationIdempotency"]).one()
                row.updated_at = datetime.utcnow() - timedelta(days=30)
                db.commit()
            finally:
                db.close()
            blocked = api.NativeEffectLedger(fixture.factory, fixture.identity).claim("booking", {"room": "r2"})
            assert blocked.outcome == "blocked"
            assert blocked.failure_reason == "effect_outcome_unknown"

    asyncio.run(scenario())


def test_revised_arguments_cannot_reuse_an_old_action_result_or_repeat_the_write():
    api = ledger_api()

    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult

        async with NativeEffectsFixture() as fixture:
            ledger = api.NativeEffectLedger(fixture.factory, fixture.identity)
            claim = ledger.claim("send_link", {"recipient": "old@example.test"})
            assert ledger.complete(claim, NativeActionResult(True, variables={"status": "accepted"}), outcome_known=True)
            revised = ledger.claim("send_link", {"recipient": "new@example.test"})
            assert revised.outcome == "blocked"
            assert revised.failure_reason == "effect_arguments_changed"
            assert revised.result is None

    asyncio.run(scenario())


def test_claim_scope_mismatch_and_unreadable_results_fail_closed():
    api = ledger_api()

    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult

        async with NativeEffectsFixture() as fixture:
            ledger = api.NativeEffectLedger(fixture.factory, fixture.identity)
            claim = ledger.claim("send_link", {})
            assert ledger.complete(claim, NativeActionResult(True), outcome_known=True)
            db = fixture.factory()
            try:
                row = db.query(fixture.effect_models["OperationIdempotency"]).one()
                row.result = {"sealed": "corrupt synthetic ciphertext"}
                db.commit()
                blocked = ledger.claim("send_link", {})
                assert blocked.outcome == "blocked" and blocked.failure_reason == "effect_result_unavailable"
                row.account_id = UUID("00000000-0000-0000-0000-000000000999")
                db.commit()
                blocked = ledger.claim("send_link", {})
                assert blocked.outcome == "blocked" and blocked.failure_reason == "effect_scope_mismatch"
            finally:
                db.close()

    asyncio.run(scenario())


def test_failed_native_effect_replays_failure_without_automatic_retry():
    api = ledger_api()

    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult

        async with NativeEffectsFixture() as fixture:
            ledger = api.NativeEffectLedger(fixture.factory, fixture.identity)
            claim = ledger.claim("send_link", {})
            assert ledger.complete(
                claim, NativeActionResult(False, branch="error", failure_reason="delivery_rejected"),
                outcome_known=True,
            )
            replay = ledger.claim("send_link", {})
            assert replay.outcome == "replay"
            assert not replay.result.success
            assert replay.result.failure_reason == "delivery_rejected"

    asyncio.run(scenario())


def test_missing_durable_storage_is_a_blocker_not_an_in_memory_fallback():
    api = ledger_api()

    def unavailable():
        raise RuntimeError("Private storage connection context must not be returned")

    from botelier.voice.flows.pilot_contract import PilotIdentity
    from test_native_graph import IDENTITY_FIELDS

    ledger = api.NativeEffectLedger(unavailable, PilotIdentity(**IDENTITY_FIELDS))
    claim = ledger.claim("send_link", {})
    assert claim.outcome == "blocked"
    assert claim.failure_reason == "effect_storage_unavailable"


def test_same_call_switching_versions_cannot_create_a_second_effect_claim():
    api = ledger_api()

    async def scenario():
        from dataclasses import replace

        async with NativeEffectsFixture() as fixture:
            first = api.NativeEffectLedger(fixture.factory, fixture.identity)
            assert first.claim("booking", {"room": "r2"}).outcome == "execute"
            changed = replace(
                fixture.identity, flow_version_id="00000000-0000-0000-0000-000000000909",
            )
            later = api.NativeEffectLedger(fixture.factory, changed).claim("booking", {"room": "r2"})
            assert later.outcome == "blocked"
            assert later.failure_reason == "effect_scope_mismatch"

    asyncio.run(scenario())


def test_failed_transaction_cleanup_cannot_escape_with_private_infrastructure_details():
    api = ledger_api()

    class BrokenSession:
        def add(self, row):
            pass

        def commit(self):
            raise RuntimeError("private infrastructure commit")

        def rollback(self):
            raise RuntimeError("private infrastructure rollback")

        def close(self):
            raise RuntimeError("private infrastructure close")

    from botelier.voice.flows.pilot_contract import PilotIdentity
    from test_native_graph import IDENTITY_FIELDS

    ledger = api.NativeEffectLedger(BrokenSession, PilotIdentity(**IDENTITY_FIELDS))
    assert ledger.claim("send_link", {}).failure_reason == "effect_storage_unavailable"


def test_uuid_aliases_cannot_grant_two_claims_for_the_same_account_and_property():
    api = ledger_api()

    async def scenario():
        from dataclasses import replace

        async with NativeEffectsFixture() as fixture:
            lower = replace(
                fixture.identity,
                account_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                property_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            )
            upper = replace(lower, account_id=lower.account_id.upper(), property_id=lower.property_id.upper())
            assert api.NativeEffectLedger(fixture.factory, lower).claim("send_link", {}).outcome == "execute"
            assert api.NativeEffectLedger(fixture.factory, upper).claim("send_link", {}).outcome == "blocked"
            db = fixture.factory()
            try:
                assert db.query(fixture.effect_models["OperationIdempotency"]).count() == 1
            finally:
                db.close()

    asyncio.run(scenario())


def test_completion_requires_explicit_known_outcome_not_a_provider_reason_string():
    api = ledger_api()

    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult

        async with NativeEffectsFixture() as fixture:
            ledger = api.NativeEffectLedger(fixture.factory, fixture.identity)
            claim = ledger.claim("send_link", {})
            result = NativeActionResult(False, branch="error", failure_reason="provider_timeout")
            assert not ledger.complete(claim, result)
            assert ledger.claim("send_link", {}).failure_reason == "effect_outcome_unknown"

    asyncio.run(scenario())


def test_completion_checks_claim_token_arguments_scope_and_can_commit_only_once():
    api = ledger_api()

    async def scenario():
        from dataclasses import replace
        from botelier.voice.flows.native_execution import NativeActionResult

        async with NativeEffectsFixture() as fixture:
            ledger = api.NativeEffectLedger(fixture.factory, fixture.identity)
            claim = ledger.claim("send_link", {})
            result = NativeActionResult(True)
            for tampered in (
                replace(claim, token="00000000-0000-0000-0000-000000000999"),
                replace(claim, args_hash="not-the-arguments"),
                replace(claim, key="not-the-key"),
                replace(claim, node_id="other_node"),
            ):
                assert not ledger.complete(tampered, result, outcome_known=True)
            other = api.NativeEffectLedger(fixture.factory, replace(
                fixture.identity, property_id="00000000-0000-0000-0000-000000000909",
            ))
            assert not other.complete(claim, result, outcome_known=True)
            assert ledger.complete(claim, result, outcome_known=True)
            assert not ledger.complete(claim, result, outcome_known=True)
            assert ledger.claim("send_link", {}).outcome == "replay"

    asyncio.run(scenario())


def test_completion_storage_and_encryption_failures_leave_pending_claim(monkeypatch):
    api = ledger_api()

    async def scenario():
        import botelier.crypto
        from botelier.voice.flows.native_execution import NativeActionResult

        async with NativeEffectsFixture() as fixture:
            ledger = api.NativeEffectLedger(fixture.factory, fixture.identity)
            original_factory = ledger.session_factory

            class BrokenCipher:
                def encrypt(self, value):
                    raise RuntimeError("private encryption context")

            for mode in ("factory", "query", "commit", "encryption"):
                claim = ledger.claim(f"send_{mode}", {})
                assert claim.outcome == "execute"
                if mode == "factory":
                    def broken_factory():
                        raise RuntimeError("private storage context")
                    ledger.session_factory = broken_factory
                elif mode in {"query", "commit"}:
                    def broken_factory(mode=mode):
                        session = original_factory()
                        def fail(*args, **kwargs):
                            raise RuntimeError("private transaction context")
                        setattr(session, mode, fail)
                        return session
                    ledger.session_factory = broken_factory
                try:
                    with monkeypatch.context() as context:
                        if mode == "encryption":
                            context.setattr(botelier.crypto, "get_cipher", lambda: BrokenCipher())
                        assert not ledger.complete(claim, NativeActionResult(True), outcome_known=True)
                finally:
                    ledger.session_factory = original_factory
                assert ledger.claim(f"send_{mode}", {}).failure_reason == "effect_outcome_unknown"

    asyncio.run(scenario())


def test_cancelled_completion_propagates_cancellation_closes_session_and_never_reopens_claim():
    api = ledger_api()

    async def scenario():
        from botelier.voice.flows.native_execution import NativeActionResult

        async with NativeEffectsFixture() as fixture:
            ledger = api.NativeEffectLedger(fixture.factory, fixture.identity)
            claim = ledger.claim("send_link", {})
            closed = []

            def cancelled_factory():
                session = fixture.factory()
                original_close = session.close
                def cancel():
                    raise asyncio.CancelledError()
                def close():
                    closed.append(True)
                    original_close()
                session.commit = cancel
                session.close = close
                return session

            ledger.session_factory = cancelled_factory
            with pytest.raises(asyncio.CancelledError):
                ledger.complete(claim, NativeActionResult(True), outcome_known=True)
            assert closed == [True]
            ledger.session_factory = fixture.factory
            assert ledger.claim("send_link", {}).failure_reason == "effect_outcome_unknown"

    asyncio.run(scenario())


def test_claim_encryption_preflight_failure_never_opens_storage_or_grants_a_write(monkeypatch):
    api = ledger_api()

    async def scenario():
        import botelier.crypto

        async with NativeEffectsFixture() as fixture:
            opened = []

            def counted_factory():
                opened.append(True)
                return fixture.factory()

            class BrokenCipher:
                def encrypt(self, value):
                    raise RuntimeError("private encryption context")

            ledger = api.NativeEffectLedger(counted_factory, fixture.identity)
            with monkeypatch.context() as context:
                context.setattr(botelier.crypto, "get_cipher", lambda: BrokenCipher())
                claim = ledger.claim("send_link", {})
            assert claim.outcome == "blocked"
            assert claim.failure_reason == "effect_storage_unavailable"
            assert not opened
            db = fixture.factory()
            try:
                assert db.query(fixture.effect_models["OperationIdempotency"]).count() == 0
            finally:
                db.close()

    asyncio.run(scenario())


def test_accepted_http_write_with_missing_required_mapping_stays_pending(monkeypatch):
    async def scenario():
        import httpx

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
            await runner.close()
            await preview_runner.close()

    asyncio.run(scenario())


def test_effect_receipts_are_scoped_to_entered_tool_and_published_version(monkeypatch):
    async def scenario():
        import httpx

        async with NativeEffectsFixture() as fixture:
            from botelier.models.flow_version import FlowVersion, FlowVersionStatus
            from botelier.models.operation_idempotency import OperationIdempotency
            from botelier.models.tool import Tool, ToolType
            from botelier.services.ssrf_safe_transport import SSRFSafeTransport
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow
            from botelier.voice.flows.pilot_contract import PilotIdentity

            child_tool_id = str(uuid.uuid4())
            child_version_id = str(uuid.uuid4())
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
            db = fixture.factory()
            db.add(Tool(
                id=child_tool_id, name="Alternate write", description="Scoped test",
                tool_type=ToolType.FLOW, config=config,
                tool_set_id=UUID("00000000-0000-0000-0000-000000000105"),
                published_version_id=UUID(child_version_id),
                published_version_number=1,
            ))
            db.add(FlowVersion(
                id=UUID(child_version_id), tool_id=child_tool_id,
                version_number=1, status=FlowVersionStatus.PUBLISHED,
                flow_config=config,
            ))
            db.commit()
            db.close()

            identity = fixture.identity
            child_identity = PilotIdentity(
                account_id=identity.account_id,
                property_id=identity.property_id,
                tool_id=child_tool_id,
                flow_version_id=child_version_id,
                call_sid=identity.call_sid,
            )
            root_flow = compile_flow(config, identity)
            child_flow = compile_flow(config, child_identity)
            root_runner = NativeActionRunner(root_flow, fixture.factory)
            child_runner = NativeActionRunner(child_flow, fixture.factory)
            requests = []

            async def controlled_transport(_transport, request):
                requests.append(request)
                return httpx.Response(
                    200, json={"reference": "fixture-receipt"}, request=request,
                )

            monkeypatch.setattr(
                SSRFSafeTransport, "handle_async_request", controlled_transport,
            )
            facts = {"amount": 12}
            root_consent = NativeConfirmation(
                "confirm", 2, json.dumps(facts), ("amount",),
            )
            child_consent = NativeConfirmation(
                "confirm", 3, json.dumps(facts), ("amount",),
            )
            try:
                root_result = await root_runner.execute(
                    root_flow.node("write"), facts, confirmation=root_consent,
                )
                child_result = await child_runner.execute(
                    child_flow.node("write"), facts, confirmation=child_consent,
                )
                root_replay = await root_runner.execute(
                    root_flow.node("write"), facts, confirmation=root_consent,
                )
                assert root_result.success and child_result.success
                assert root_replay.success
                assert len(requests) == 2
                db = fixture.factory()
                receipts = db.query(OperationIdempotency).all()
                assert len(receipts) == 2
                operations = {row.operation for row in receipts}
                assert len(operations) == 2
                assert all(item.startswith("native:write:") for item in operations)
                assert len({row.idempotency_key for row in receipts}) == 2
                assert all(row.status == "succeeded" for row in receipts)
                db.close()
            finally:
                await root_runner.close()
                await child_runner.close()

    asyncio.run(scenario())
