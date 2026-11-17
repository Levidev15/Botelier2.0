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


def test_record_and_encrypted_receipt_are_atomic_across_commit_ack_loss():
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.models.operation_idempotency import OperationIdempotency
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow

            db = fixture.factory()
            RecordType = fixture.effect_models["RecordType"]
            CallLog = fixture.effect_models["CallLog"]
            record_type_id = uuid.uuid4()
            db.add(RecordType(
                id=record_type_id, account_id=uuid.UUID(fixture.account_id),
                name="Atomic record", slug="atomic-record",
                fields=[{"key": "price", "type": "number", "required": True}],
                status_options=[{"value": "confirmed", "label": "Confirmed"}],
                is_active=True,
            ))
            db.add(CallLog(
                id=uuid.uuid4(), account_id=uuid.UUID(fixture.account_id),
                call_sid=fixture.identity.call_sid,
                assistant_id=uuid.UUID(fixture.assistant_id),
                status="completed", outcome="completed",
            ))
            db.commit()
            db.close()
            config = _create_flow(record_type_id)
            compiled = compile_flow(config, fixture.identity)
            confirmation = NativeConfirmation(
                "confirm", 1, '{"price":0}', ("price",),
            )

            class CommitFault:
                mode = "before"

                def __call__(self):
                    return FaultSession(fixture.factory(), self)

            class FaultSession:
                def __init__(self, inner, owner):
                    self.inner, self.owner = inner, owner

                def __getattr__(self, name):
                    return getattr(self.inner, name)

                def commit(self):
                    mode, self.owner.mode = self.owner.mode, None
                    if mode == "before":
                        self.inner.rollback()
                        raise RuntimeError("commit not acknowledged")
                    self.inner.commit()
                    if mode == "after":
                        raise RuntimeError("commit ack lost")

            faults = CommitFault()
            runner = NativeActionRunner(compiled, faults)
            first = await runner.execute(
                compiled.node("save"), {"price": 0}, confirmation=confirmation,
            )
            assert first.failure_reason == "record_storage_unavailable"
            db = fixture.factory()
            assert db.query(fixture.effect_models["Record"]).count() == 0
            assert db.query(OperationIdempotency).count() == 0
            db.close()

            faults.mode = "after"
            acknowledged = await runner.execute(
                compiled.node("save"), {"price": 0}, confirmation=confirmation,
            )
            assert acknowledged.success is True
            restarted = NativeActionRunner(compiled, fixture.factory)
            replay = await restarted.execute(
                compiled.node("save"), {"price": 0}, confirmation=confirmation,
            )
            assert replay == acknowledged

            db = fixture.factory()
            records = db.query(fixture.effect_models["Record"]).all()
            operations = db.query(OperationIdempotency).all()
            assert len(records) == len(operations) == 1
            assert operations[0].status == "succeeded"
            assert records[0].data == {"price": 0}
            serialized_receipt = json.dumps(operations[0].result)
            assert "price" not in serialized_receipt
            db.close()

    asyncio.run(scenario())


