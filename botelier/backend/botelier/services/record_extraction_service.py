"""Structured record auto-extraction service.

Runs AFTER a voice call or SMS conversation completes. Makes ONE combined LLM
call across all of an account's active ``auto_extract`` record types and creates
at most one auto-extracted :class:`Record` per type per source conversation.

Design (channel-agnostic):
  - Callers build a plain-text transcript and invoke :func:`run_record_extraction`
    with the source identifiers. Thin wrappers exist for voice (call logs) and
    SMS (conversations), plus threaded/background runners that own their own
    DB session so they are safe to call from a thread-pool executor.
  - A single LLM request returns a strict-schema object keyed by record type id,
    each entry being ``{matched, status, data}``. On strict-schema failure we
    retry once in ``json_object`` mode. This realizes the approved "one combined
    call" design while still allowing per-type field typing under strict mode.

Idempotency (three layers):
  1. Pre-skip any type that already has a ``flow_node`` record for this source
     (the explicit SAVE_RECORD node wins over inference).
  2. Pre-skip any type that already has an ``auto_extract`` record for this source
     (re-runs never duplicate).
  3. A partial unique index + ``ON CONFLICT DO NOTHING`` insert is the final
     backstop against concurrent double-runs.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from loguru import logger
from openai import OpenAI
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from botelier.models.record import CaptureMethod, Record, SourceChannel
from botelier.models.record_type import RecordType
from botelier.services.acw_service import _MAX_TRANSCRIPT_CHARS, _build_transcript_text

_client: Optional[OpenAI] = None

_MAX_ACTIVE_TYPES = 10
_MAX_LLM_ATTEMPTS = 2
_DEFAULT_MODEL = "gpt-4o-mini"


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


# ── Record type selection ────────────────────────────────────────────────────


def _load_active_types(
    account_id: UUID, assistant_id: Optional[UUID], db: Session
) -> List[RecordType]:
    """Return active, auto_extract record types applicable to this assistant.

    ``assistant_ids`` null/empty on a type means it applies to ALL assistants.
    Capped at :data:`_MAX_ACTIVE_TYPES` (lowest display_order first).
    """
    types = (
        db.query(RecordType)
        .filter(
            RecordType.account_id == account_id,
            RecordType.is_active == True,
            RecordType.auto_extract == True,
        )
        .order_by(RecordType.display_order, RecordType.created_at)
        .all()
    )

    applicable: List[RecordType] = []
    assistant_str = str(assistant_id) if assistant_id else None
    for t in types:
        allowed = t.assistant_ids
        if allowed:
            if assistant_str is None or assistant_str not in {str(a) for a in allowed}:
                continue
        applicable.append(t)

    if len(applicable) > _MAX_ACTIVE_TYPES:
        logger.warning(
            f"Record extraction: account {account_id} has {len(applicable)} active "
            f"auto_extract types; capping at {_MAX_ACTIVE_TYPES}"
        )
        applicable = applicable[:_MAX_ACTIVE_TYPES]
    return applicable


def _existing_source_type_ids(
    db: Session,
    account_id: UUID,
    call_log_id: Optional[UUID],
    conversation_id: Optional[UUID],
) -> Dict[str, set]:
    """Return sets of record_type_ids that already have flow_node / auto_extract
    records for this source, so they can be pre-skipped."""
    q = db.query(Record.record_type_id, Record.capture_method).filter(
        Record.account_id == account_id
    )
    if call_log_id is not None:
        q = q.filter(Record.source_call_log_id == call_log_id)
    elif conversation_id is not None:
        q = q.filter(Record.source_conversation_id == conversation_id)
    else:
        return {"flow_node": set(), "auto_extract": set()}

    flow_node: set = set()
    auto_extract: set = set()
    for type_id, method in q.all():
        if method == CaptureMethod.FLOW_NODE.value:
            flow_node.add(type_id)
        elif method == CaptureMethod.AUTO_EXTRACT.value:
            auto_extract.add(type_id)
    return {"flow_node": flow_node, "auto_extract": auto_extract}


def has_active_extraction_types(
    account_id: UUID, assistant_id: Optional[UUID], db: Session
) -> bool:
    """Cheap gate for triggers: is there any applicable auto_extract type?"""
    return len(_load_active_types(account_id, assistant_id, db)) > 0


# ── Schema construction ──────────────────────────────────────────────────────


def _field_json_type(field_type: str) -> List[str]:
    if field_type == "number":
        return ["number", "null"]
    if field_type == "boolean":
        return ["boolean", "null"]
    return ["string", "null"]


def _data_schema_for_type(record_type: RecordType) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    keys: List[str] = []
    for f in record_type.fields or []:
        key = f.get("key")
        if not key:
            continue
        props[key] = {"type": _field_json_type(f.get("type", "text"))}
        keys.append(key)
    return {
        "type": "object",
        "properties": props,
        "required": keys,
        "additionalProperties": False,
    }


def _status_schema_for_type(record_type: RecordType) -> Dict[str, Any]:
    options = [
        o.get("value") for o in (record_type.status_options or []) if o.get("value")
    ]
    if options:
        return {"type": ["string", "null"], "enum": options + [None]}
    return {"type": ["string", "null"]}


def _build_combined_schema(types: List[RecordType]) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    for t in types:
        props[str(t.id)] = {
            "type": "object",
            "properties": {
                "matched": {"type": "boolean"},
                "status": _status_schema_for_type(t),
                "data": _data_schema_for_type(t),
            },
            "required": ["matched", "status", "data"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": props,
        "required": [str(t.id) for t in types],
        "additionalProperties": False,
    }


def _json_schema_response_format(schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "record_extraction",
            "strict": True,
            "schema": schema,
        },
    }


def _build_prompt(types: List[RecordType], transcript_text: str) -> str:
    parts: List[str] = [
        "You extract structured records from a completed customer conversation.",
        "For EACH record type below, decide whether the conversation contains a "
        "genuine, actionable instance of it. Only set matched=true when the "
        "conversation clearly warrants creating that record; otherwise matched=false.",
        "Fill each field with the value stated in the conversation; use null when "
        "the value was not provided. Do not invent values.",
        "",
        "RECORD TYPES:",
    ]
    for t in types:
        parts.append(f"\n=== Record type id={t.id} — {t.name} ===")
        if t.description:
            parts.append(f"Description: {t.description}")
        if t.extraction_instructions:
            parts.append(f"Extraction instructions: {t.extraction_instructions}")
        field_lines = []
        for f in t.fields or []:
            line = f"- {f.get('key')} ({f.get('type', 'text')})"
            if f.get("label"):
                line += f" — {f.get('label')}"
            if f.get("required"):
                line += " [required]"
            if f.get("options"):
                line += f" options: {', '.join(str(o) for o in f['options'])}"
            field_lines.append(line)
        if field_lines:
            parts.append("Fields:\n" + "\n".join(field_lines))
        status_vals = [o.get("value") for o in (t.status_options or []) if o.get("value")]
        if status_vals:
            parts.append("Status options: " + ", ".join(status_vals))

    parts.append(f"\nCONVERSATION TRANSCRIPT:\n{transcript_text}")
    parts.append(
        "\nReturn a JSON object keyed by each record type id, each value being "
        '{"matched": bool, "status": <one status option value or null>, '
        '"data": {field_key: value_or_null}}.'
    )
    return "\n".join(parts)


# ── Core extraction ──────────────────────────────────────────────────────────


def _clip_transcript(transcript_text: str) -> str:
    if len(transcript_text) <= _MAX_TRANSCRIPT_CHARS:
        return transcript_text
    truncated = transcript_text[:_MAX_TRANSCRIPT_CHARS]
    last_newline = truncated.rfind("\n")
    if last_newline > 0:
        truncated = truncated[:last_newline]
    return truncated + "\n[Transcript truncated due to length]"


def _call_llm(types: List[RecordType], transcript_text: str, model: str) -> Dict[str, Any]:
    client = _get_client()
    schema = _build_combined_schema(types)
    prompt = _build_prompt(types, transcript_text)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise information-extraction engine. Return only valid "
                "JSON matching the requested shape. Never fabricate data."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    last_error: Optional[Exception] = None
    for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
        if attempt == 1:
            response_format = _json_schema_response_format(schema)
        else:
            response_format = {"type": "json_object"}
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format=response_format,
                temperature=0,
            )
            return json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                f"Record extraction LLM attempt {attempt}/{_MAX_LLM_ATTEMPTS} failed: {exc}"
            )
    if last_error:
        raise last_error
    return {}


def _coerce_data(record_type: RecordType, raw: Any) -> Dict[str, Any]:
    """Keep only known field keys with non-null values."""
    if not isinstance(raw, dict):
        return {}
    valid_keys = {f.get("key") for f in (record_type.fields or []) if f.get("key")}
    return {k: v for k, v in raw.items() if k in valid_keys and v is not None and v != ""}


def _valid_status(record_type: RecordType, value: Any) -> Optional[str]:
    if not value:
        return None
    allowed = {o.get("value") for o in (record_type.status_options or []) if o.get("value")}
    if allowed and value not in allowed:
        return None
    return str(value)


def run_record_extraction(
    *,
    account_id: UUID,
    transcript_text: str,
    source_channel: str,
    assistant_id: Optional[UUID],
    db: Session,
    call_log_id: Optional[UUID] = None,
    conversation_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Run combined extraction and persist matched records. Channel-agnostic."""
    if not transcript_text or not transcript_text.strip():
        return {"skipped": True, "reason": "empty_transcript"}

    types = _load_active_types(account_id, assistant_id, db)
    if not types:
        return {"skipped": True, "reason": "no_active_types"}

    existing = _existing_source_type_ids(db, account_id, call_log_id, conversation_id)
    already = existing["flow_node"] | existing["auto_extract"]
    types = [t for t in types if t.id not in already]
    if not types:
        return {"skipped": True, "reason": "already_captured"}

    transcript_text = _clip_transcript(transcript_text)
    model = os.environ.get("RECORD_EXTRACTION_MODEL", _DEFAULT_MODEL)

    try:
        parsed = _call_llm(types, transcript_text, model)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Record extraction failed for account {account_id}: {exc}")
        return {"error": str(exc)}

    created = 0
    for t in types:
        entry = parsed.get(str(t.id))
        if not isinstance(entry, dict):
            continue
        if not entry.get("matched"):
            continue
        data = _coerce_data(t, entry.get("data"))
        if not data:
            continue
        status = _valid_status(t, entry.get("status"))

        values = {
            "id": uuid4(),
            "account_id": account_id,
            "record_type_id": t.id,
            "status": status,
            "data": data,
            "source_channel": source_channel,
            "capture_method": CaptureMethod.AUTO_EXTRACT.value,
            "source_call_log_id": call_log_id,
            "source_conversation_id": conversation_id,
            "assistant_id": assistant_id,
            "created_at": datetime.utcnow(),
        }
        stmt = pg_insert(Record.__table__).values(**values).on_conflict_do_nothing()
        result = db.execute(stmt)
        if result.rowcount:
            created += 1

    db.commit()
    logger.info(
        f"Record extraction for account {account_id}: created {created} record(s) "
        f"across {len(types)} candidate type(s) (channel={source_channel})"
    )
    return {"success": True, "created": created, "candidate_types": len(types)}


