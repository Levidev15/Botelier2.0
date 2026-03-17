import json
import os
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

from loguru import logger
from openai import OpenAI
from sqlalchemy.orm import Session

from botelier.models.call_log import CallLog
from botelier.models.assistant import Assistant
from botelier.models.disposition import AssistantDisposition
from botelier.models.resolution_option import AssistantResolutionOption


_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


_MAX_TRANSCRIPT_CHARS = 8000

_ROLE_LABELS = {
    "user": "Customer",
    "assistant": "AI Agent",
}


def _build_transcript_text(transcript: list) -> str:
    lines = []
    for msg in transcript:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content.strip():
            label = _ROLE_LABELS.get(role, role)
            lines.append(f"{label}: {content}")
    return "\n".join(lines)


def run_acw(call_log: CallLog, db: Session) -> Dict[str, Any]:
    if not call_log.transcript:
        logger.warning(f"ACW skipped for call {call_log.id}: no transcript")
        return {"skipped": True, "reason": "no_transcript"}

    assistant = db.query(Assistant).filter(Assistant.id == call_log.assistant_id).first()
    if not assistant:
        logger.warning(f"ACW skipped for call {call_log.id}: assistant not found")
        return {"skipped": True, "reason": "no_assistant"}

    acw_config = assistant.acw_config or {}

    dispositions = db.query(AssistantDisposition).filter(
        AssistantDisposition.assistant_id == assistant.id,
        AssistantDisposition.is_active == True
    ).order_by(AssistantDisposition.display_order).all()

    resolution_options = db.query(AssistantResolutionOption).filter(
        AssistantResolutionOption.assistant_id == assistant.id,
        AssistantResolutionOption.is_active == True
    ).order_by(AssistantResolutionOption.display_order).all()

    quality_rubric = acw_config.get("quality_rubric", "")
    summary_enabled = acw_config.get("summary_enabled", False)
    summary_prompt = acw_config.get("summary_prompt", "")

    has_dispositions = len(dispositions) > 0
    has_resolutions = len(resolution_options) > 0
    has_quality = bool(quality_rubric and quality_rubric.strip())
    has_summary = summary_enabled

    if not any([has_dispositions, has_resolutions, has_quality, has_summary]):
        logger.info(f"ACW skipped for call {call_log.id}: no sections enabled")
        return {"skipped": True, "reason": "no_sections_enabled"}

    transcript_text = _build_transcript_text(call_log.transcript)
    if not transcript_text.strip():
        logger.warning(f"ACW skipped for call {call_log.id}: empty transcript")
        return {"skipped": True, "reason": "empty_transcript"}

    if len(transcript_text) > _MAX_TRANSCRIPT_CHARS:
        truncated = transcript_text[:_MAX_TRANSCRIPT_CHARS]
        last_newline = truncated.rfind("\n")
        if last_newline > 0:
            truncated = truncated[:last_newline]
        transcript_text = truncated + "\n[Transcript truncated due to length]"
        logger.info(f"ACW: transcript truncated for call {call_log.id}")

    prompt_parts = [f"Assistant: {assistant.name}\nAnalyze this call transcript.\n"]
    json_fields = []

    if has_dispositions:
        disp_list = "\n".join(
            f"- {d.name}: {d.description or 'No description'}" for d in dispositions
        )
        prompt_parts.append(
            f"DISPOSITIONS — pick the single best match:\n{disp_list}"
        )
        json_fields.append('"disposition": "exact name from list or null"')

    if has_resolutions:
        res_list = "\n".join(
            f"- {r.name}: {r.description or 'No description'}" for r in resolution_options
        )
        prompt_parts.append(
            f"RESOLUTION STATUS — pick the single best match:\n{res_list}"
        )
        json_fields.append('"resolution": "exact name from list or null"')

    if has_quality:
        prompt_parts.append(
            f"QUALITY SCORE — rate 0-100 using this rubric:\n{quality_rubric}"
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

    prompt_parts.append(f"\nTranscript:\n{transcript_text}")
    prompt_parts.append(f"\nRespond ONLY with JSON:\n{{{', '.join(json_fields)}}}")

    full_prompt = "\n\n".join(prompt_parts)

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a call center QA analyst. Return only valid JSON."},
                {"role": "user", "content": full_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        result = json.loads(response.choices[0].message.content)
    except Exception as e:
        logger.exception(f"ACW LLM call failed for call {call_log.id}: {e}")
        return {"error": str(e)}

    selected_disposition = None
    if has_dispositions:
        disposition_name = result.get("disposition")
        if disposition_name:
            for d in dispositions:
                if d.name.lower() == disposition_name.lower():
                    call_log.disposition_id = d.id
                    selected_disposition = d.to_dict()
                    break

    if has_resolutions:
        resolution_name = result.get("resolution")
        if resolution_name:
            valid_names = {r.name.lower(): r.name for r in resolution_options}
            matched = valid_names.get(resolution_name.lower())
            if matched:
                call_log.acw_resolution = matched
            else:
                logger.warning(f"ACW: LLM returned unrecognized resolution '{resolution_name}' for call {call_log.id}")
                call_log.acw_resolution = None

    if has_quality:
        score = result.get("quality_score")
        if isinstance(score, (int, float)):
            call_log.acw_quality_score = max(0, min(100, int(score)))

    if has_summary:
        summary_text = result.get("summary", "")
        if summary_text:
            call_log.ai_summary = summary_text

    call_log.acw_completed_at = datetime.utcnow()
    db.commit()

    logger.info(f"ACW completed for call {call_log.id}")

    return {
        "success": True,
        "disposition": selected_disposition,
        "acw_resolution": call_log.acw_resolution,
        "acw_quality_score": call_log.acw_quality_score,
        "summary": call_log.ai_summary,
        "acw_completed_at": call_log.acw_completed_at.isoformat() + "Z" if call_log.acw_completed_at else None,
    }


def run_acw_background(call_log_id: UUID):
    import time
    from botelier.database import SessionLocal
    db = SessionLocal()
    try:
        max_retries = 5
        for attempt in range(max_retries):
            call_log = db.query(CallLog).filter(CallLog.id == call_log_id).first()
            if not call_log:
                logger.warning(f"ACW background: call log {call_log_id} not found")
                return
            if call_log.transcript:
                break
            db.expire(call_log)
            wait = 2 * (attempt + 1)
            logger.info(f"ACW background: transcript not ready for {call_log_id}, retry {attempt+1}/{max_retries} in {wait}s")
            time.sleep(wait)
        else:
            logger.warning(f"ACW background: transcript never arrived for {call_log_id}, skipping")
            return
        run_acw(call_log, db)
    except Exception as e:
        logger.exception(f"ACW background task failed for call {call_log_id}: {e}")
    finally:
        db.close()
