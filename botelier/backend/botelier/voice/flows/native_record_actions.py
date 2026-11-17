"""Atomic native flow Record creation and source-bound correction."""

import hashlib
import json
import re
from datetime import datetime
from uuid import UUID

_TEMPLATE_TOKEN = re.compile(r"\{\{(\w+)\}\}\Z")


class NativeRecordActionStore:
    """Commit a flow-node Record mutation and encrypted receipt in one transaction."""

    def __init__(self, session_factory, identity):
        self.session_factory = session_factory
        self.identity = identity

    def apply(self, node_id, setting, data, status, call_log_id, assistant_id):
        if setting.get("updateSourceNodeId"):
            return self._update(
                node_id, setting, data, status, call_log_id, assistant_id,
            )
        return self._create(
            node_id, setting, data, status, call_log_id, assistant_id,
        )

    def prepare(self, setting, facts):
        from botelier.models.assistant import Assistant
        from botelier.models.call_log import CallLog
        from botelier.models.record_type import RecordType
        from botelier.services.request_templates import render_content_template

        db = self.session_factory()
        try:
            try:
                type_id = _uuid(setting.get("recordTypeId"))
            except (TypeError, ValueError, AttributeError):
                raise LookupError("record_type_unavailable") from None
            account_id, property_id = self._scope_ids()
            record_type = db.query(RecordType).filter(
                RecordType.id == type_id,
                RecordType.account_id == account_id,
                RecordType.is_active.is_(True),
            ).first()
            if record_type is None:
                raise LookupError("record_type_unavailable")
            fields = record_type.fields or []
            definitions = {
                field.get("key"): field for field in fields
                if isinstance(field, dict)
            }
            if len(definitions) != len(fields):
                raise ValueError("record_schema_invalid")
            mapping = setting.get("mapping") or {}
            if set(mapping) - set(definitions):
                raise ValueError("record_field_invalid")
            values = {}
            for key, template in mapping.items():
                if not isinstance(template, str):
                    raise ValueError("record_value_invalid")
                exact = _TEMPLATE_TOKEN.fullmatch(template)
                if exact:
                    variable = exact.group(1)
                    if variable not in facts:
                        raise ValueError("record_value_missing")
                    value = facts[variable]
                else:
                    value = render_content_template(
                        template, facts, media_type="text/plain",
                    )
                _validate_field(definitions[key], value)
                values[key] = value
            if not setting.get("updateSourceNodeId"):
                _validate_record_state(
                    fields, values, None, record_type.status_options or [],
                )
            status = None
            if setting.get("status") is not None:
                exact = _TEMPLATE_TOKEN.fullmatch(setting["status"])
                if exact:
                    if exact.group(1) not in facts:
                        raise ValueError("record_status_missing")
                    status = facts[exact.group(1)]
                else:
                    status = render_content_template(
                        setting["status"], facts, media_type="text/plain",
                    )
                allowed = {
                    item.get("value") for item in record_type.status_options or []
                    if isinstance(item, dict) and isinstance(item.get("value"), str)
                }
                if status not in allowed:
                    raise ValueError("record_status_invalid")
            call_log = db.query(CallLog).filter(
                CallLog.call_sid == self.identity.call_sid,
                CallLog.account_id == account_id,
            ).first()
            if call_log is None or call_log.assistant_id is None:
                return None
            assistant = db.query(Assistant).filter(
                Assistant.id == call_log.assistant_id,
                Assistant.account_id == account_id,
                Assistant.is_active.is_(True),
            ).first()
            if (
                assistant is None or assistant.property_id is not None
                and assistant.property_id != property_id
            ):
                return None
            return values, status, call_log.id, call_log.assistant_id
        finally:
            self._quiet(db, "close")

    def prepare_preview(self, setting, facts, prior=None):
        """Render and validate an in-memory record without requiring a CallLog."""
        from botelier.models.record_type import RecordType
        from botelier.services.request_templates import render_content_template

        db = self.session_factory()
        try:
            try:
                type_id = _uuid(setting.get("recordTypeId"))
            except (TypeError, ValueError, AttributeError):
                raise LookupError("record_type_unavailable") from None
            account_id, _property_id = self._scope_ids()
            record_type = db.query(RecordType).filter(
                RecordType.id == type_id,
                RecordType.account_id == account_id,
                RecordType.is_active.is_(True),
            ).first()
            if record_type is None:
                raise LookupError("record_type_unavailable")
            fields = record_type.fields or []
            definitions = {
                field.get("key"): field for field in fields
                if isinstance(field, dict)
            }
            if len(definitions) != len(fields):
                raise ValueError("record_schema_invalid")
            mapping = setting.get("mapping") or {}
            if not isinstance(mapping, dict) or set(mapping) - set(definitions):
                raise ValueError("record_field_invalid")
            values = {}
            for key, template in mapping.items():
                if not isinstance(template, str):
                    raise ValueError("record_value_invalid")
                exact = _TEMPLATE_TOKEN.fullmatch(template)
                if exact:
                    variable = exact.group(1)
                    if variable not in facts:
                        raise ValueError("record_value_missing")
                    value = facts[variable]
                else:
                    value = render_content_template(
                        template, facts, media_type="text/plain",
                    )
                _validate_field(definitions[key], value)
                values[key] = value
            status = None
            if setting.get("status") is not None:
                exact = _TEMPLATE_TOKEN.fullmatch(setting["status"])
                if exact:
                    if exact.group(1) not in facts:
                        raise ValueError("record_status_missing")
                    status = facts[exact.group(1)]
                else:
                    status = render_content_template(
                        setting["status"], facts, media_type="text/plain",
                    )
                allowed = {
                    item.get("value") for item in record_type.status_options or []
                    if isinstance(item, dict) and isinstance(item.get("value"), str)
                }
                if status not in allowed:
                    raise ValueError("record_status_invalid")

            source_node_id = setting.get("updateSourceNodeId")
            if source_node_id:
                if (
                    not isinstance(prior, dict)
                    or prior.get("record_type_id") != str(type_id)
                    or not isinstance(prior.get("data"), dict)
                ):
                    return None
                final_data = dict(prior["data"])
                final_data.update(values)
                final_status = prior.get("status") if status is None else status
                _validate_record_state(
                    fields, final_data, final_status,
                    record_type.status_options or [],
                )
            else:
                final_data = values
                final_status = status
                _validate_record_state(
                    fields, final_data, final_status,
                    record_type.status_options or [],
                )
            return {
                "record_type_id": str(type_id),
                "data": final_data,
                "status": final_status,
            }
        finally:
            self._quiet(db, "close")

    def _create(self, node_id, setting, data, status, call_log_id, assistant_id):
        from botelier.models.assistant import Assistant
        from botelier.models.call_log import CallLog
        from botelier.models.operation_idempotency import OperationIdempotency
        from botelier.models.property import Property
        from botelier.models.record import Record
        from botelier.models.record_type import RecordType
        from botelier.models.tool import Tool
        from botelier.models.tool_set import ToolSet

        record_type_id = _uuid(setting.get("recordTypeId"))
        account_id, property_id = self._scope_ids()
        key = _create_record_key(self.identity, node_id)
        operation = "native_record_create:" + _hash_json([
            self.identity.account_id, self.identity.property_id,
            self.identity.call_sid, self.identity.tool_id, node_id,
        ])
        args = {
            "record_type_id": str(record_type_id), "data": data, "status": status,
            "source_call_log_id": str(call_log_id),
            "assistant_id": str(assistant_id),
        }
        args_hash = _hash_json(args)
        db = self.session_factory()
        try:
            record_type = db.query(RecordType).filter(
                RecordType.id == record_type_id,
                RecordType.account_id == account_id,
                RecordType.is_active.is_(True),
            ).first()
            if record_type is None:
                return _failure("record_type_unavailable")
            if not _owned_source(
                db, self.identity, call_log_id, assistant_id,
                CallLog, Assistant, Property, Tool, ToolSet,
            ):
                return _failure("record_source_unavailable")
            try:
                _validate_record_state(
                    record_type.fields or [], data, status,
                    record_type.status_options or [],
                )
            except (TypeError, ValueError):
                return _failure("record_validation_rejected")
            replay = self._read_receipt(db, key, operation, args_hash)
            if replay is not None:
                return replay
            if db.query(Record).filter(
                Record.idempotency_key == key,
            ).first() is not None:
                return _failure("record_create_conflict")
            record = Record(
                account_id=account_id, record_type_id=record_type_id,
                status=status, data=data, source_channel="voice",
                capture_method="flow_node", idempotency_key=key,
                source_call_log_id=_uuid(call_log_id),
                assistant_id=_uuid(assistant_id),
            )
            db.add(record)
            db.flush()
            receipt = {
                "id": str(record.id), "updated_at": _iso(record.updated_at),
                "data": record.data or {}, "status": record.status,
            }
            self._insert_receipt(db, key, operation, args_hash, account_id, property_id, receipt)
            db.commit()
            return _success()
        except Exception:
            self._quiet(db, "rollback")
            return self._replay_after_uncertain_commit(key, operation, args_hash)
        finally:
            self._quiet(db, "close")

    def _update(self, node_id, setting, replacement, replacement_status, call_log_id, assistant_id):
        from botelier.models.call_log import CallLog
        from botelier.models.operation_idempotency import OperationIdempotency
        from botelier.models.property import Property
        from botelier.models.record import Record
        from botelier.models.record_type import RecordType
        from botelier.models.assistant import Assistant
        from botelier.models.tool import Tool
        from botelier.models.tool_set import ToolSet

        account_id, property_id = self._scope_ids()
        type_id = _uuid(setting.get("recordTypeId"))
        source_node_id = setting.get("updateSourceNodeId")
        source_key = _create_record_key(self.identity, source_node_id)
        operation_key = operation = args_hash = None
        db = self.session_factory()
        try:
            record_type = db.query(RecordType).filter(
                RecordType.id == type_id, RecordType.account_id == account_id,
                RecordType.is_active.is_(True),
            ).first()
            call_log = db.query(CallLog).filter(
                CallLog.id == _uuid(call_log_id),
                CallLog.call_sid == self.identity.call_sid,
                CallLog.account_id == account_id,
                CallLog.assistant_id == _uuid(assistant_id),
            ).first()
            assistant = db.query(Assistant).filter(
                Assistant.id == _uuid(assistant_id),
                Assistant.account_id == account_id,
                Assistant.is_active.is_(True),
            ).first()
            if (
                record_type is None or call_log is None or assistant is None
                or not _owned_source(
                    db, self.identity, call_log_id, assistant_id,
                    CallLog, Assistant, Property, Tool, ToolSet,
                )
                or assistant.property_id is not None
                and assistant.property_id != property_id
            ):
                return _failure("record_source_unavailable")
            record = db.query(Record).filter(
                Record.idempotency_key == source_key,
                Record.account_id == account_id,
                Record.record_type_id == type_id,
                Record.source_channel == "voice",
                Record.capture_method == "flow_node",
                Record.source_call_log_id == call_log.id,
                Record.assistant_id == assistant.id,
            ).first()
            if record is None:
                return _failure("record_source_unavailable")
            prior_data_raw = record.data or {}
            prior_data = _detached_json(prior_data_raw)
            prior_status = record.status
            prior_updated_at = record.updated_at
            intended_data = dict(prior_data)
            intended_data.update(replacement)
            intended_status = (
                prior_status if replacement_status is None else replacement_status
            )
            try:
                _validate_record_state(
                    record_type.fields or [], intended_data, intended_status,
                    record_type.status_options or [],
                )
            except (TypeError, ValueError):
                return _failure("record_values_invalid")

            intent = {
                "source_record_id": str(record.id),
                "source_node_id": source_node_id,
                "update_node_id": node_id,
                "data": intended_data,
                "status": intended_status,
            }
            intent_hash = _hash_json(intent)
            operation = "native_record_update:" + intent_hash
            current_revision = _revision(
                str(record.id), prior_updated_at, prior_data, prior_status,
            )
            prior_receipt = self._find_matching_update_receipt(
                db, operation, account_id, property_id,
                str(record.id), current_revision,
            )
            if prior_receipt is not None:
                return prior_receipt

            operation_args = {
                "source_record_id": str(record.id),
                "source_node_id": source_node_id,
                "update_node_id": node_id,
                "prior_revision": current_revision,
                "replacement": intent,
            }
            args_hash = _hash_json(operation_args)
            operation_key = _hash_json([
                "native-record-update-v1", self.identity.account_id,
                self.identity.property_id, self.identity.call_sid,
                self.identity.tool_id, operation_args,
            ])
            exact = self._read_receipt(db, operation_key, operation, args_hash)
            if exact is not None:
                return exact

            now = datetime.utcnow()
            query = db.query(Record).filter(
                Record.id == record.id,
                Record.account_id == account_id,
                Record.record_type_id == type_id,
                Record.source_channel == "voice",
                Record.capture_method == "flow_node",
                Record.source_call_log_id == call_log.id,
                Record.assistant_id == assistant.id,
                Record.data == prior_data_raw,
            )
            query = (
                query.filter(Record.updated_at.is_(None))
                if prior_updated_at is None
                else query.filter(Record.updated_at == prior_updated_at)
            )
            query = (
                query.filter(Record.status.is_(None))
                if prior_status is None
                else query.filter(Record.status == prior_status)
            )
            changed = query.update({
                Record.data: intended_data,
                Record.status: intended_status,
                Record.updated_at: now,
            }, synchronize_session=False)
            if changed != 1:
                db.rollback()
                return _failure("record_conflict")
            receipt = {
                "id": str(record.id), "updated_at": _iso(now),
                "data": intended_data, "status": intended_status,
            }
            self._insert_receipt(
                db, operation_key, operation, args_hash,
                account_id, property_id, receipt,
            )
            db.commit()
            return _success()
        except Exception:
            self._quiet(db, "rollback")
            if operation_key and operation and args_hash:
                return self._replay_after_uncertain_commit(
                    operation_key, operation, args_hash,
                )
            return _failure("record_storage_unavailable")
        finally:
            self._quiet(db, "close")

    def _find_matching_update_receipt(
        self, db, operation, account_id, property_id, record_id, revision,
    ):
        from botelier.models.operation_idempotency import OperationIdempotency

        rows = db.query(OperationIdempotency).filter(
            OperationIdempotency.operation == operation,
            OperationIdempotency.account_id == account_id,
            OperationIdempotency.property_id == property_id,
            OperationIdempotency.status == "succeeded",
        ).order_by(OperationIdempotency.updated_at.desc()).limit(20).all()
        for row in rows:
            payload = _decrypt(row.result)
            if (
                isinstance(payload, dict) and payload.get("record") == revision
                and revision.get("id") == record_id
            ):
                return _action_result(payload)
        return None

    def _read_receipt(self, db, key, operation, args_hash):
        from botelier.models.operation_idempotency import OperationIdempotency

        row = db.query(OperationIdempotency).filter(
            OperationIdempotency.idempotency_key == key,
        ).first()
        if row is None:
            return None
        if (
            row.account_id != self._scope_ids()[0]
            or row.property_id != self._scope_ids()[1]
            or row.operation != operation or row.args_hash != args_hash
            or row.status != "succeeded"
        ):
            return _failure("record_conflict")
        payload = _decrypt(row.result)
        if not isinstance(payload, dict) or not isinstance(payload.get("action"), dict):
            return _failure("record_receipt_unavailable")
        return _action_result(payload)

    def _insert_receipt(self, db, key, operation, args_hash, account_id, property_id, record):
        from botelier.models.operation_idempotency import OperationIdempotency

        payload = {
            "action": {
                "success": True, "branch": "success", "variables": {},
                "llm_data": {}, "failure_reason": None,
            },
            "record": record,
        }
        sealed = _encrypt(payload)
        db.add(OperationIdempotency(
            idempotency_key=key, account_id=account_id,
            property_id=property_id, operation=operation,
            args_hash=args_hash, status="succeeded",
            result={"sealed": sealed}, updated_at=datetime.utcnow(),
        ))
        db.flush()

    def _replay_after_uncertain_commit(self, key, operation, args_hash):
        db = None
        try:
            db = self.session_factory()
            result = self._read_receipt(db, key, operation, args_hash)
            return result if result is not None else _failure("record_storage_unavailable")
        except Exception:
            return _failure("record_storage_unavailable")
        finally:
            self._quiet(db, "close")

    def _scope_ids(self):
        return UUID(self.identity.account_id), UUID(self.identity.property_id)

    @staticmethod
    def _quiet(db, method):
        if db is None:
            return
        try:
            getattr(db, method)()
        except Exception:
            pass