# ── Voice wrappers ───────────────────────────────────────────────────────────


def run_record_extraction_for_call_in_thread(call_log_id: UUID) -> Dict[str, Any]:
    """Thread-safe voice extraction runner (owns its own session)."""
    from botelier.database import SessionLocal
    from botelier.models.call_log import CallLog

    db = SessionLocal()
    try:
        call_log = db.query(CallLog).filter(CallLog.id == call_log_id).first()
        if not call_log:
            return {"error": "call_log_not_found"}
        if not call_log.transcript:
            return {"skipped": True, "reason": "no_transcript"}
        transcript_text = _build_transcript_text(call_log.transcript)
        return run_record_extraction(
            account_id=call_log.account_id,
            transcript_text=transcript_text,
            source_channel=SourceChannel.VOICE.value,
            assistant_id=call_log.assistant_id,
            db=db,
            call_log_id=call_log.id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Record extraction thread failed for call {call_log_id}: {exc}")
        return {"error": str(exc)}
    finally:
        db.close()


async def run_record_extraction_for_call_background(call_log_id: UUID):
    """Poll for transcript readiness then run voice extraction in a thread."""
    import asyncio

    from botelier.database import SessionLocal
    from botelier.models.call_log import CallLog

    transcript_ready = False
    db = SessionLocal()
    try:
        max_retries = 5
        for attempt in range(max_retries):
            call_log = db.query(CallLog).filter(CallLog.id == call_log_id).first()
            if not call_log:
                return
            if call_log.transcript:
                transcript_ready = True
                break
            db.expire(call_log)
            await asyncio.sleep(2 * (attempt + 1))
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Record extraction polling failed for {call_log_id}: {exc}")
    finally:
        db.close()

    if not transcript_ready:
        return

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, run_record_extraction_for_call_in_thread, call_log_id)


