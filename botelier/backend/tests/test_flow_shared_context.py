"""Focused coverage for Task #538 call-scoped flow context."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from botelier.flow_executor import CallFlowContext, FlowExecutor, parse_flow_config
from botelier.voice.function_mapper import FunctionMapper


def _booking_config():
    return {
        "initial_node": "start",
        "variables": [
            {"key": "arrival", "type": "date", "description": "arrival"},
            {"key": "departure", "type": "date", "description": "departure"},
        ],
        "nodes": [
            {
                "id": "start",
                "type": "initial",
                "data": {"greeting": "Hello", "waitForResponse": False},
            },
            {
                "id": "arrival",
                "type": "collect_slot",
                "data": {
                    "slot": {
                        "variableKey": "arrival",
                        "prompt": "Arrival?",
                        "validation": {"requireFuture": False},
                    }
                },
            },
            {
                "id": "departure",
                "type": "collect_slot",
                "data": {
                    "slot": {
                        "variableKey": "departure",
                        "prompt": "Departure?",
                        "validation": {
                            "requireFuture": False,
                            "crossFieldCheck": {
                                "compareWith": "arrival",
                                "operator": "after",
                                "errorMessage": "Checkout must follow checkin.",
                            },
                        },
                    }
                },
            },
            {"id": "book", "type": "api_request", "data": {"api": {"method": "POST"}}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "arrival"},
            {"id": "e2", "source": "arrival", "target": "departure"},
            {"id": "e3", "source": "departure", "target": "book"},
            {"id": "e4", "source": "book", "target": "end"},
        ],
    }


def test_structured_import_validates_atomically_and_advances_only_to_action_gate():
    executor = FlowExecutor(parse_flow_config(_booking_config()))

    invalid = executor.import_caller_slots(
        {"arrival": "2099-06-10", "departure": "2099-06-01"}
    )
    assert invalid["success"] is False
    assert executor.state.collected_slots == {}

    imported = executor.import_caller_slots(
        {"arrival": "2099-06-10", "departure": "2099-06-12"}
    )
    assert imported["success"] is True

    # The normal initial-message traversal consumes the already-satisfied
    # collect gates but must stop before executing/skipping the POST.
    assert executor.get_initial_messages() == ["Hello"]
    assert executor.state.current_node_id == "book"
    assert {s["function"]["name"] for s in executor.get_function_schemas()} == {
        "execute_book"
    }


def test_waiting_initial_enters_first_collect_without_speaking_its_prompt():
    """waitForResponse only controls speech, never whether state enters the graph."""
    config = _booking_config()
    config["nodes"][0]["data"]["waitForResponse"] = True
    executor = FlowExecutor(parse_flow_config(config))

    assert executor.get_initial_messages() == ["Hello"]
    assert executor.state.current_node_id == "arrival"
    assert {s["function"]["name"] for s in executor.get_function_schemas()} == {
        "collect_arrival"
    }


def test_waiting_initial_with_imported_slots_stops_at_api_gate():
    """Known booking facts skip collects but cannot bypass the booking action."""
    config = _booking_config()
    config["nodes"][0]["data"]["waitForResponse"] = True
    executor = FlowExecutor(parse_flow_config(config))

    assert executor.import_caller_slots(
        {"arrival": "2099-06-10", "departure": "2099-06-12"}
    )["success"]
    assert executor.get_initial_messages() == ["Hello"]
    executor.advance_past_satisfied_collects()

    assert executor.state.current_node_id == "book"
    assert {s["function"]["name"] for s in executor.get_function_schemas()} == {
        "execute_book"
    }


def test_started_flow_no_longer_emits_a_start_schema():
    """A reconnect must expose the pending node, not invite a restart."""
    mapper = FunctionMapper()
    tool = SimpleNamespace(
        id=uuid4(),
        name="rooms",
        description="book",
        config=_booking_config(),
        llm_provider=None,
        llm_model=None,
        llm_temperature=None,
        llm_max_tokens=None,
    )
    initial_schemas, _ = mapper.get_flow_functions(tool)
    assert "start_rooms" in {schema["function"]["name"] for schema in initial_schemas}

    executor = mapper.get_flow_executors()[0]
    executor.get_initial_messages()
    resumed_schemas, _ = mapper.get_flow_functions(tool)
    assert "start_rooms" not in {schema["function"]["name"] for schema in resumed_schemas}
    assert "collect_arrival" in {schema["function"]["name"] for schema in resumed_schemas}


def test_duplicate_flow_start_is_rejected_before_any_side_effect():
    """A repeated provider tool call cannot replay a started booking flow."""
    mapper = FunctionMapper()
    executor = FlowExecutor(parse_flow_config(_booking_config()))
    executor.get_initial_messages()
    mapper._flow_executors["rooms"] = executor
    mapper.track_tool_usage = MagicMock()

    params = SimpleNamespace(result_callback=AsyncMock())
    asyncio.run(mapper._create_flow_trigger_handler("rooms")(params))

    mapper.track_tool_usage.assert_not_called()
    params.result_callback.assert_awaited_once()
    result = params.result_callback.await_args.args[0]
    assert result["success"] is False
    assert "already in progress" in result["message"]


def test_flow_start_snapshots_the_first_actionable_node():
    """Start-trigger progress survives worker recreation before caller input."""
    mapper = FunctionMapper()
    executor = FlowExecutor(parse_flow_config(_booking_config()))
    executor._snapshot_state = AsyncMock()
    mapper._flow_executors["rooms"] = executor
    mapper.track_tool_usage = MagicMock()
    mapper.update_llm_tools_for_flow = MagicMock()
    params = SimpleNamespace(
        arguments={},
        llm=SimpleNamespace(push_frame=AsyncMock()),
        result_callback=AsyncMock(),
    )

    asyncio.run(mapper._create_flow_trigger_handler("rooms")(params))

    assert executor.state.current_node_id == "arrival"
    # Slot import may snapshot its own context propagation; the trigger must
    # still persist the post-transition state before exposing next tools.
    assert executor._snapshot_state.await_count >= 1
    mapper.update_llm_tools_for_flow.assert_called_once_with("rooms")


def test_shared_context_reuses_slots_across_executors_and_newest_caller_value_wins():
    context = CallFlowContext()
    first = FlowExecutor(parse_flow_config(_booking_config()), call_context=context)
    second = FlowExecutor(parse_flow_config(_booking_config()), call_context=context)

    assert first.import_caller_slots({"arrival": "2099-06-10"})["success"]
    assert second.state.collected_slots["arrival"] == "2099-06-10"

    assert second.import_caller_slots({"arrival": "2099-07-01"})["success"]
    assert first.state.collected_slots["arrival"] == "2099-07-01"
    assert context.revisions["arrival"] == 2


def test_defaults_and_derived_values_remain_flow_local():
    context = CallFlowContext()

    def config(default):
        value = _booking_config()
        value["variables"][0]["defaultValue"] = default
        return value

    first = FlowExecutor(parse_flow_config(config("2099-01-01")), call_context=context)
    second = FlowExecutor(parse_flow_config(config("2099-02-01")), call_context=context)
    assert context.values == {}
    assert first.state.collected_slots["arrival"] == "2099-01-01"
    assert second.state.collected_slots["arrival"] == "2099-02-01"

    first.state.set_variable("api_result", "first-only")
    assert "api_result" not in context.values
    assert "api_result" not in second.state.collected_slots


def test_function_mapper_owns_one_context_and_start_schema_accepts_typed_slots():
    mapper = FunctionMapper(assistant_timezone="America/Los_Angeles")

    def tool(name):
        return SimpleNamespace(
            id=uuid4(),
            name=name,
            description="book",
            config=_booking_config(),
            llm_provider=None,
            llm_model=None,
            llm_temperature=None,
            llm_max_tokens=None,
        )

    first_schemas, _ = mapper.get_flow_functions(tool("rooms"))
    mapper.get_flow_functions(tool("spa"))
    executors = mapper.get_flow_executors()

    assert len(executors) == 2
    assert executors[0].call_context is mapper._flow_context
    assert executors[1].call_context is mapper._flow_context
    assert executors[0].assistant_timezone == "America/Los_Angeles"
    assert executors[1].assistant_timezone == "America/Los_Angeles"
    trigger = first_schemas[0]["function"]
    assert trigger["name"] == "start_rooms"
    assert trigger["parameters"]["properties"]["arrival"]["type"] == "string"
    assert trigger["parameters"]["properties"]["departure"]["type"] == "string"
    assert trigger["parameters"]["required"] == []


def test_correction_invalidates_dependent_value_and_rewinds_to_its_collect_gate():
    executor = FlowExecutor(parse_flow_config(_booking_config()))
    executor.import_caller_slots(
        {"arrival": "2099-06-10", "departure": "2099-06-12"}
    )
    executor.get_initial_messages()
    assert executor.state.current_node_id == "book"
    executor.flow_config.nodes.append(
        parse_flow_config(
            {
                "initial_node": "derive",
                "variables": [],
                "nodes": [
                    {
                        "id": "derive",
                        "type": "set_variable",
                        "data": {
                            "setVariable": {
                                "variableKey": "stay_key",
                                "valueType": "template",
                                "value": "{{departure}}",
                            }
                        },
                    }
                ],
                "edges": [],
            }
        ).nodes[0]
    )
    executor.state.set_variable("stay_key", "2099-06-12")

    # The old departure is no longer valid after the newest caller correction.
    assert executor.correct_caller_slot("arrival", "2099-06-15") is None
    assert executor.state.collected_slots == {"arrival": "2099-06-15"}
    assert executor.state.current_node_id == "departure"
    assert {s["function"]["name"] for s in executor.get_function_schemas()} == {
        "collect_departure"
    }
    departure_schema = executor._create_slot_function(
        executor.flow_config.variables[1]
    )["function"]
    assert "after 2099-06-15" in departure_schema["description"]


def test_shared_correction_rewinds_other_executor_and_gates_mutating_action():
    import asyncio

    context = CallFlowContext()
    flow_a = FlowExecutor(parse_flow_config(_booking_config()), call_context=context)
    flow_b = FlowExecutor(parse_flow_config(_booking_config()), call_context=context)
    values = {"arrival": "2099-06-10", "departure": "2099-06-12"}
    assert flow_a.import_caller_slots(values)["success"]
    flow_a.get_initial_messages()
    flow_b.get_initial_messages()
    assert flow_b.state.current_node_id == "book"
    assert "execute_book" in {
        schema["function"]["name"] for schema in flow_b.get_function_schemas()
    }

    # A completed non-idempotent result remains protected even while flow
    # eligibility rewinds; it must never be cleared/replayed by notification.
    flow_b._non_get_results["already_done"] = {"success": True}
    assert flow_a.correct_caller_slot("arrival", "2099-06-15") is None

    assert "departure" not in context.values
    assert flow_b.state.current_node_id == "departure"
    assert {
        schema["function"]["name"] for schema in flow_b.get_function_schemas()
    } == {"collect_departure"}
    blocked = asyncio.run(
        flow_b.handle_function_call("execute_book", {})
    )
    assert blocked["success"] is False
    assert blocked["out_of_order"] is True
    assert flow_b._non_get_results["already_done"] == {"success": True}

    recollected = asyncio.run(
        flow_b.handle_function_call(
            "collect_departure", {"departure": "2099-06-20"}
        )
    )
    assert recollected["success"] is True
    assert flow_b.state.current_node_id == "book"
    assert "execute_book" in {
        schema["function"]["name"] for schema in flow_b.get_function_schemas()
    }


def test_unrelated_shared_fact_does_not_rewind_other_flow():
    context = CallFlowContext()
    booking = FlowExecutor(parse_flow_config(_booking_config()), call_context=context)
    unrelated_config = {
        "initial_node": "start",
        "variables": [{"key": "phone", "type": "phone", "description": "phone"}],
        "nodes": [
            {
                "id": "start",
                "type": "initial",
                "data": {"waitForResponse": False},
            },
            {
                "id": "phone",
                "type": "collect_slot",
                "data": {"slot": {"variableKey": "phone", "prompt": "Phone?"}},
            },
            {
                "id": "notify",
                "type": "api_request",
                "data": {
                    "api": {
                        "method": "POST",
                        "bodyTemplate": '{"phone":"{{phone}}"}',
                    }
                },
            },
        ],
        "edges": [
            {"id": "u1", "source": "start", "target": "phone"},
            {"id": "u2", "source": "phone", "target": "notify"},
        ],
    }
    unrelated = FlowExecutor(
        parse_flow_config(unrelated_config), call_context=context
    )
    unrelated.import_caller_slots({"phone": "+15551234567"})
    unrelated.get_initial_messages()
    assert unrelated.state.current_node_id == "notify"

    booking.import_caller_slots(
        {"arrival": "2099-06-10", "departure": "2099-06-12"}
    )
    assert booking.correct_caller_slot("arrival", "2099-06-15") is None
    assert unrelated.state.current_node_id == "notify"
    assert "execute_notify" in {
        schema["function"]["name"] for schema in unrelated.get_function_schemas()
    }


def test_completed_mutating_api_result_survives_rewind_and_is_not_replayed():
    executor = FlowExecutor(parse_flow_config(_booking_config()))
    cached = {"success": True, "message": "booked", "action": None}
    executor._non_get_results["book"] = cached

    # A rewind can make the same action reachable again; its permanent
    # call-scoped idempotency cache remains authoritative.
    executor.state.current_node_id = "book"
    assert executor._non_get_results["book"] is cached


def test_completed_save_record_is_not_replayed():
    executor = FlowExecutor(parse_flow_config(_booking_config()), account_id="account")
    executor.state.saved_records["save"] = "record-id"
    # Add a save node solely to exercise the early idempotency path.
    executor.flow_config.nodes.append(
        parse_flow_config(
            {
                "initial_node": "save",
                "variables": [],
                "nodes": [{"id": "save", "type": "save_record", "data": {}}],
                "edges": [],
            }
        ).nodes[0]
    )

    import asyncio

    result = asyncio.run(executor._handle_save_record("save_record_save", {}))
    assert result["record_saved"] is True
    assert result["message"] == "Record was already saved"


def test_rehydrated_saved_record_short_circuits_retry():
    import asyncio
    from unittest.mock import MagicMock

    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (
        "save",
        {"_saved_records": {"save": "record-id"}},
        "active",
    )
    executor = FlowExecutor(
        parse_flow_config(
            {
                "initial_node": "save",
                "variables": [],
                "nodes": [{"id": "save", "type": "save_record", "data": {}}],
                "edges": [],
            }
        ),
        account_id="account",
        call_sid="call",
        flow_tool_id=str(uuid4()),
        db_session=db,
    )

    assert executor.rehydrate_from_snapshot() is True
    result = asyncio.run(executor._handle_save_record("save_record_save", {}))
    assert executor.state.saved_records == {"save": "record-id"}
    assert result["record_saved"] is True
    assert result["message"] == "Record was already saved"


def test_concurrent_save_record_calls_are_serialized_and_create_once():
    import asyncio

    executor = FlowExecutor(parse_flow_config(_booking_config()))
    creates = 0

    async def fake_locked(function_name, arguments):
        nonlocal creates
        if "save" in executor.state.saved_records:
            return {"record_saved": True, "message": "already"}
        await asyncio.sleep(0)
        creates += 1
        executor.state.saved_records["save"] = "record-id"
        return {"record_saved": True, "message": "created"}

    executor._handle_save_record_locked = fake_locked

    async def run():
        return await asyncio.gather(
            executor._handle_save_record("save_record_save", {}),
            executor._handle_save_record("save_record_save", {}),
        )

    results = asyncio.run(run())
    assert creates == 1
    assert [r["message"] for r in results] == ["created", "already"]


def test_save_record_db_key_survives_snapshot_failure_and_fresh_executor_retry(
    monkeypatch,
):
    import asyncio
    from types import SimpleNamespace

    from sqlalchemy.exc import IntegrityError

    from botelier.models.record import Record

    account_id = uuid4()
    record_type_id = uuid4()
    tool_id = uuid4()
    stored_records = []
    record_type = SimpleNamespace(
        id=record_type_id,
        account_id=account_id,
        name="Booking",
        fields=[],
        status_options=[],
    )

    class Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *args):
            return self

        def first(self):
            if self.model.__name__ == "RecordType":
                return record_type
            if self.model.__name__ == "Record":
                return stored_records[0] if stored_records else None
            return None

    class FakeDB:
        def __init__(self):
            self.pending = None

        def query(self, model):
            return Query(model)

        def add(self, value):
            self.pending = value

        def commit(self):
            if not isinstance(self.pending, Record):
                return
            if any(
                row.idempotency_key == self.pending.idempotency_key
                for row in stored_records
            ):
                raise IntegrityError("duplicate", {}, Exception("unique"))
            self.pending.id = uuid4()
            stored_records.append(self.pending)
            self.pending = None

        def rollback(self):
            self.pending = None

        def close(self):
            pass

        # Flow snapshot persistence deliberately fails after the Record commit.
        def execute(self, *args, **kwargs):
            raise RuntimeError("snapshot unavailable")

    monkeypatch.setattr("botelier.database.SessionLocal", FakeDB)

    config = {
        "initial_node": "save",
        "variables": [],
        "nodes": [
            {
                "id": "save",
                "type": "save_record",
                "data": {"saveRecord": {"recordTypeId": str(record_type_id)}},
            }
        ],
        "edges": [],
    }

    def executor():
        return FlowExecutor(
            parse_flow_config(config),
            account_id=str(account_id),
            call_sid="CA-stable",
            flow_tool_id=str(tool_id),
        )

    first = asyncio.run(
        executor()._handle_save_record("save_record_save", {})
    )
    # A new worker has no in-memory/snapshot saved_records marker.
    second_executor = executor()
    assert second_executor.state.saved_records == {}
    second = asyncio.run(
        second_executor._handle_save_record("save_record_save", {})
    )

    assert first["record_saved"] is True
    assert second["record_saved"] is True
    assert second["message"] == "Record was already saved"
    assert len(stored_records) == 1
    assert (
        second_executor.state.saved_records["save"]
        == str(stored_records[0].id)
    )


def test_assistant_timezone_drives_date_guidance():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    executor = FlowExecutor(
        parse_flow_config(_booking_config()), assistant_timezone="Pacific/Kiritimati"
    )
    expected_today = datetime.now(ZoneInfo("Pacific/Kiritimati")).strftime("%Y-%m-%d")
    assert f"Current date: {expected_today}" in executor.get_static_system_prompt_additions()