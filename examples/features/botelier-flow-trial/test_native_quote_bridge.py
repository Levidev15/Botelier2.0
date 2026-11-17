"""Actual compiled-node/broker coverage; all storage and inputs are disposable."""

import asyncio
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_native_quote_actions import caller_facts, configuration
from test_reservation_quote_contract import NOW


def quote_definition():
    return {
        "initial_node": "start",
        "variables": [
            {"key": "provider_quote", "type": "text"},
            {"key": "selection", "type": "text"},
            {"key": "caller_phone", "type": "phone"},
        ],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": ""}},
            {"id": "quote", "type": "capability", "data": {
                "api": configuration(),
            }},
            {"id": "done", "type": "end", "data": {"closingMessage": ""}},
        ],
        "edges": [
            {"id": "start-quote", "source": "start", "target": "quote"},
            {"id": "quote-done", "source": "quote", "target": "done",
             "sourceHandle": "success"},
        ],
    }


def test_quote_capability_is_native_only_pure_and_not_a_payment_service():
    from botelier.services.capabilities.registry import get_capability

    spec = get_capability("validate_reservation_quote")
    assert spec is not None
    assert spec.native_flow_only is True
    assert spec.service_backed is False
    assert spec.mutating is False
    assert set(spec.required) == {"quote", "expected"}
    assert set(spec.parameters) == {"quote", "expected"}


def test_actual_compiler_admits_and_freezes_the_explicit_quote_contract():
    from botelier.voice.flows.native_graph import compile_flow
    from test_native_graph import identity

    source = quote_definition()
    expected = deepcopy(source["nodes"][1]["data"]["api"])
    compiled = compile_flow(source, identity())
    assert compiled.node("quote").data()["api"] == expected
    source["nodes"][1]["data"]["api"]["quotePolicy"]["allowedCheckoutOrigins"].clear()
    assert compiled.node("quote").data()["api"] == expected


@pytest.mark.parametrize("change", ["origin", "required_total", "default_total"])
def test_actual_compiler_rejects_unsafe_quote_policy_and_mapping(change):
    from botelier.voice.flows.native_graph import NativeGraphError, compile_flow
    from test_native_graph import identity

    source = quote_definition()
    config = source["nodes"][1]["data"]["api"]
    if change == "origin":
        config["quotePolicy"]["allowedCheckoutOrigins"] = ["{{caller_phone}}"]
    elif change == "required_total":
        config["quotePolicy"]["publicConfirmationFields"].pop("pricing.total")
    else:
        config["responseVariables"] = [{
            "variableKey": "quote_total", "jsonPath": "$.public.pricing.total",
            "defaultValue": "230.00",
        }]
    with pytest.raises(NativeGraphError):
        compile_flow(source, identity())


