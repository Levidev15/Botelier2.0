"""Compiled, offline quote-delivery coverage through the native action broker."""

import asyncio
from copy import deepcopy
from datetime import timedelta
import html
from types import SimpleNamespace
import threading
import uuid


def _delivery_definition(identity, tool_id, tool_type):
    from test_native_quote_actions import configuration
    from test_native_quote_bridge import quote_definition
    from botelier.voice.flows.native_graph import compile_flow

    source = quote_definition()
    recipient_variable = "caller_email" if tool_type == "SEND_EMAIL" else "caller_phone"
    if tool_type == "SEND_EMAIL":
        source["variables"].append({"key": recipient_variable, "type": "email"})
    confirmation_fields = [
        *configuration()["quotePolicy"]["publicConfirmationFields"].values(),
        "quote_fingerprint", recipient_variable,
    ]
    confirmation = {
        "summaryTemplate": (
            "Room {{quote_room}}, {{quote_check_in}} to {{quote_check_out}}, "
            "total {{quote_total}} {{quote_currency}}. Send the review link?"
        ),
        "confirmPrompt": "Should I send the reservation quote?",
        "variablesToConfirm": confirmation_fields,
        "allowEdit": False,
    }
    if tool_type == "SEND_EMAIL":
        arguments = (
            '{"recipient":"{{caller_email}}","subject":"Reservation quote",'
            '"body":"Review <room> & reservation:\\n{{private_checkout_url}}"}'
        )
    else:
        arguments = (
            '{"recipient":"{{caller_phone}}",'
            '"body":"Review your selected reservation:\\n{{private_checkout_url}}"}'
        )
    delivery = {
        "apiSource": "tool", "toolId": tool_id,
        "argumentsTemplate": arguments,
        "quoteDelivery": {
            "quoteNodeId": "quote", "recipientVariable": recipient_variable,
        },
    }
    source["nodes"] = [
        source["nodes"][0], source["nodes"][1],
        {"id": "confirm", "type": "confirmation", "data": {
            "confirmation": confirmation,
        }},
        {"id": "delivery", "type": "api_request", "data": {"api": delivery}},
        {"id": "done", "type": "end", "data": {"closingMessage": ""}},
    ]
    source["edges"] = [
        {"id": "start-quote", "source": "start", "target": "quote"},
        {"id": "quote-confirm", "source": "quote", "target": "confirm",
         "sourceHandle": "success"},
        {"id": "confirm-delivery", "source": "confirm", "target": "delivery",
         "sourceHandle": "confirmed"},
        {"id": "delivery-done", "source": "delivery", "target": "done",
         "sourceHandle": "success"},
    ]
    return compile_flow(source, identity)


def _add_tool_and_sender(fixture, tool_id, tool_type):
    from botelier.models.tool import Tool, ToolType

    db = fixture.factory()
    flow = db.query(Tool).filter(Tool.id == fixture.tool_id).first()
    connection_id = None
    try:
        if tool_type == "SEND_EMAIL":
            from botelier.models.integration import (
                AccountIntegration, IntegrationStatus, IntegrationType,
            )

            integration_type = IntegrationType(
                id=uuid.uuid4(), slug="email-sender-gmail",
                name="Synthetic email sender", provider="google",
                category="email_sender", is_enabled=True,
            )
            connection_id = uuid.uuid4()
            connection = AccountIntegration(
                id=connection_id, account_id=uuid.UUID(fixture.account_id),
                property_id=uuid.UUID(fixture.property_id),
                integration_type=integration_type,
                connection_name="Synthetic quote sender",
                status=IntegrationStatus.CONNECTED, connection_config="{}",
            )
            db.add(connection)
            tool_config = {"connection_id": str(connection_id)}
        else:
            tool_config = {}
        db.add(Tool(
            id=tool_id, name="Synthetic quote delivery",
            description="Offline saved messaging tool",
            tool_type=ToolType[tool_type], config=tool_config,
            tool_set_id=flow.tool_set_id, is_active="true",
        ))
        db.commit()
    finally:
        db.close()
    return str(connection_id) if connection_id else None