# ── SMS wrappers ─────────────────────────────────────────────────────────────


def _build_sms_transcript(messages: List[Any]) -> str:
    lines: List[str] = []
    for m in messages:
        content = (m.content or "").strip()
        if not content:
            continue
        speaker = "Customer" if m.direction == "inbound" else "AI Agent"
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def run_record_extraction_for_conversation_in_thread(conversation_id: UUID) -> Dict[str, Any]:
    """Thread-safe SMS extraction runner (owns its own session)."""
    from botelier.database import SessionLocal
    from botelier.models.sms_conversation import SMSConversation, SMSMessage

    db = SessionLocal()
    try:
        conversation = (
            db.query(SMSConversation)
            .filter(SMSConversation.id == conversation_id)
            .first()
        )
        if not conversation:
            return {"error": "conversation_not_found"}
        messages = (
            db.query(SMSMessage)
            .filter(SMSMessage.conversation_id == conversation_id)
            .order_by(SMSMessage.created_at)
            .all()
        )
        transcript_text = _build_sms_transcript(messages)
        return run_record_extraction(
            account_id=conversation.account_id,
            transcript_text=transcript_text,
            source_channel=SourceChannel.SMS.value,
            assistant_id=conversation.assistant_id,
            db=db,
            conversation_id=conversation.id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            f"Record extraction thread failed for conversation {conversation_id}: {exc}"
        )
        return {"error": str(exc)}
    finally:
        db.close()