def test_actual_native_broker_validates_without_resolver_messenger_or_payment(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.voice.flows import native_quote_actions
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_graph import compile_flow

            original = native_quote_actions.validate_reservation_quote

            def fixed_clock(quote, **kwargs):
                return original(quote, **{**kwargs, "now": NOW})

            monkeypatch.setattr(
                native_quote_actions, "validate_reservation_quote", fixed_clock,
            )
            compiled = compile_flow(quote_definition(), fixture.identity)
            runner = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            resolutions = []

            def forbidden_resolver(*args):
                resolutions.append(args)
                raise AssertionError("a pure quote must not resolve a PMS/payment service")

            monkeypatch.setattr(runner, "_resolve_capability", forbidden_resolver)
            facts = caller_facts()
            before = deepcopy(facts)
            result = await runner.execute(compiled.node("quote"), facts)
            assert result.success is True, result
            assert result.variables["quote_total"] == "230.00"
            assert result.variables["quote_subtotal"] == "200.00"
            assert result.variables["quote_taxes"] == "20.00"
            assert result.variables["quote_fees"] == "10.00"
            assert result.variables["quote_children"] == 0
            assert result.llm_data["quote_total"] == "230.00"
            assert "private_checkout_url" not in result.llm_data
            assert "quote_fingerprint" not in result.llm_data
            assert facts == before
            assert resolutions == []
            assert runner.messenger is None
            await runner.close()

    asyncio.run(scenario())


def test_legacy_resolver_rejects_native_quotes_before_any_provider_or_payment_lookup():
    from botelier.services.capabilities.resolver import CapabilityResolver

    class NoDatabase:
        def query(self, *_args):
            raise AssertionError("native-only capabilities must not query providers")

    resolver = CapabilityResolver(
        NoDatabase(), "00000000-0000-0000-0000-000000000001", None,
    )
    assert resolver.resolve("validate_reservation_quote") is None
    result = resolver.execute_sync(
        "validate_reservation_quote", arguments={}, channel="flow",
    )
    assert result["status"] == "unavailable"
    assert "native" in result["error"].lower()


def test_legacy_flow_rejects_native_quotes_before_borrowing_a_database():
    from botelier.flow_executor import FlowExecutor

    def no_database():
        raise AssertionError("legacy flow must not resolve native quote capabilities")

    legacy = SimpleNamespace(
        account_id="00000000-0000-0000-0000-000000000001",
        state=SimpleNamespace(current_node_id="quote"),
        _resolve_api_edge=lambda *_args, **_kwargs: None,
        _borrow_db_session=no_database,
    )
    result = asyncio.run(FlowExecutor._handle_capability_request(
        legacy, "quote", None,
        {"capability": "validate_reservation_quote"},
    ))
    assert result["success"] is False
    assert "native" in result["message"].lower()


def test_internal_payment_dispatcher_is_not_a_generic_service_route(monkeypatch):
    from botelier.services.capabilities.resolver import CapabilityResolver

    def no_payment(*_args, **_kwargs):
        raise AssertionError("quote validation must never construct a payment service")

    monkeypatch.setitem(
        sys.modules, "botelier.services.payments",
        SimpleNamespace(PaymentService=no_payment),
    )
    resolver = CapabilityResolver(None, "synthetic-account", None)
    result = resolver._service_backed_payment(
        "validate_reservation_quote", {}, "voice", "CAoffline-only",
    )
    assert result["status"] == "unavailable"


def test_legacy_service_handler_also_refuses_nonpayment_capabilities(monkeypatch):
    from botelier.flow_executor import FlowExecutor

    def no_payment(*_args, **_kwargs):
        raise AssertionError("unsupported services must not construct a payment service")

    monkeypatch.setitem(
        sys.modules, "botelier.services.payments",
        SimpleNamespace(PaymentService=no_payment),
    )
    legacy = SimpleNamespace(
        state=SimpleNamespace(current_node_id="quote"),
        _resolve_api_edge=lambda *_args, **_kwargs: None,
    )
    result = asyncio.run(FlowExecutor._handle_service_backed_capability(
        legacy, "quote", None, {}, "validate_reservation_quote",
    ))
    assert result["success"] is False


def test_capability_typed_arguments_preserve_names_and_zero_in_the_actual_broker(monkeypatch):
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeActionResult
            from botelier.voice.flows.native_graph import compile_flow

            source = quote_definition()
            source["variables"] = [
                {"key": "arrival", "type": "text"},
                {"key": "departure", "type": "text"},
                {"key": "child_count", "type": "number"},
            ]
            source["nodes"][1]["data"]["api"] = {
                "apiSource": "capability", "capability": "search_availability",
                "argumentsTemplate": (
                    '{"check_in_date":{{arrival}},"check_out_date":{{departure}},'
                    '"children":{{child_count}}}'
                ),
            }
            compiled = compile_flow(source, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            calls = []

            def resolve(name, arguments, _facts, _config, writing):
                calls.append((name, arguments, writing))
                return {}, arguments, set(), False

            async def no_provider(*_args, **_kwargs):
                return NativeActionResult(True)

            monkeypatch.setattr(runner, "_resolve_capability", resolve)
            monkeypatch.setattr(runner, "_execute_integration", no_provider)
            result = await runner.execute(compiled.node("quote"), {
                "arrival": "2026-12-01", "departure": "2026-12-03",
                "child_count": 0,
            })
            assert result.success is True, result
            assert calls == [("search_availability", {
                "check_in_date": "2026-12-01", "check_out_date": "2026-12-03",
                "children": 0,
            }, False)]
            await runner.close()

    asyncio.run(scenario())
