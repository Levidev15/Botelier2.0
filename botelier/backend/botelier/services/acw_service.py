import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from loguru import logger
from openai import OpenAI
from sqlalchemy.orm import Session

from botelier.models.assistant import Assistant
from botelier.models.call_log import CallLeg, CallLog, LegType
from botelier.models.disposition import AssistantDisposition
from botelier.models.resolution_option import AssistantResolutionOption

_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


_MAX_TRANSCRIPT_CHARS = 32000
_MAX_LLM_ATTEMPTS = 2
# Task #397 — tool-result snippets in the QA transcript. 500 chars keeps
# confirmation numbers / dates / amounts visible so the LLM can verify the
# agent quoted accurate information (120 was too aggressive).
_MAX_TOOL_RESULT_CHARS = 500
# Task #397 — condensed assistant system prompt included as ASSISTANT PURPOSE.
_MAX_SYSTEM_PROMPT_CHARS = 1500
_MAX_TOPIC_WORDS = 3
_MAX_TOPIC_CHARS = 60

_ROLE_LABELS = {
    "user": "Customer",
    "assistant": "AI Agent",
}

_TRANSFER_LEG_TYPES = {
    LegType.TRANSFER_EXTERNAL.value,
    LegType.TRANSFER_SIP.value,
    LegType.TRANSFER_COLD.value,
    LegType.TRANSFER_INTERNAL.value,
}


def _mask_number(number: str) -> str:
    """Mask a phone number, showing only the last 4 digits."""
    if not number:
        return "unknown"
    digits = "".join(c for c in number if c.isdigit())
    if len(digits) >= 4:
        return f"***-{digits[-4:]}"
    return number


# Trailing id-ish segments on flow tool names (e.g. "_node_1a2b3c", "_9f8e7d",
# "_123"). Requires at least one digit so real words are never stripped.
_ID_SUFFIX_RE = re.compile(r"_(?:node_)?(?=[0-9a-f]*[0-9])[0-9a-f]{3,}$", re.IGNORECASE)