def _create_record_key(identity, node_id):
    return _hash_json([
        "native-record-create-v1", identity.account_id, identity.property_id,
        identity.call_sid, identity.tool_id, node_id,
    ])


def _hash_json(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _uuid(value):
    return UUID(str(value))


def _detached_json(value):
    return json.loads(json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"),
    ))


def _iso(value):
    return value.isoformat(timespec="microseconds") if value is not None else None


def _revision(record_id, updated_at, data, status):
    return {
        "id": record_id, "updated_at": _iso(updated_at),
        "data": _detached_json(data), "status": status,
    }


def _validate_record_state(fields, data, status, status_options):
    definitions = {
        field.get("key"): field for field in fields if isinstance(field, dict)
    }
    if len(definitions) != len(fields) or set(data) - set(definitions):
        raise ValueError("record_schema_invalid")
    for field in fields:
        key = field["key"]
        value = data.get(key)
        if field.get("required") and (value is None or value == ""):
            raise ValueError("record_required_field")
        if value is not None:
            _validate_field(field, value)
    allowed_statuses = {
        item.get("value") for item in status_options
        if isinstance(item, dict) and isinstance(item.get("value"), str)
    }
    if status is not None and status not in allowed_statuses:
        raise ValueError("record_status_invalid")


def _owned_source(
    db, identity, call_log_id, assistant_id,
    CallLog, Assistant, Property, Tool, ToolSet,
):
    account_id, property_id = UUID(identity.account_id), UUID(identity.property_id)
    call_log = db.query(CallLog).filter(
        CallLog.id == _uuid(call_log_id),
        CallLog.account_id == account_id,
        CallLog.call_sid == identity.call_sid,
        CallLog.assistant_id == _uuid(assistant_id),
    ).first()
    assistant = db.query(Assistant).filter(
        Assistant.id == _uuid(assistant_id),
        Assistant.account_id == account_id,
        Assistant.is_active.is_(True),
    ).first()
    property_row = db.query(Property).filter(
        Property.id == property_id,
        Property.account_id == account_id,
        Property.is_active.is_(True),
    ).first()
    flow = db.query(Tool).filter(
        Tool.id == identity.tool_id,
        Tool.is_active == "true",
    ).first()
    tool_set = (
        db.query(ToolSet).filter(
            ToolSet.id == flow.tool_set_id,
            ToolSet.account_id == account_id,
        ).first()
        if flow is not None and flow.tool_set_id is not None else None
    )
    return bool(
        call_log is not None and assistant is not None and property_row is not None
        and tool_set is not None
        and (
            assistant.property_id is None
            or assistant.property_id == property_id
        )
    )


