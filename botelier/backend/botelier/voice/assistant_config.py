"""Build the existing voice configuration for both voice and text hosts.

Keep assistant/knowledge settings in one place. This does not start a call,
construct a provider, select a flow, or expose the private prompt to a client.
"""

import asyncio

from loguru import logger

from .agent import AgentStatus, VoiceAgentConfig


async def build_assistant_agent_config(assistant) -> VoiceAgentConfig:
    """Resolve the same assistant settings and private knowledge used by voice."""
    from .knowledge_handler import load_knowledge_for_prompt

    status = AgentStatus.ACTIVE if assistant.is_active else AgentStatus.PAUSED
    base_prompt = assistant.system_prompt or "You are a friendly assistant."
    kb_content = ""
    if assistant.knowledge_base_id:
        try:
            kb_content = await asyncio.to_thread(
                load_knowledge_for_prompt, str(assistant.knowledge_base_id),
            )
        except Exception as exc:
            # Preserve the existing base-prompt fallback, but never log a
            # provider/database error body or the knowledge itself.
            logger.error(
                "assistant_knowledge_load_failed category={}",
                type(exc).__name__,
            )

    if kb_content:
        # Keep the stable persona/guidelines before the changing knowledge
        # suffix, preserving the current voice prompt-cache behavior.
        enhanced_prompt = f"""{base_prompt}

## RESPONSE GUIDELINES
- Answer questions from the knowledge base naturally and conversationally
- Keep responses concise (under 50 words) since this is a phone call
- Only transfer to a human if: (1) the caller explicitly requests to speak with someone, OR (2) the question requires information NOT in the knowledge base AND the caller needs urgent assistance
- For general questions covered by the knowledge base, answer directly without offering to transfer
- If the caller asks a question in the middle of a task, answer it briefly, then continue where you left off — do not lose your place or restart

## KNOWLEDGE BASE
You have access to the following Q&A knowledge base. Use this information to answer customer questions directly and confidently. Do NOT transfer the call or say you don't have information if the answer is in this knowledge base.

{kb_content}"""
        logger.info("assistant_knowledge_loaded characters={}", len(kb_content))
    else:
        enhanced_prompt = base_prompt

    return VoiceAgentConfig(
        agent_id=str(assistant.id),
        account_id=str(assistant.account_id),
        name=assistant.name,
        description=assistant.description,
        status=status,
        stt_provider=assistant.stt_provider,
        stt_model=assistant.stt_model,
        stt_language=assistant.language or "en",
        stt_config=assistant.stt_config or {},
        llm_provider=assistant.llm_provider,
        llm_model=assistant.llm_model,
        llm_temperature=0.7 if assistant.temperature is None else assistant.temperature,
        llm_max_tokens=assistant.max_tokens or 400,
        llm_config=assistant.llm_config or {},
        tts_provider=assistant.tts_provider,
        tts_voice_id=assistant.tts_voice or "",
        tts_model=assistant.tts_model,
        tts_speed=1.0,
        tts_config=assistant.tts_config or {},
        system_prompt=enhanced_prompt,
        greeting_message=assistant.first_message or "Hello! How can I help you today?",
        timezone=getattr(assistant, "timezone", None) or "UTC",
        enable_function_calling=True,
        enable_interruptions=(
            True if assistant.allow_interruptions is None else bool(assistant.allow_interruptions)
        ),
        enable_vad=assistant.vad_enabled,
        vad_provider=assistant.vad_provider,
        vad_config=assistant.vad_config or {},
    )