def _confirmed_facts(recipient_variable, *, email=False):
    from test_native_quote_actions import caller_facts, configuration
    from test_reservation_quote_contract import NOW
    from botelier.voice.flows.native_execution import NativeConfirmation
    from botelier.voice.flows.native_quote_actions import prepare_quote

    facts = caller_facts()
    facts["caller_email"] = "guest@example.invalid"
    if email:
        facts["provider_quote"]["checkout_url"] += "&mode=review"
    prepared = prepare_quote(configuration(), facts, now=NOW)
    facts.update(prepared.result.variables)
    confirmed_fields = (
        *prepared.policy.public_confirmation_variables,
        prepared.policy.fingerprint_variable, recipient_variable,
    )
    confirmation = NativeConfirmation(
        "confirm", 7,
        {key: facts[key] for key in confirmed_fields},
        confirmed_fields,
    )
    return facts, confirmation


def _fixed_quote_clock(monkeypatch, clock):
    from botelier.voice.flows import native_quote_actions

    original = native_quote_actions.validate_reservation_quote

    def fixed_clock(quote, **kwargs):
        if kwargs.get("now") is None:
            kwargs["now"] = clock[0]
        return original(quote, **kwargs)

    monkeypatch.setattr(native_quote_actions, "validate_reservation_quote", fixed_clock)


def _use_vetted_offline_sentence_assets():
    """Use the candidate's vetted offline tokenizer data without downloading."""
    from pathlib import Path

    import nltk.data

    assets = (
        Path(__file__).resolve().parents[3]
        / "generated-artifacts/voice-pilot/offline-assets/nltk_data"
    ).resolve()
    english_tab = assets / "tokenizers/punkt_tab/english/abbrev_types.txt"
    if not english_tab.is_file():
        raise RuntimeError("The vetted offline NLTK sentence assets are unavailable")
    if str(assets) not in nltk.data.path:
        nltk.data.path.insert(0, str(assets))


def _runner(
    fixture, compiled, *, email=False, execution_mode="execute", sms_client=None,
):
    from botelier.voice.flows.native_actions import NativeActionRunner
    from botelier.voice.flows.native_messaging import NativeMessenger

    sent = []

    class Messages:
        def create(self, **kwargs):
            sent.append({"kind": "sms", **kwargs})
            return SimpleNamespace(sid="SMoffline-quote")

    def email_dispatch(connection, recipients, subject, body, **kwargs):
        sent.append({
            "kind": "email", "connection": connection, "recipients": recipients,
            "subject": subject, "body": body, **kwargs,
        })
        return True

    messenger = NativeMessenger(
        identity=fixture.identity,
        twilio_client=(
            None if email else sms_client or SimpleNamespace(messages=Messages())
        ),
        from_number="+12025550100", execution_mode=execution_mode,
        email_dispatch=email_dispatch if email else None,
    )
    runner = NativeActionRunner(
        compiled, fixture.factory, messenger=messenger,
        execution_mode=execution_mode, channel="voice",
    )
    return runner, sent


def _held_sms_client(entered, release, sent):
    class Messages:
        def create(self, **kwargs):
            sent.append({"kind": "sms", **kwargs})
            return SimpleNamespace(sid="SMoffline-held")

    messages = Messages()

    class Client:
        @property
        def messages(self):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("held fake SMS client setup was not released")
            return messages

    return Client()


def _ledger_rows(fixture):
    from botelier.models.operation_idempotency import OperationIdempotency

    db = fixture.factory()
    try:
        return db.query(OperationIdempotency).all()
    finally:
        db.close()