def _validate_field(field, value):
    import re
    from datetime import date, datetime

    kind = field.get("type", "text")
    options = field.get("options") or []
    option_values = {
        option.get("value") if isinstance(option, dict) else option
        for option in options
    }
    valid = {
        "text": lambda item: isinstance(item, str) and len(item) <= 8000,
        "number": lambda item: type(item) in (int, float),
        "date": lambda item: _valid_date(date, item),
        "datetime": lambda item: _valid_datetime(datetime, item),
        "boolean": lambda item: type(item) is bool,
        "select": lambda item: item in option_values,
        "phone": lambda item: isinstance(item, str) and bool(
            re.fullmatch(r"[+0-9() .-]{7,32}", item)
        ),
        "email": lambda item: isinstance(item, str) and len(item) <= 320 and bool(
            re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", item)
        ),
    }.get(kind)
    if valid is None or not valid(value):
        raise ValueError("record_field_type")


def _valid_date(date_type, value):
    if not isinstance(value, str):
        return False
    try:
        date_type.fromisoformat(value)
        return True
    except ValueError:
        return False


def _valid_datetime(datetime_type, value):
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        datetime_type.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _encrypt(payload):
    from botelier.crypto import get_cipher

    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return get_cipher().encrypt(encoded).decode("ascii")


def _decrypt(result):
    try:
        from botelier.crypto import get_cipher

        sealed = result.get("sealed") if isinstance(result, dict) else None
        if not isinstance(sealed, str):
            return None
        return json.loads(get_cipher().decrypt(sealed.encode("ascii")).decode("utf-8"))
    except Exception:
        return None


def _action_result(payload):
    from botelier.voice.flows.native_actions import NativeActionResult

    action = payload["action"]
    return NativeActionResult(
        bool(action.get("success")), branch=action.get("branch", "success"),
        variables=action.get("variables") or {}, llm_data=action.get("llm_data"),
        failure_reason=action.get("failure_reason"),
    )


def _success():
    from botelier.voice.flows.native_actions import NativeActionResult

    return NativeActionResult(True, variables={}, llm_data={})


def _failure(reason):
    from botelier.voice.flows.native_actions import _failure

    return _failure(reason)
