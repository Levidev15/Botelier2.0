import asyncio
import json
import uuid


def test_confirmed_save_record_preserves_zero_false_and_deduplicates():
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow

            db = fixture.factory()
            RecordType = fixture.effect_models["RecordType"]
            CallLog = fixture.effect_models["CallLog"]
            record_type_id = uuid.uuid4()
            assistant_id = uuid.UUID(fixture.assistant_id)
            db.add(RecordType(
                id=record_type_id, account_id=uuid.UUID(fixture.account_id),
                name="Synthetic booking", slug="synthetic-booking",
                fields=[
                    {"key": "price", "type": "number", "required": True},
                    {"key": "tax", "type": "boolean", "required": True},
                ],
                status_options=[{"value": "confirmed", "label": "Confirmed"}],
                is_active=True,
            ))
            db.add(CallLog(
                id=uuid.uuid4(), account_id=uuid.UUID(fixture.account_id),
                call_sid=fixture.identity.call_sid, assistant_id=assistant_id,
                status="completed", outcome="completed",
            ))
            db.commit()
            db.close()

            config = {
                "initial_node": "start",
                "variables": [
                    {"key": "price", "type": "number"},
                    {"key": "tax", "type": "text"},
                ],
                "nodes": [
                    {"id": "start", "type": "initial", "data": {"greeting": ""}},
                    {"id": "confirm", "type": "confirmation", "data": {
                        "confirmation": {
                            "summaryTemplate": "Confirm {{price}}.",
                            "confirmPrompt": "Is this correct?",
                            "variablesToConfirm": ["price", "tax"],
                            "allowEdit": False,
                        },
                    }},
                    {"id": "save", "type": "save_record", "data": {"saveRecord": {
                        "recordTypeId": str(record_type_id),
                        "mapping": {"price": "{{price}}", "tax": "{{tax}}"},
                        "status": "confirmed",
                    }}},
                    {"id": "done", "type": "end", "data": {"closingMessage": ""}},
                ],
                "edges": [
                    {"id": "start-confirm", "source": "start", "target": "confirm"},
                    {"id": "confirmed-save", "source": "confirm", "target": "save",
                     "sourceHandle": "confirmed"},
                    {"id": "save-done", "source": "save", "target": "done"},
                ],
            }
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            facts = {"price": 0, "tax": False}
            node = compiled.node("save")

            denied = await runner.execute(node, facts)
            assert denied.failure_reason == "confirmation_required"
            confirmation = NativeConfirmation(
                "confirm", 3, json.dumps(facts), ("price", "tax"),
            )
            preview_runner = NativeActionRunner(
                compiled, fixture.factory, execution_mode="preview",
            )
            preview_denied = await preview_runner.execute(node, facts)
            assert preview_denied.failure_reason == "confirmation_required"
            preview = await preview_runner.execute(
                node, facts, confirmation=confirmation,
            )
            assert preview.failure_reason == "preview_required"
            db = fixture.factory()
            Record = fixture.effect_models["Record"]
            assert db.query(Record).count() == 0
            db.close()

            first = await runner.execute(node, facts, confirmation=confirmation)
            second = await runner.execute(node, facts, confirmation=confirmation)
            assert first.success is True
            assert second.success is True

            db = fixture.factory()
            Record = fixture.effect_models["Record"]
            rows = db.query(Record).filter(
                Record.account_id == uuid.UUID(fixture.account_id),
            ).all()
            assert len(rows) == 1
            assert rows[0].data == {"price": 0, "tax": False}
            assert rows[0].status == "confirmed"
            assert rows[0].source_call_log_id is not None
            db.close()

    asyncio.run(scenario())