def test_messenger_email_html_is_opt_in_and_generic_dispatch_is_unchanged():
    from botelier.voice.flows.native_messaging import NativeMessenger

    calls = []
    identity = SimpleNamespace(account_id="account", property_id="property")
    connection = SimpleNamespace(
        account_id="account", property_id="property", status="connected",
        integration_type=SimpleNamespace(slug="email-sender-gmail"),
    )

    def dispatch(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    messenger = NativeMessenger(
        identity=identity, twilio_client=None, from_number="+12025550100",
        execution_mode="execute", email_dispatch=dispatch,
    )
    generic = messenger.send_email_sync(
        connection, "guest@example.invalid", "Receipt", "Plain message",
    )
    assert generic.accepted is True
    assert calls[0][1] == {"db": None}

    quote = messenger.send_email_sync(
        connection, "guest@example.invalid", "Reservation quote",
        "Review <room> & reservation: https://booking.example.invalid/review",
        body_html=(
            "Review &lt;room&gt; &amp; reservation: "
            "https://booking.example.invalid/review"
        ),
    )
    assert quote.accepted is True
    assert calls[1][1] == {
        "body_html": (
            "Review &lt;room&gt; &amp; reservation: "
            "https://booking.example.invalid/review"
        ),
        "db": None,
    }


def test_native_confirmation_requires_compiled_fields_and_typed_json_equality():
    from botelier.voice.flows.native_actions import NativeActionRunner
    from botelier.voice.flows.native_execution import NativeConfirmation
    from botelier.voice.flows.native_graph import compile_flow
    from botelier.voice.flows.pilot_contract import PilotIdentity

    identity = PilotIdentity(
        account_id="00000000-0000-0000-0000-000000000101",
        property_id="00000000-0000-0000-0000-000000000102",
        tool_id="offline-flow", flow_version_id="offline-version",
        call_sid="CAoffline-typed-confirmation",
    )
    compiled = compile_flow({
        "initial_node": "start",
        "variables": [
            {"key": "recipient", "type": "phone"},
            {"key": "count", "type": "number"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": ""}},
            {"id": "confirm", "type": "confirmation", "data": {
                "confirmation": {
                    "summaryTemplate": "Confirm {{count}} for {{recipient}}?",
                    "confirmPrompt": "Proceed?",
                    "variablesToConfirm": ["recipient", "count"],
                    "allowEdit": False,
                },
            }},
            {"id": "send", "type": "api_request", "data": {"api": {
                "apiSource": "tool", "toolId": "offline-sms-tool",
                "argumentsTemplate": (
                    '{"recipient":"{{recipient}}","body":"Count {{count}}"}'
                ),
            }}},
        ],
        "edges": [
            {"id": "start-confirm", "source": "start", "target": "confirm"},
            {"id": "confirm-send", "source": "confirm", "target": "send",
             "sourceHandle": "confirmed"},
        ],
    }, identity)
    runner = NativeActionRunner(compiled, lambda: None, execution_mode="preview")
    facts = {"recipient": "+12025550101", "count": 1}
    exact = NativeConfirmation(
        "confirm", 1, facts, ("recipient", "count"),
    )
    assert runner._confirmation_matches(
        exact, facts, compiled.node("send"), {"recipient", "count"},
    )
    bool_for_number = NativeConfirmation(
        "confirm", 1, {"recipient": facts["recipient"], "count": True},
        ("recipient", "count"),
    )
    assert not runner._confirmation_matches(
        bool_for_number, facts, compiled.node("send"), {"recipient", "count"},
    )
    wrong_field_order = NativeConfirmation(
        "confirm", 1, facts, ("count", "recipient"),
    )
    assert not runner._confirmation_matches(
        wrong_field_order, facts, compiled.node("send"), {"recipient", "count"},
    )


def test_compiled_sms_and_email_quote_delivery_send_once_and_replay(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario(tool_type):
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            clock = [NOW]
            _fixed_quote_clock(monkeypatch, clock)
            tool_id = "offline-quote-" + tool_type.lower()
            _add_tool_and_sender(fixture, tool_id, tool_type)
            compiled = _delivery_definition(fixture.identity, tool_id, tool_type)
            runner, sent = _runner(
                fixture, compiled, email=tool_type == "SEND_EMAIL",
            )
            prepare_threads = []
            main_thread = threading.get_ident()
            original_prepare = runner._prepare_quote_delivery

            def track_prepare(*args):
                prepare_threads.append(threading.get_ident())
                return original_prepare(*args)

            monkeypatch.setattr(runner, "_prepare_quote_delivery", track_prepare)
            recipient_variable = (
                "caller_email" if tool_type == "SEND_EMAIL" else "caller_phone"
            )
            facts, confirmation = _confirmed_facts(
                recipient_variable, email=tool_type == "SEND_EMAIL",
            )
            original_facts = deepcopy(facts)

            result = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert result.success is True, result
            if tool_type == "SEND_SMS":
                assert len(prepare_threads) == 3
                assert sum(thread_id != main_thread for thread_id in prepare_threads) == 1
            assert facts == original_facts
            assert confirmation.values()["quote_total"] == "230.00"
            assert confirmation.values()["quote_taxes"] == "20.00"
            assert confirmation.values()["quote_fees"] == "10.00"
            assert len(sent) == 1
            assert "private_checkout_url" not in result.llm_data
            assert "quote_fingerprint" not in result.llm_data
            if tool_type == "SEND_SMS":
                assert sent[0]["to"] == facts["caller_phone"]
                assert sent[0]["body"].endswith(facts["private_checkout_url"])
                assert sent[0]["body"].count(facts["private_checkout_url"]) == 1
            else:
                assert sent[0]["recipients"] == [facts["caller_email"]]
                assert sent[0]["body"].endswith(facts["private_checkout_url"])
                assert sent[0]["body_html"] == html.escape(
                    sent[0]["body"], quote=True,
                ).replace("\n", "<br>\n")
                assert "&lt;room&gt; &amp; reservation" in sent[0]["body_html"]
                assert "&amp;mode=review" in sent[0]["body_html"]

            replay = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert replay.success is True, replay
            if tool_type == "SEND_SMS":
                assert len(prepare_threads) == 4
                assert sum(thread_id != main_thread for thread_id in prepare_threads) == 1
            assert len(sent) == 1
            assert len(_ledger_rows(fixture)) == 1
            await runner.close()

    asyncio.run(scenario("SEND_SMS"))
    asyncio.run(scenario("SEND_EMAIL"))


def test_unconfirmed_stale_and_unsafe_quote_delivery_inputs_never_submit(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW
    from botelier.voice.flows import native_actions

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            _fixed_quote_clock(monkeypatch, [NOW])
            tool_id = "offline-quote-invalid"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            runner, sent = _runner(fixture, compiled)
            facts, confirmation = _confirmed_facts("caller_phone")
            node = compiled.node("delivery")

            for not_confirmed in (None, object()):
                missing = await runner.execute(
                    node, facts, confirmation=not_confirmed,
                )
                assert missing.failure_reason == "confirmation_required"

            cases = []
            changed_recipient = deepcopy(facts)
            changed_recipient["caller_phone"] = "+12025550123"
            cases.append((changed_recipient, confirmation, "quote_confirmation_changed"))

            changed_total = deepcopy(facts)
            changed_total["quote_total"] = "1.00"
            cases.append((changed_total, confirmation, "quote_confirmation_changed"))

            changed_room = deepcopy(facts)
            changed_room["selection"]["room_id"] = "another-room"
            cases.append((changed_room, confirmation, "quote_selection_mismatch"))

            changed_dates = deepcopy(facts)
            changed_dates["selection"]["check_out"] = "2026-12-04"
            cases.append((changed_dates, confirmation, "quote_selection_mismatch"))

            changed_occupancy = deepcopy(facts)
            changed_occupancy["selection"]["adults"] = 3
            cases.append((
                changed_occupancy, confirmation, "quote_selection_mismatch",
            ))

            changed_tax = deepcopy(facts)
            changed_tax["provider_quote"]["pricing"]["tax_total"] = "25.00"
            cases.append((changed_tax, confirmation, "quote_pricing_inconsistent"))

            changed_price = deepcopy(facts)
            changed_price["provider_quote"]["pricing"].update(
                subtotal="210.00", total="240.00",
            )
            cases.append((changed_price, confirmation, "quote_quote_changed"))

            expired = deepcopy(facts)
            expired["provider_quote"]["expires_at"] = "2026-12-01T14:59:00Z"
            cases.append((expired, confirmation, "quote_quote_expired"))

            unapproved_origin = deepcopy(facts)
            unapproved_origin["provider_quote"]["checkout_url"] = (
                "https://unapproved.example.invalid/review/quote"
            )
            cases.append((unapproved_origin, confirmation, "quote_checkout_link"))

            for current_facts, current_confirmation, expected in cases:
                result = await runner.execute(
                    node, current_facts, confirmation=current_confirmation,
                )
                assert result.failure_reason == expected, (expected, result)

            wrong_confirmation = type(confirmation)(
                "confirm", 8, confirmation.values(),
                tuple(reversed(confirmation.confirmed_fields)),
            )
            result = await runner.execute(
                node, facts, confirmation=wrong_confirmation,
            )
            assert result.failure_reason == "confirmation_required"

            original_render = native_actions.render_json_template
            for alteration in ("second_url", "altered_url"):
                def render_with_alteration(template, values, _alteration=alteration):
                    arguments = original_render(template, values)
                    if _alteration == "second_url":
                        arguments["body"] += " https://attacker.example.invalid/"
                    else:
                        arguments["body"] = arguments["body"].replace(
                            facts["private_checkout_url"],
                            facts["private_checkout_url"] + "-changed",
                        )
                    return arguments

                monkeypatch.setattr(
                    native_actions, "render_json_template", render_with_alteration,
                )
                result = await runner.execute(
                    node, facts, confirmation=confirmation,
                )
                assert result.failure_reason == "quote_delivery_url"
            monkeypatch.setattr(native_actions, "render_json_template", original_render)

            assert sent == []
            assert _ledger_rows(fixture) == []
            await runner.close()

    asyncio.run(scenario())


def test_valid_preview_quote_delivery_never_claims_or_submits(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            _fixed_quote_clock(monkeypatch, [NOW])
            tool_id = "offline-quote-preview"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            runner, sent = _runner(fixture, compiled, execution_mode="preview")
            facts, confirmation = _confirmed_facts("caller_phone")
            result = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert result.failure_reason == "preview_required"
            assert sent == []
            assert _ledger_rows(fixture) == []
            await runner.close()

    asyncio.run(scenario())


def test_quote_delivery_revalidates_after_claim_and_records_known_no_submit(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            clock = [NOW]
            _fixed_quote_clock(monkeypatch, clock)
            tool_id = "offline-quote-expiry-race"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            runner, sent = _runner(fixture, compiled)
            facts, confirmation = _confirmed_facts("caller_phone")

            original_claim = runner._ledger.claim

            def claim_then_expire(node_id, arguments):
                claimed = original_claim(node_id, arguments)
                clock[0] = NOW + timedelta(minutes=11)
                return claimed

            monkeypatch.setattr(runner._ledger, "claim", claim_then_expire)
            result = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert result.failure_reason == "quote_quote_expired"
            assert sent == []
            rows = _ledger_rows(fixture)
            assert len(rows) == 1
            assert rows[0].status == "failed"
            await runner.close()

    asyncio.run(scenario())


def test_sms_quote_revalidates_after_async_entry_before_provider_submission(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            clock = [NOW]
            _fixed_quote_clock(monkeypatch, clock)
            tool_id = "offline-quote-async-entry-expiry-race"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            runner, sent = _runner(fixture, compiled)
            facts, confirmation = _confirmed_facts("caller_phone")
            original_send = runner.messenger.send_sms
            entered = asyncio.Event()
            release = asyncio.Event()

            async def hold_after_broker_check(recipient, body, *, before_submit=None):
                entered.set()
                await release.wait()
                if before_submit is None:
                    return await original_send(recipient, body)
                return await original_send(
                    recipient, body, before_submit=before_submit,
                )

            runner.messenger.send_sms = hold_after_broker_check
            task = asyncio.create_task(runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            ))
            await asyncio.wait_for(entered.wait(), timeout=3)
            clock[0] = NOW + timedelta(minutes=11)
            release.set()
            result = await task

            assert result.failure_reason == "quote_quote_expired", result
            assert sent == []
            rows = _ledger_rows(fixture)
            assert len(rows) == 1
            assert rows[0].status == "failed"
            await runner.close()

    asyncio.run(scenario())


def test_sms_quote_revalidates_after_held_worker_client_setup(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            clock = [NOW]
            _fixed_quote_clock(monkeypatch, clock)
            tool_id = "offline-quote-held-client-expiry-race"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            entered, release = threading.Event(), threading.Event()
            sent = []
            runner, _ = _runner(
                fixture, compiled,
                sms_client=_held_sms_client(entered, release, sent),
            )
            facts, confirmation = _confirmed_facts("caller_phone")

            task = asyncio.create_task(runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            ))
            assert await asyncio.wait_for(
                asyncio.to_thread(entered.wait, 3), timeout=4,
            )
            clock[0] = NOW + timedelta(minutes=11)
            release.set()
            result = await task

            assert result.failure_reason == "quote_quote_expired", result
            assert sent == []
            rows = _ledger_rows(fixture)
            assert len(rows) == 1
            assert rows[0].status == "failed"
            await runner.close()

    asyncio.run(scenario())


def test_sms_quote_is_fenced_if_runner_closes_before_provider_submission(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            _fixed_quote_clock(monkeypatch, [NOW])
            tool_id = "offline-quote-close-before-submit"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            entered, release = threading.Event(), threading.Event()
            sent = []
            runner, _ = _runner(
                fixture, compiled,
                sms_client=_held_sms_client(entered, release, sent),
            )
            facts, confirmation = _confirmed_facts("caller_phone")

            task = asyncio.create_task(runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            ))
            assert await asyncio.wait_for(
                asyncio.to_thread(entered.wait, 3), timeout=4,
            )
            await runner.close()
            release.set()
            result = await task

            assert result.failure_reason == "action_runner_closed", result
            assert sent == []
            rows = _ledger_rows(fixture)
            assert len(rows) == 1
            assert rows[0].status == "failed"

    asyncio.run(scenario())


def test_sms_quote_is_fenced_if_owner_is_cancelled_before_provider_submission(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            _fixed_quote_clock(monkeypatch, [NOW])
            tool_id = "offline-quote-cancel-before-submit"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            entered, release, worker_finished = (
                threading.Event(), threading.Event(), threading.Event(),
            )
            sent = []
            runner, _ = _runner(
                fixture, compiled,
                sms_client=_held_sms_client(entered, release, sent),
            )
            original_submit = runner.messenger._submit_sms

            def track_worker(*args):
                try:
                    return original_submit(*args)
                finally:
                    worker_finished.set()

            runner.messenger._submit_sms = track_worker
            facts, confirmation = _confirmed_facts("caller_phone")

            task = asyncio.create_task(runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            ))
            assert await asyncio.wait_for(
                asyncio.to_thread(entered.wait, 3), timeout=4,
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("the owning action task must remain cancelled")
            release.set()
            assert await asyncio.wait_for(
                asyncio.to_thread(worker_finished.wait, 3), timeout=4,
            )

            assert sent == []
            rows = _ledger_rows(fixture)
            assert len(rows) == 1
            assert rows[0].status == "failed"
            retry = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert retry.failure_reason == "submission_cancelled"
            assert sent == []
            assert len(_ledger_rows(fixture)) == 1
            await runner.close()

    asyncio.run(scenario())


def test_cancelled_quote_sms_after_submission_stays_pending_and_cannot_replay(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            _fixed_quote_clock(monkeypatch, [NOW])
            tool_id = "offline-quote-cancel-after-submit"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            entered, release, worker_finished = (
                threading.Event(), threading.Event(), threading.Event(),
            )
            sent = []

            class Messages:
                def create(self, **kwargs):
                    sent.append({"kind": "sms", **kwargs})
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError("fake provider submission was not released")
                    return SimpleNamespace(sid="SMoffline-completes-after-cancel")

            runner, _ = _runner(
                fixture, compiled,
                sms_client=SimpleNamespace(messages=Messages()),
            )
            original_submit = runner.messenger._submit_sms

            def track_worker(*args):
                try:
                    return original_submit(*args)
                finally:
                    worker_finished.set()

            runner.messenger._submit_sms = track_worker
            facts, confirmation = _confirmed_facts("caller_phone")
            task = asyncio.create_task(runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            ))
            assert await asyncio.wait_for(
                asyncio.to_thread(entered.wait, 3), timeout=4,
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("the owning action task must remain cancelled")
            release.set()
            assert await asyncio.wait_for(
                asyncio.to_thread(worker_finished.wait, 3), timeout=4,
            )

            assert len(sent) == 1
            rows = _ledger_rows(fixture)
            assert len(rows) == 1
            assert rows[0].status == "pending"
            retry = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert retry.failure_reason == "effect_outcome_unknown"
            assert len(sent) == 1
            assert len(_ledger_rows(fixture)) == 1
            await runner.close()

    asyncio.run(scenario())


def test_email_quote_delivery_revalidates_after_sender_resolution_and_claim(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            clock = [NOW]
            _fixed_quote_clock(monkeypatch, clock)
            tool_id = "offline-quote-email-expiry-race"
            _add_tool_and_sender(fixture, tool_id, "SEND_EMAIL")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_EMAIL")
            runner, sent = _runner(fixture, compiled, email=True)
            facts, confirmation = _confirmed_facts("caller_email", email=True)

            original_claim = runner._ledger.claim

            def claim_then_expire(node_id, arguments):
                claimed = original_claim(node_id, arguments)
                clock[0] = NOW + timedelta(minutes=11)
                return claimed

            monkeypatch.setattr(runner._ledger, "claim", claim_then_expire)
            result = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert result.failure_reason == "quote_quote_expired"
            assert sent == []
            rows = _ledger_rows(fixture)
            assert len(rows) == 1
            assert rows[0].status == "failed"
            await runner.close()

    asyncio.run(scenario())


def test_quote_selection_mutation_after_claim_is_known_no_submit(monkeypatch):
    from native_effect_io import NativeEffectsFixture
    from test_reservation_quote_contract import NOW

    async def scenario():
        _use_vetted_offline_sentence_assets()
        async with NativeEffectsFixture() as fixture:
            _fixed_quote_clock(monkeypatch, [NOW])
            tool_id = "offline-quote-selection-race"
            _add_tool_and_sender(fixture, tool_id, "SEND_SMS")
            compiled = _delivery_definition(fixture.identity, tool_id, "SEND_SMS")
            runner, sent = _runner(fixture, compiled)
            facts, confirmation = _confirmed_facts("caller_phone")
            original_prepare = runner._prepare_quote_delivery
            count = 0

            def mutate_after_claim(node, config, current_facts, current_confirmation, args):
                nonlocal count
                count += 1
                if count == 2:
                    current_facts["selection"]["room_id"] = "changed-after-claim"
                return original_prepare(
                    node, config, current_facts, current_confirmation, args,
                )

            monkeypatch.setattr(runner, "_prepare_quote_delivery", mutate_after_claim)
            result = await runner.execute(
                compiled.node("delivery"), facts, confirmation=confirmation,
            )
            assert result.failure_reason == "quote_selection_mismatch"
            assert count == 2
            assert sent == []
            rows = _ledger_rows(fixture)
            assert len(rows) == 1
            assert rows[0].status == "failed"
            await runner.close()

    asyncio.run(scenario())