def _humanize_action_name(fn_name: str) -> str:
    """Turn a machine tool name into a readable action label for the QA prompt.

    "execute_lookup_reservation_node_1a2b3c" → "Lookup Reservation"
    "end_call_9f8e7d" → "End Call"
    Falls back to the raw name if nothing readable remains.
    """
    name = (fn_name or "").strip()
    for prefix in ("execute_",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    prev = None
    while prev != name:
        prev = name
        name = _ID_SUFFIX_RE.sub("", name)
    if name.endswith("_node"):
        name = name[: -len("_node")]
    words = [w for w in name.split("_") if w]
    if not words:
        return fn_name
    return " ".join(w.capitalize() for w in words)


def _sanitize_topic(value: Any) -> Optional[str]:
    """Enforce the 3-words-or-less topic contract server-side.

    Defensive: collapses whitespace, strips punctuation edges, truncates to
    the first 3 words and a hard char cap. Returns None for anything unusable
    so a bad topic never blocks the rest of the QA result.
    """
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip(" .,:;!?\"'`")
    if not cleaned:
        return None
    words = cleaned.split(" ")[:_MAX_TOPIC_WORDS]
    topic = " ".join(words)[:_MAX_TOPIC_CHARS].strip()
    return topic or None


def _fmt_duration(seconds: Optional[int]) -> str:
    """Format duration in seconds to a human-readable string."""
    if not seconds:
        return "unknown"
    minutes, secs = divmod(int(seconds), 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _build_transcript_text(transcript: list) -> str:
    """Convert raw LLM message list to a readable transcript string.

    Handles four message types:
    - user: spoken by the caller
    - assistant with content: spoken by the AI
    - assistant with tool_calls (empty content): AI triggered a tool/action
    - tool: the result returned by a tool call
    """
    lines = []
    for msg in transcript:
        role = msg.get("role", "unknown")
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if role == "user" and content.strip():
            lines.append(f"Customer: {content.strip()}")

        elif role == "assistant":
            if content.strip():
                lines.append(f"AI Agent: {content.strip()}")
            elif tool_calls:
                for tc in tool_calls:
                    fn_name = ""
                    if isinstance(tc, dict):
                        fn_name = tc.get("function", {}).get("name", "") or tc.get("name", "")
                    elif hasattr(tc, "function"):
                        fn_name = getattr(tc.function, "name", "")
                    if fn_name:
                        lines.append(
                            f"AI Agent: [Action taken: {_humanize_action_name(fn_name)}]"
                        )

        elif role == "tool":
            snippet = content.strip()[:_MAX_TOOL_RESULT_CHARS] if content else ""
            if snippet:
                lines.append(f"System: [Tool result: {snippet}]")

    return "\n".join(lines)


def _build_call_context(call_log: CallLog, db: Session) -> str:
    """Build a CALL CONTEXT block summarising call metadata for the ACW prompt.

    Includes duration, masked caller number, call outcome, and transfer details
    so the LLM can make accurate disposition / resolution / quality decisions.
    """
    lines = ["CALL CONTEXT:"]

    # Task #397 — judge pacing against the AI conversation leg (authoritative
    # Pipecat duration), not the billing duration which includes transfer time.
    # Matches the dashboard's Duration display exactly. Falls back to the
    # billing duration when no AI leg exists (legacy rows).
    ai_leg_seconds = sum(
        leg.duration_seconds or 0
        for leg in db.query(CallLeg)
        .filter(
            CallLeg.call_log_id == call_log.id,
            CallLeg.leg_type == LegType.AI_CONVERSATION.value,
            CallLeg.duration_source == "pipecat",
        )
        .all()
    )
    if ai_leg_seconds > 0:
        lines.append(f"- AI Conversation Duration: {_fmt_duration(ai_leg_seconds)}")
    else:
        lines.append(f"- Duration: {_fmt_duration(call_log.duration_seconds)}")

    if call_log.caller_number:
        lines.append(f"- Caller: {_mask_number(call_log.caller_number)}")

    outcome = call_log.outcome or "unknown"
    lines.append(f"- Outcome: {outcome}")

    if call_log.has_transfer:
        transfer_mode = call_log.transfer_mode or "warm"
        legs: List[CallLeg] = (
            db.query(CallLeg)
            .filter(
                CallLeg.call_log_id == call_log.id,
                CallLeg.leg_type.in_(list(_TRANSFER_LEG_TYPES)),
            )
            .order_by(CallLeg.leg_number)
            .all()
        )
        if legs:
            for leg in legs:
                dest = _mask_number(leg.participant or "")
                status = leg.status or "unknown"
                status_label = {
                    "completed": "answered and connected",
                    "no_answer": "no-answer (not connected)",
                    "busy": "busy",
                    "failed": "failed",
                    "canceled": "canceled",
                }.get(status, status)
                lines.append(
                    f"- Transfer: {transfer_mode} transfer to {dest} → result: {status_label}"
                )
        else:
            lines.append(f"- Transfer: {transfer_mode} transfer (no leg details available)")

    return "\n".join(lines)


def _stamp_acw_skip(call_log: CallLog, db: Session, reason: str) -> Dict[str, Any]:
    """Persist a terminal ACW skip state so rows do not look indefinitely pending."""
    logger.info(f"ACW skipped for call {call_log.id}: {reason}")
    try:
        call_log.acw_skip_reason = reason
        if not call_log.acw_completed_at:
            call_log.acw_completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        logger.warning(f"Failed to stamp acw_skip_reason for {call_log.id}: {exc}")
        db.rollback()
    return {"skipped": True, "reason": reason}


def _normalize_option_key(value: Any) -> str:
    return str(value or "").strip().casefold()


def _find_option_by_id_or_name(options: List[Any], option_id: Any, option_name: Any):
    """Match configured option IDs first, names second for legacy compatibility."""
    if option_id:
        wanted_id = str(option_id).strip()
        for option in options:
            if str(option.id) == wanted_id:
                return option

    wanted_name = _normalize_option_key(option_name)
    if wanted_name:
        for option in options:
            if _normalize_option_key(option.name) == wanted_name:
                return option

    return None


def _build_acw_response_schema(
    *,
    dispositions: List[AssistantDisposition],
    resolution_options: List[AssistantResolutionOption],
    has_quality: bool,
    has_summary: bool,
) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    required: List[str] = []

    if dispositions:
        properties["disposition_id"] = {
            "type": "string",
            "enum": [str(d.id) for d in dispositions],
            "description": "ID of the selected disposition.",
        }
        required.append("disposition_id")

    if resolution_options:
        properties["resolution_option_id"] = {
            "type": "string",
            "enum": [str(r.id) for r in resolution_options],
            "description": "ID of the selected resolution option.",
        }
        required.append("resolution_option_id")

    if has_quality:
        properties["quality_score"] = {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
        }
        required.append("quality_score")

    if has_summary:
        properties["summary"] = {"type": "string"}
        required.append("summary")

    # Task #397 — topic is always part of the QA response. Length limits are
    # NOT expressed here (OpenAI strict mode rejects maxLength); the 3-word
    # cap is enforced server-side by _sanitize_topic.
    properties["topic"] = {
        "type": "string",
        "description": "Main topic of the call in 3 words or less, Title Case.",
    }
    required.append("topic")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _json_schema_response_format(schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "post_call_qa",
            "strict": True,
            "schema": schema,
        },
    }


def should_auto_run_acw(assistant: Optional[Assistant], call_sid: Optional[str] = None) -> bool:
    """Return whether ACW should auto-run and log actionable diagnostics.

    This preserves current behavior: only explicit acw_config.auto_run=true
    enables automatic post-call QA.
    """
    if not assistant:
        logger.warning(f"ACW auto-run skipped for call {call_sid}: assistant not found")
        return False

    acw_config = assistant.acw_config or {}
    auto_run = acw_config.get("auto_run")
    if auto_run is True:
        return True

    logger.info(
        "ACW auto-run skipped for call "
        f"{call_sid}: assistant_id={assistant.id} auto_run={auto_run!r} "
        f"acw_config_keys={sorted(acw_config.keys())}"
    )
    return False


def run_acw(call_log: CallLog, db: Session) -> Dict[str, Any]:
    # Task #98 — short-circuit when the caller never spoke. There is nothing
    # for the LLM to score, classify, or summarize. Stamp acw_completed_at
    # and acw_skip_reason so the UI can show a clean "No Caller Audio" badge
    # instead of leaving the row dangling in a perpetual "ACW pending" state.
    if call_log.caller_spoke is False:
        return _stamp_acw_skip(call_log, db, "no_caller_audio")

    if not call_log.transcript:
        return _stamp_acw_skip(call_log, db, "no_transcript")

    assistant = db.query(Assistant).filter(Assistant.id == call_log.assistant_id).first()
    if not assistant:
        return _stamp_acw_skip(call_log, db, "no_assistant")

    acw_config = assistant.acw_config or {}

    dispositions = (
        db.query(AssistantDisposition)
        .filter(
            AssistantDisposition.assistant_id == assistant.id,
            AssistantDisposition.is_active == True,
        )
        .order_by(AssistantDisposition.display_order)
        .all()
    )

    resolution_options = (
        db.query(AssistantResolutionOption)
        .filter(
            AssistantResolutionOption.assistant_id == assistant.id,
            AssistantResolutionOption.is_active == True,
        )
        .order_by(AssistantResolutionOption.display_order)
        .all()
    )

    quality_rubric = acw_config.get("quality_rubric", "")
    summary_enabled = acw_config.get("summary_enabled", False)
    summary_prompt = acw_config.get("summary_prompt", "")

    has_dispositions = len(dispositions) > 0
    has_resolutions = len(resolution_options) > 0
    has_quality = bool(quality_rubric and quality_rubric.strip())
    has_summary = summary_enabled

    # Task #397 — topic generation is always-on for auto-run assistants, so a
    # QA config with no sections enabled still produces a topic-only run.
    # Assistants without auto_run keep the original skip (manual behavior
    # unchanged for operators who never turned QA on).
    auto_run_enabled = acw_config.get("auto_run") is True
    if (
        not any([has_dispositions, has_resolutions, has_quality, has_summary])
        and not auto_run_enabled
    ):
        return _stamp_acw_skip(call_log, db, "no_sections_enabled")

    transcript_text = _build_transcript_text(call_log.transcript)
    if not transcript_text.strip():
        return _stamp_acw_skip(call_log, db, "empty_transcript")

    if len(transcript_text) > _MAX_TRANSCRIPT_CHARS:
        truncated = transcript_text[:_MAX_TRANSCRIPT_CHARS]
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        transcript_text = truncated + "\n[Transcript truncated due to length]"
        logger.info(f"ACW: transcript truncated for call {call_log.id}")

    call_context = _build_call_context(call_log, db)
    prompt_parts = [f"Assistant: {assistant.name}\nAnalyze this call transcript.\n\n{call_context}"]
    json_fields = []

    # Task #397 — give the QA judge the assistant's actual mission so scores
    # and classifications are graded against what the agent was *supposed* to
    # do, not a generic notion of a good call.
    assistant_purpose = (assistant.system_prompt or "").strip()
    if assistant_purpose:
        if len(assistant_purpose) > _MAX_SYSTEM_PROMPT_CHARS:
            assistant_purpose = (
                assistant_purpose[:_MAX_SYSTEM_PROMPT_CHARS] + "\n[... truncated]"
            )
        prompt_parts.append(
            "ASSISTANT PURPOSE (what this AI agent was configured to do — judge "
            f"the call against this):\n{assistant_purpose}"
        )

    if has_dispositions:
        disp_list = "\n".join(
            f"- id={d.id} | name={d.name} | description={d.description or 'No description'}"
            for d in dispositions
        )
        prompt_parts.append(
            f"DISPOSITION (required) - pick exactly one active option and return its id:\n{disp_list}"
        )
        json_fields.append('"disposition_id": "selected disposition id"')

    if has_resolutions:
        res_list = "\n".join(
            f"- id={r.id} | name={r.name} | description={r.description or 'No description'}"
            for r in resolution_options
        )
        prompt_parts.append(
            f"RESOLUTION (required) - pick exactly one active option and return its id:\n{res_list}"
        )
        json_fields.append('"resolution_option_id": "selected resolution option id"')

    if has_quality:
        prompt_parts.append(
            f"QUALITY SCORE — rate 0-100 using this rubric:\n{quality_rubric}\n"
            "Anchor the score to these bands (apply them consistently):\n"
            "- 90-100: excellent — caller's goal fully achieved, information accurate, no notable errors\n"
            "- 70-89: good — goal achieved with minor issues (awkward phrasing, small delays, minor omissions)\n"
            "- 50-69: fair — notable problems (wrong or missing information, skipped steps, goal only partly met)\n"
            "- 25-49: poor — major failures, caller's goal mostly unmet\n"
            "- 0-24: failed — the call did not serve its purpose"
        )
        json_fields.append('"quality_score": integer 0-100')

    if has_summary:
        if summary_prompt and summary_prompt.strip():
            prompt_parts.append(f"SUMMARY — {summary_prompt.strip()}")
        else:
            prompt_parts.append(
                "SUMMARY — Provide a concise 2-3 sentence summary: caller intent, actions taken, outcome."
            )
        json_fields.append('"summary": "..."')

    # Task #397 — topic is always requested, regardless of configured sections.
    prompt_parts.append(
        "TOPIC (required) — State the main topic of this call in 3 words or "
        'less, e.g. "Room Booking", "Checkout Time", "Cake Order". '
        "Use Title Case. No punctuation."
    )
    json_fields.append('"topic": "main call topic, 3 words or less"')

    prompt_parts.append(f"\nTranscript:\n{transcript_text}")
    prompt_parts.append(f"\nRespond ONLY with JSON:\n{{{', '.join(json_fields)}}}")

    full_prompt = "\n\n".join(prompt_parts)
    response_schema = _build_acw_response_schema(
        dispositions=dispositions if has_dispositions else [],
        resolution_options=resolution_options if has_resolutions else [],
        has_quality=has_quality,
        has_summary=has_summary,
    )

    result: Dict[str, Any] = {}
    selected_disposition = None
    selected_resolution = None
    validation_errors: List[str] = []
    try:
        client = _get_client()
        model = acw_config.get("llm_model", "gpt-4o-mini")
        system_fields = []
        if has_dispositions:
            system_fields.append("disposition_id")
        if has_resolutions:
            system_fields.append("resolution_option_id")
        if has_quality:
            system_fields.append("quality_score")
        if has_summary:
            system_fields.append("summary")

        system_content = (
            "You are a call center QA analyst. Analyze the call transcript and "
            "return only valid JSON. Always include a 'topic' field: the call's "
            "main topic in 3 words or less."
        )
        if system_fields:
            system_content += (
                " Select exactly one configured option ID for each required "
                f"classification field: {', '.join(system_fields)}."
            )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": full_prompt},
        ]

        for attempt in range(1, _MAX_LLM_ATTEMPTS + 1):
            if attempt == 1:
                response_format = _json_schema_response_format(response_schema)
            else:
                response_format = {"type": "json_object"}
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous response did not validate against the configured "
                            "ACW options. Return only JSON using the exact option IDs listed "
                            "in the transcript analysis prompt."
                        ),
                    }
                )

            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    temperature=0,
                )
            except Exception as create_exc:
                if attempt == 1:
                    logger.warning(
                        "ACW strict JSON schema call failed for call "
                        f"{call_log.id}: {create_exc}; retrying with JSON object mode"
                    )
                    continue
                raise

            result = json.loads(response.choices[0].message.content or "{}")
            validation_errors = []
            selected_disposition = None
            selected_resolution = None

            if has_dispositions:
                selected_disposition = _find_option_by_id_or_name(
                    dispositions,
                    result.get("disposition_id"),
                    result.get("disposition"),
                )
                if not selected_disposition:
                    validation_errors.append(
                        "missing_or_invalid_disposition_id="
                        f"{result.get('disposition_id')!r} disposition={result.get('disposition')!r}"
                    )

            if has_resolutions:
                selected_resolution = _find_option_by_id_or_name(
                    resolution_options,
                    result.get("resolution_option_id"),
                    result.get("resolution"),
                )
                if not selected_resolution:
                    validation_errors.append(
                        "missing_or_invalid_resolution_option_id="
                        f"{result.get('resolution_option_id')!r} resolution={result.get('resolution')!r}"
                    )

            if not validation_errors:
                break

            logger.warning(
                f"ACW validation failed for call {call_log.id} on attempt "
                f"{attempt}/{_MAX_LLM_ATTEMPTS}: {validation_errors}"
            )

        if validation_errors:
            # Task #397 — terminal stamp: without acw_completed_at the row
            # stays "QA pending" forever. Manual re-run remains possible
            # because run_acw_in_thread re-runs any row with a skip reason.
            call_log.acw_skip_reason = "classification_invalid"
            if not call_log.acw_completed_at:
                call_log.acw_completed_at = datetime.utcnow()
            # Topic is independent of classification — keep it if usable.
            topic_value = _sanitize_topic(result.get("topic"))
            if topic_value:
                call_log.acw_topic = topic_value
            db.commit()
            return {"error": "classification_invalid", "details": validation_errors}
    except Exception as e:
        logger.exception(f"ACW LLM call failed for call {call_log.id}: {e}")
        # Task #397 — stamp a terminal skip state so the row never sits in
        # "QA pending" after an LLM outage. Manual re-run clears it on success.
        try:
            call_log.acw_skip_reason = "llm_error"
            if not call_log.acw_completed_at:
                call_log.acw_completed_at = datetime.utcnow()
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                f"ACW: failed to stamp llm_error skip state for call {call_log.id}"
            )
        return {"error": str(e)}

    if selected_disposition:
        call_log.disposition_id = selected_disposition.id

    if selected_resolution:
        call_log.acw_resolution = selected_resolution.name

    if has_quality:
        score = result.get("quality_score")
        if isinstance(score, (int, float)):
            call_log.acw_quality_score = max(0, min(100, int(score)))

    if has_summary:
        summary_text = result.get("summary", "")
        if summary_text:
            call_log.ai_summary = summary_text

    # Task #397 — topic is best-effort: a missing/garbage topic never blocks
    # dispositions, resolution, quality, or summary.
    topic_value = _sanitize_topic(result.get("topic"))
    if topic_value:
        call_log.acw_topic = topic_value

    call_log.acw_skip_reason = None
    call_log.acw_completed_at = datetime.utcnow()
    db.commit()

    logger.info(f"ACW completed for call {call_log.id}")

    return {
        "success": True,
        "disposition": selected_disposition.to_dict() if selected_disposition else None,
        "acw_resolution": call_log.acw_resolution,
        "acw_quality_score": call_log.acw_quality_score,
        "summary": call_log.ai_summary,
        "acw_topic": call_log.acw_topic,
        "acw_completed_at": call_log.acw_completed_at.isoformat() + "Z"
        if call_log.acw_completed_at
        else None,
    }