def test_confirmed_source_record_correction_is_versioned_cas_and_replayable():
    from native_effect_io import NativeEffectsFixture

    async def scenario():
        async with NativeEffectsFixture() as fixture:
            from botelier.models.operation_idempotency import OperationIdempotency
            from botelier.voice.flows.native_actions import NativeActionRunner
            from botelier.voice.flows.native_execution import NativeConfirmation
            from botelier.voice.flows.native_graph import compile_flow

            db = fixture.factory()
            RecordType = fixture.effect_models["RecordType"]
            CallLog = fixture.effect_models["CallLog"]
            record_type_id = uuid.uuid4()
            db.add(RecordType(
                id=record_type_id, account_id=uuid.UUID(fixture.account_id),
                name="Correctable record", slug="correctable-record",
                fields=[
                    {"key": "name", "type": "text", "required": True},
                    {"key": "flag", "type": "boolean", "required": True},
                ],
                status_options=[
                    {"value": "confirmed", "label": "Confirmed"},
                    {"value": "corrected", "label": "Corrected"},
                ],
                is_active=True,
            ))
            db.add(CallLog(
                id=uuid.uuid4(), account_id=uuid.UUID(fixture.account_id),
                call_sid=fixture.identity.call_sid,
                assistant_id=uuid.UUID(fixture.assistant_id),
                status="completed", outcome="completed",
            ))
            db.commit()
            db.close()
            config = _correction_flow(record_type_id)
            compiled = compile_flow(config, fixture.identity)
            runner = NativeActionRunner(compiled, fixture.factory)
            source_facts = {"name": "Ari", "flag": False}
            source_consent = NativeConfirmation(
                "confirm", 1, json.dumps(source_facts), ("name", "flag"),
            )
            created = await runner.execute(
                compiled.node("save"), source_facts,
                confirmation=source_consent,
            )
            assert created.success is True

            corrected_facts = {"name": "Aria", "flag": False}
            fresh_consent = NativeConfirmation(
                "confirm_update", 2, json.dumps(corrected_facts), ("name", "flag"),
            )
            denied_stale = await runner.execute(
                compiled.node("update"), corrected_facts,
                confirmation=source_consent,
            )
            assert denied_stale.failure_reason == "confirmation_required"

            class AckLossFactory:
                mode = "after"

                def __call__(self):
                    return AckLossSession(fixture.factory(), self)

            class AckLossSession:
                def __init__(self, inner, owner):
                    self.inner, self.owner = inner, owner

                def __getattr__(self, name):
                    return getattr(self.inner, name)

                def commit(self):
                    mode, self.owner.mode = self.owner.mode, None
                    self.inner.commit()
                    if mode == "after":
                        raise RuntimeError("update commit acknowledgement lost")

            ack_loss = AckLossFactory()
            updated = await NativeActionRunner(
                compiled, ack_loss,
            ).execute(
                compiled.node("update"), corrected_facts,
                confirmation=fresh_consent,
            )
            replay = await NativeActionRunner(
                compiled, fixture.factory,
            ).execute(
                compiled.node("update"), corrected_facts,
                confirmation=fresh_consent,
            )
            assert updated.success is True
            assert replay == updated
            db = fixture.factory()
            rows = db.query(fixture.effect_models["Record"]).all()
            updates = db.query(OperationIdempotency).filter(
                OperationIdempotency.operation.like("native_record_update:%"),
            ).all()
            assert len(rows) == 1
            assert rows[0].data == {"name": "Aria", "flag": False}
            assert rows[0].status == "corrected"
            assert len(updates) == 1
            revision_after_update = rows[0].updated_at
            db.close()

            # A fresh correction is a new operation bound to the updated prior revision.
            second_facts = {"name": "Ariana", "flag": False}
            second_consent = NativeConfirmation(
                "confirm_update", 3, json.dumps(second_facts), ("name", "flag"),
            )
            second_update = await runner.execute(
                compiled.node("update"), second_facts,
                confirmation=second_consent,
            )
            assert second_update.success is True
            db = fixture.factory()
            rows = db.query(fixture.effect_models["Record"]).all()
            updates = db.query(OperationIdempotency).filter(
                OperationIdempotency.operation.like("native_record_update:%"),
            ).all()
            assert len(rows) == 1
            assert rows[0].data == {"name": "Ariana", "flag": False}
            assert rows[0].updated_at != revision_after_update
            assert len(updates) == 2
            db.close()

            class ConflictQuery:
                def __init__(self, inner, model):
                    self.inner, self.model = inner, model

                def __getattr__(self, name):
                    return getattr(self.inner, name)

                def filter(self, *args):
                    return ConflictQuery(self.inner.filter(*args), self.model)

                def filter_by(self, **kwargs):
                    return ConflictQuery(self.inner.filter_by(**kwargs), self.model)

                def update(self, *args, **kwargs):
                    return 0

            class ConflictSession:
                def __init__(self, inner, record_model):
                    self.inner, self.record_model = inner, record_model

                def __getattr__(self, name):
                    return getattr(self.inner, name)

                def query(self, model):
                    query = self.inner.query(model)
                    return (
                        ConflictQuery(query, model)
                        if model is self.record_model else query
                    )

            class ConflictFactory:
                def __call__(self):
                    return ConflictSession(
                        fixture.factory(), fixture.effect_models["Record"],
                    )

            conflict_facts = {"name": "Arian", "flag": False}
            conflict_consent = NativeConfirmation(
                "confirm_update", 4, json.dumps(conflict_facts), ("name", "flag"),
            )
            conflict = await NativeActionRunner(
                compiled, ConflictFactory(),
            ).execute(
                compiled.node("update"), conflict_facts,
                confirmation=conflict_consent,
            )
            assert conflict.failure_reason == "record_conflict"
            db = fixture.factory()
            rows = db.query(fixture.effect_models["Record"]).all()
            updates = db.query(OperationIdempotency).filter(
                OperationIdempotency.operation.like("native_record_update:%"),
            ).all()
            assert len(rows) == 1
            assert rows[0].data == {"name": "Ariana", "flag": False}
            assert len(updates) == 2
            db.close()

            from botelier.voice.flows.native_record_actions import NativeRecordActionStore

            db = fixture.factory()
            foreign_type_id = uuid.uuid4()
            db.add(RecordType(
                id=foreign_type_id, account_id=uuid.UUID(fixture.account_id),
                name="Other record", slug="other-record",
                fields=[{"key": "name", "type": "text", "required": True}],
                status_options=[{"value": "corrected", "label": "Corrected"}],
                is_active=True,
            ))
            db.commit()
            db.close()
            store = NativeRecordActionStore(fixture.factory, fixture.identity)
            base_setting = {
                "recordTypeId": str(record_type_id),
                "updateSourceNodeId": "save", "mapping": {"name": "{{name}}"},
            }
            wrong_call = store.apply(
                "update", base_setting, {"name": "Wrong call"}, "corrected",
                uuid.uuid4(), uuid.UUID(fixture.assistant_id),
            )
            wrong_assistant = store.apply(
                "update", base_setting, {"name": "Wrong assistant"}, "corrected",
                fixture.models["version_id"], uuid.uuid4(),
            )
            wrong_type = store.apply(
                "update", {
                    **base_setting, "recordTypeId": str(foreign_type_id),
                },
                {"name": "Wrong type"}, "corrected",
                fixture.models["version_id"],
                uuid.UUID(fixture.assistant_id),
            )
            assert wrong_call.failure_reason == "record_source_unavailable"
            assert wrong_assistant.failure_reason == "record_source_unavailable"
            assert wrong_type.failure_reason == "record_source_unavailable"

    asyncio.run(scenario())


