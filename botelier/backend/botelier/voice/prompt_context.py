"""Shared system-prompt composition for live voice and Test Lab."""

from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC_TIMEZONE = "UTC"
ASSISTANT_LOCAL_TIME_HEADING = "## ASSISTANT LOCAL TIME"


def resolve_assistant_timezone(timezone_name: Optional[str]) -> tuple[str, ZoneInfo]:
    """Resolve an IANA timezone, explicitly falling back to UTC."""
    candidate = (timezone_name or "").strip() or UTC_TIMEZONE
    try:
        return candidate, ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC_TIMEZONE, ZoneInfo(UTC_TIMEZONE)


def assistant_local_datetime(
    timezone_name: Optional[str], now: datetime
) -> tuple[str, datetime]:
    """Return the resolved IANA name and the supplied instant in local time."""
    resolved_name, zone = resolve_assistant_timezone(timezone_name)
    instant = now
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return resolved_name, instant.astimezone(zone)


def build_assistant_local_time_segment(
    timezone_name: Optional[str], now: datetime
) -> str:
    """Build the compact volatile assistant-local clock prompt segment."""
    resolved_name, local_now = assistant_local_datetime(timezone_name, now)
    offset = local_now.strftime("%z")
    formatted_offset = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    return (
        f"{ASSISTANT_LOCAL_TIME_HEADING}\n"
        f"Date: {local_now:%Y-%m-%d} | Time: {local_now:%H:%M:%S} | "
        f"Timezone: {resolved_name} | UTC offset: {formatted_offset}"
    )


def compose_assistant_system_prompt(
    static_sections: Iterable[str],
    timezone_name: Optional[str],
    *,
    now: datetime,
    dynamic_sections: Iterable[str] = (),
) -> str:
    """Compose stable content, then local clock, then other dynamic context."""
    stable = [section.strip() for section in static_sections if section and section.strip()]
    dynamic = [section.strip() for section in dynamic_sections if section and section.strip()]
    return "\n\n".join(
        stable + [build_assistant_local_time_segment(timezone_name, now)] + dynamic
    )


def build_runtime_system_prompt(
    assistant_prompt: str,
    flow_executors: Iterable[Any],
    timezone_name: Optional[str],
    *,
    now: datetime,
) -> str:
    """Build the identical live/Test Lab prompt from resolved runtime inputs."""
    executors = list(flow_executors)
    personas = [
        persona
        for executor in executors
        if (persona := executor.get_flow_persona_section())
    ]
    return build_runtime_system_prompt_from_parts(
        assistant_prompt,
        personas,
        bool(executors),
        any(executor.has_past_date_slot() for executor in executors),
        timezone_name,
        now=now,
    )


def build_runtime_system_prompt_from_parts(
    assistant_prompt: str,
    flow_personas: Iterable[str],
    has_flow: bool,
    has_past_date_slot: bool,
    timezone_name: Optional[str],
    *,
    now: datetime,
) -> str:
    """Build a runtime prompt from serializable live-pipeline prompt parts."""
    from botelier.flow_executor import build_flow_behavioral_rules

    personas = [persona for persona in flow_personas if persona]
    static_sections = [assistant_prompt, *personas]
    if has_flow:
        _, local_now = assistant_local_datetime(timezone_name, now)
        static_sections.append(
            build_flow_behavioral_rules(
                local_now.strftime("%Y-%m-%d"),
                has_past_date_slot,
            )
        )
    return compose_assistant_system_prompt(
        static_sections,
        timezone_name,
        now=now,
    )


def static_prompt_prefix(prompt: str) -> str:
    """Return the byte-stable content preceding the volatile clock segment."""
    marker = f"\n\n{ASSISTANT_LOCAL_TIME_HEADING}\n"
    return prompt.split(marker, 1)[0]