def run_acw_in_thread(call_log_id: UUID) -> Dict[str, Any]:
    """Thread-safe ACW runner.

    Creates and owns its own DB session so it is safe to call from any thread
    (including a thread-pool executor) without sharing a session across threads.
    Re-checks ``acw_completed_at`` before starting to handle races between
    concurrent background tasks.
    """
    from botelier.database import SessionLocal

    db = SessionLocal()
    try:
        call_log = db.query(CallLog).filter(CallLog.id == call_log_id).first()
        if not call_log:
            logger.warning(f"ACW thread: call log {call_log_id} not found")
            return {"error": "call_log_not_found"}
        # Task #397 — a row is only "already completed" when it finished
        # cleanly (no skip reason). Rows stamped with a terminal skip state
        # (llm_error, classification_invalid, no_transcript, ...) stay
        # re-runnable via the manual QA endpoint; a successful re-run clears
        # the skip reason. Auto-run dedupe still checks acw_completed_at
        # upstream, so terminal skips are not re-enqueued automatically
        # (edge case: a task already in flight when the skip was stamped may
        # re-run once — bounded and idempotent).
        if call_log.acw_completed_at and not call_log.acw_skip_reason:
            logger.debug(f"ACW thread: already completed for {call_log_id}, skipping")
            return {"skipped": True, "reason": "already_completed"}
        return run_acw(call_log, db)
    except Exception as e:
        logger.exception(f"ACW thread runner failed for {call_log_id}: {e}")
        return {"error": str(e)}
    finally:
        db.close()