def _create_flow(record_type_id):
    return {
        "initial_node": "start",
        "variables": [{"key": "price", "type": "number"}],
        "nodes": [
            {"id": "start", "type": "initial", "data": {"greeting": ""}},
            {"id": "confirm", "type": "confirmation", "data": {
                "confirmation": {
                    "summaryTemplate": "Confirm {{price}}.",
                    "confirmPrompt": "Proceed?",
                    "variablesToConfirm": ["price"], "allowEdit": False,
                },
            }},
            {"id": "save", "type": "save_record", "data": {"saveRecord": {
                "recordTypeId": str(record_type_id),
                "mapping": {"price": "{{price}}"},
                "status": "confirmed",
            }}},
            {"id": "done", "type": "end", "data": {"closingMessage": ""}},
        ],
        "edges": [
            {"id": "start-confirm", "source": "start", "target": "confirm"},
            {"id": "confirm-save", "source": "confirm", "target": "save",
             "sourceHandle": "confirmed"},
            {"id": "save-done", "source": "save", "target": "done"},
        ],
    }


def _correction_flow(record_type_id):
    flow = _create_flow(record_type_id)
    flow["variables"] = [
        {"key": "name", "type": "text"},
        {"key": "flag", "type": "text"},
    ]
    start, confirm, save = flow["nodes"][:3]
    flow["nodes"][1]["data"]["confirmation"] = {
        "summaryTemplate": "Confirm {{name}}.",
        "confirmPrompt": "Proceed?",
        "variablesToConfirm": ["name", "flag"],
        "allowEdit": False,
    }
    flow["nodes"][2]["data"]["saveRecord"]["mapping"] = {
        "name": "{{name}}", "flag": "{{flag}}",
    }
    flow["nodes"][2]["data"]["saveRecord"]["status"] = "confirmed"
    update_confirmation = {
        "id": "confirm_update", "type": "confirmation",
        "data": {"confirmation": {
            "summaryTemplate": "Correct {{name}}.",
            "confirmPrompt": "Is this correction correct?",
            "variablesToConfirm": ["name", "flag"],
            "allowEdit": False,
        }},
    }
    flow["nodes"] = [start, confirm, save, update_confirmation, {
        "id": "update", "type": "save_record", "data": {"saveRecord": {
            "recordTypeId": str(record_type_id),
            "updateSourceNodeId": "save",
            "mapping": {"name": "{{name}}"},
            "status": "corrected",
        }},
    }, {
        "id": "done", "type": "end", "data": {"closingMessage": ""},
    }]
    flow["edges"] = [
        {"id": "start-confirm", "source": "start", "target": "confirm"},
        {"id": "confirm-save", "source": "confirm", "target": "save",
         "sourceHandle": "confirmed"},
        {"id": "save-confirm-update", "source": "save", "target": "confirm_update"},
        {"id": "confirm-update", "source": "confirm_update", "target": "update",
         "sourceHandle": "confirmed"},
        {"id": "update-done", "source": "update", "target": "done"},
    ]
    return flow