async def run_acw_background(call_log_id: UUID):
    """Async background task: polls for transcript readiness then runs ACW in a thread.

    Polling uses ``asyncio.sleep`` so no thread-pool worker is held while waiting.
    The actual ACW work (OpenAI call + DB writes) runs in a thread-pool executor
    via ``run_acw_in_thread``, which owns its own session — safe across threads.
    """
    import asyncio

    from botelier.database import SessionLocal

    # --- polling phase: wait for transcript using a dedicated session ---
    transcript_ready = False
    db = SessionLocal()
    try:
        max_retries = 5
        call_log = None
        for attempt in range(max_retries):
            call_log = db.query(CallLog).filter(CallLog.id == call_log_id).first()
            if not call_log:
                logger.warning(f"ACW background: call log {call_log_id} not found")
                return
            if call_log.acw_completed_at:
                logger.debug(
                    f"ACW background: already completed for {call_log_id}, skipping"
                )
                return
            if call_log.transcript:
                transcript_ready = True
                break
            # Expire before sleeping so the next loop iteration re-fetches from DB
            # rather than returning the identity-mapped cached object.
            db.expire(call_log)
            wait = 2 * (attempt + 1)
            logger.info(
                f"ACW background: transcript not ready for {call_log_id}, "
                f"retry {attempt + 1}/{max_retries} in {wait}s"
            )
            await asyncio.sleep(wait)
        else:
            logger.warning(
                f"ACW background: transcript never arrived for {call_log_id}, skipping"
            )
            if call_log:
                _stamp_acw_skip(call_log, db, "transcript_not_ready")
    except Exception as e:
        logger.exception(f"ACW background polling failed for {call_log_id}: {e}")
    finally:
        db.close()

    if not transcript_ready:
        return

    # --- execution phase: run ACW in a thread with its own session ---
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, run_acw_in_thread, call_log_id)
