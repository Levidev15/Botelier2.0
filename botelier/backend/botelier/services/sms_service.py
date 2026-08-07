"""SMS Service - Handles AI-powered SMS conversations.

This service processes incoming SMS messages by:
1. Finding or creating a conversation thread
2. Building LLM context (system prompt + KB + conversation history)
3. Calling OpenAI with tool support
4. Executing any tool calls (API Request tools)
5. Sending the AI response back via Twilio SMS
6. Saving all messages to the database

Reuses the same knowledge base, system prompt, and tools
as the voice assistant — just without STT/TTS.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from loguru import logger
from openai import OpenAI
from sqlalchemy.orm import Session
from twilio.rest import Client as TwilioClient

from botelier.database import SessionLocal
from botelier.models.assistant import Assistant
from botelier.models.knowledge_entry import KnowledgeEntry
from botelier.models.phone_number import PhoneNumber
from botelier.models.sms_conversation import (
    ConversationStatus,
    HandlerMode,
    MessageDirection,
    MessageSender,
    MessageStatus,
    SMSConversation,
    SMSMessage,
)
from botelier.models.tool import Tool, ToolType
from botelier.models.tool_set import ToolSet
from botelier.services.property_scope import resolve_session_property_id
from botelier.voice.knowledge_handler import load_knowledge_for_prompt

OPT_OUT_KEYWORDS = {"stop", "cancel", "unsubscribe", "end", "quit"}
OPT_IN_KEYWORDS = {"start", "yes", "unstop"}

DEFAULT_SESSION_TIMEOUT_HOURS = 24
DEFAULT_MAX_HISTORY_MESSAGES = 20
DEFAULT_MAX_RESPONSE_LENGTH = 480

SMS_BEHAVIOR_RULES = """
## SMS BEHAVIOR RULES
- Keep responses concise and under 300 characters when possible
- Do not use TTS-specific formatting (no currency speech conversion)
- Use natural texting tone (slightly less formal than phone)
- If the answer is lengthy, break into key bullet points
- Do not end every message with "How can I help you?"
- Never include emojis unless specifically instructed to
"""

HANDOFF_INSTRUCTION = """
## ESCALATION PROTOCOL — MANDATORY

When ANY of the following situations occur, you MUST escalate to a human agent:
- The customer wants to make, change, or cancel a RESERVATION or BOOKING
- The customer explicitly asks to speak with a human, manager, or real person
- You cannot fully answer or resolve the customer's request with available information
- The customer expresses frustration and requests human help

To escalate, start your ENTIRE response with [HANDOFF] — nothing before it.
The [HANDOFF] tag must be the very first characters of your message.

CORRECT: "[HANDOFF] I'm connecting you with our team who can assist with that reservation."
WRONG:   "I'll connect you with someone. [HANDOFF]"
WRONG:   "Sure! [HANDOFF] Let me transfer you."

If you CAN fully resolve the request yourself without needing a human, do NOT use [HANDOFF].
"""

HANDOFF_PREFIX = "[HANDOFF]"


_openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


class SMSService:
    """Handles SMS AI conversation processing."""

    def __init__(self, db: Session):
        self.db = db
        # Per-property isolation (Task #327). Resolved once per incoming message in
        # process_incoming_sms and used to scope integration resolution to
        # (account, property). None → legacy account-only scoping.
        self.session_property_id: Optional[str] = None
        # Per-conversation scope for durable capability idempotency (Task #330).
        # Resolved once per incoming message; SMS has no call SID, so this is the
        # stable contact key that keeps two guests' identical mutating capability
        # calls (e.g. the same payment amount) from colliding on one dedup key.
        self._current_conversation_id: Optional[str] = None
        # Per-turn MCP session state (Task #459). The live async MCPClient is
        # opened once at the start of an SMS turn that has an eligible MCP
        # connection, its schemas merged into the LLM tool list, and it is closed
        # at the end of the same turn. SMS has no long-lived call session, so the
        # client lifetime is exactly one incoming message → response cycle.
        self._mcp_client: Optional[Any] = None
        # Set of MCP tool names exposed to the LLM this turn (post native-name
        # collision filtering). Used to route tool_calls to the MCP client.
        self._mcp_tool_names: set = set()

    def process_incoming_sms(
        self,
        from_number: str,
        to_number: str,
        body: str,
        twilio_sid: Optional[str] = None,
        media_urls: Optional[List[str]] = None,
    ) -> tuple[Optional[str], Optional[str], bool]:
        """Process an incoming SMS and generate an AI response.

        Returns:
            (ai_response, conversation_id, handoff_triggered)
            ai_response     — text to send back, or None for no reply
            conversation_id — str UUID of the conversation (for SSE broadcast)
            handoff_triggered — True if the AI signalled [HANDOFF] this turn
        """
        phone_number = (
            self.db.query(PhoneNumber)
            .filter(
                PhoneNumber.phone_number == to_number,
                PhoneNumber.sms_enabled == True,
                PhoneNumber.is_active == True,
            )
            .first()
        )

        if not phone_number:
            logger.warning(
                f"SMS received on number {to_number} but no SMS-enabled phone number found"
            )
            return None, None, False

        sms_assistant_id = phone_number.sms_assistant_id or phone_number.assistant_id
        if not sms_assistant_id:
            logger.warning(f"No assistant assigned for SMS on {to_number}")
            return None, None, False

        assistant = (
            self.db.query(Assistant)
            .filter(
                Assistant.id == sms_assistant_id,
                Assistant.is_active == True,
            )
            .first()
        )

        if not assistant:
            logger.warning(f"Assistant {sms_assistant_id} not found or inactive")
            return None, None, False

        sms_config = assistant.sms_config or {}
        if not sms_config.get("enabled", False):
            logger.info(f"SMS is disabled on assistant {assistant.id}")
            return None, None, False

        # Per-property isolation (Task #327): resolve the property scope once for
        # this message from the texted number / assistant, then carry it through
        # every integration call this turn makes.
        self.session_property_id = resolve_session_property_id(
            dialed_number=to_number, assistant=assistant, db=self.db
        )

        normalized_body = body.strip().lower()

        # TCPA: STOP must always work immediately regardless of conversation state.
        if normalized_body in OPT_OUT_KEYWORDS:
            result = self._handle_opt_out(from_number, to_number, phone_number, twilio_sid)
            return result, None, False

        conversation = self._find_or_create_conversation(
            from_number, to_number, phone_number, assistant, sms_config
        )
        conv_id = str(conversation.id)
        # Stable per-conversation dedup scope for mutating capabilities (Task #330).
        self._current_conversation_id = conv_id

        # Opt-in (YES/START/UNSTOP) only triggers re-subscription when the
        # conversation is actually opted-out. In an active conversation these
        # words are normal customer messages and should be handled by the AI.
        if conversation.status == ConversationStatus.OPTED_OUT.value:
            if normalized_body in OPT_IN_KEYWORDS:
                result = self._handle_opt_in(from_number, to_number, phone_number, twilio_sid)
                return result, None, False
            logger.info(f"Ignoring SMS from opted-out number {from_number}")
            return None, conv_id, False

        inbound_msg = SMSMessage(
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND.value,
            sender=MessageSender.CUSTOMER.value,
            content=body,
            media_urls=media_urls,
            session_boundary=getattr(self, "_is_new_session", False),
            twilio_sid=twilio_sid,
            status=MessageStatus.RECEIVED.value,
        )
        self.db.add(inbound_msg)
        conversation.message_count = (conversation.message_count or 0) + 1
        conversation.last_message_at = datetime.utcnow()
        self.db.flush()

        # If a human agent has taken over, save the inbound message but stay silent.
        if conversation.handler_mode == "human":
            self.db.commit()
            logger.info(f"SMS conversation {conv_id} in human mode — AI silent, message saved")
            return None, conv_id, False

        ai_response, tools_called = self._generate_ai_response(
            assistant, sms_config, conversation, body
        )

        if not ai_response:
            ai_response = "I'm sorry, I wasn't able to process your message. Please try again."

        # Detect handoff signal from the AI
        handoff_triggered = False
        if ai_response.startswith(HANDOFF_PREFIX):
            ai_response = ai_response[len(HANDOFF_PREFIX) :].strip()
            conversation.handler_mode = "human"
            conversation.needs_attention = True
            handoff_triggered = True
            logger.info(f"AI triggered handoff on conversation {conv_id}")

        max_length = sms_config.get("max_response_length", DEFAULT_MAX_RESPONSE_LENGTH)
        if max_length and len(ai_response) > max_length:
            ai_response = ai_response[: max_length - 3] + "..."

        twilio_sid_out = self._send_twilio_sms(
            to_number, from_number, ai_response, phone_number.account_id
        )

        outbound_msg = SMSMessage(
            conversation_id=conversation.id,
            direction=MessageDirection.OUTBOUND.value,
            sender=MessageSender.AI.value,
            content=ai_response,
            status=MessageStatus.SENT.value,
            tool_calls=tools_called if tools_called else None,
            twilio_sid=twilio_sid_out,
        )
        self.db.add(outbound_msg)
        conversation.message_count = (conversation.message_count or 0) + 1
        conversation.last_message_at = datetime.utcnow()
        if conversation.first_response_at is None:
            conversation.first_response_at = datetime.utcnow()

        if tools_called:
            tool_names = list({tc["name"] for tc in tools_called})
            existing = conversation.tools_used or ""
            existing_set = set(existing.split(", ")) if existing else set()
            existing_set.update(tool_names)
            existing_set.discard("")
            conversation.tools_used = ", ".join(sorted(existing_set))

        self.db.commit()

        logger.info(
            f"SMS processed: {from_number} -> {to_number} | "
            f"Conv: {conv_id} | Handoff: {handoff_triggered} | Tools: {tools_called or 'none'}"
        )

        return ai_response, conv_id, handoff_triggered

    def _handle_opt_out(
        self, from_number: str, to_number: str, phone_number: PhoneNumber, twilio_sid: Optional[str]
    ) -> str:
        conversation = (
            self.db.query(SMSConversation)
            .filter(
                SMSConversation.customer_number == from_number,
                SMSConversation.botelier_number == to_number,
                SMSConversation.account_id == phone_number.account_id,
            )
            .order_by(SMSConversation.last_message_at.desc())
            .first()
        )

        if conversation:
            conversation.status = ConversationStatus.OPTED_OUT.value
            conversation.closed_at = datetime.utcnow()
        else:
            conversation = SMSConversation(
                account_id=phone_number.account_id,
                customer_number=from_number,
                botelier_number=to_number,
                phone_number_id=phone_number.id,
                status=ConversationStatus.OPTED_OUT.value,
                closed_at=datetime.utcnow(),
            )
            self.db.add(conversation)

        inbound_msg = SMSMessage(
            conversation_id=conversation.id if conversation.id else None,
            direction=MessageDirection.INBOUND.value,
            sender=MessageSender.CUSTOMER.value,
            content="STOP",
            twilio_sid=twilio_sid,
            status=MessageStatus.RECEIVED.value,
        )
        self.db.flush()
        if not inbound_msg.conversation_id:
            inbound_msg.conversation_id = conversation.id
        self.db.add(inbound_msg)
        self.db.commit()

        logger.info(f"Opt-out processed for {from_number} on {to_number}")
        return "You have been unsubscribed and will no longer receive messages. Reply START to re-subscribe."

    def _handle_opt_in(
        self, from_number: str, to_number: str, phone_number: PhoneNumber, twilio_sid: Optional[str]
    ) -> str:
        conversation = (
            self.db.query(SMSConversation)
            .filter(
                SMSConversation.customer_number == from_number,
                SMSConversation.botelier_number == to_number,
                SMSConversation.account_id == phone_number.account_id,
                SMSConversation.status == ConversationStatus.OPTED_OUT.value,
            )
            .order_by(SMSConversation.last_message_at.desc())
            .first()
        )

        if conversation:
            conversation.status = ConversationStatus.ACTIVE.value
            conversation.closed_at = None
            self.db.commit()
            logger.info(f"Opt-in processed for {from_number} on {to_number}")

        return "You have been re-subscribed. You will now receive messages again."

    def _find_or_create_conversation(
        self,
        from_number: str,
        to_number: str,
        phone_number: PhoneNumber,
        assistant: Assistant,
        sms_config: Dict[str, Any],
    ) -> SMSConversation:
        """Find or create a unified conversation thread.

        All messages from the same customer to the same Botelier number
        are grouped into one thread. Session boundaries are tracked on
        individual messages rather than splitting into separate conversations.
        """
        conversation = (
            self.db.query(SMSConversation)
            .filter(
                SMSConversation.customer_number == from_number,
                SMSConversation.botelier_number == to_number,
                SMSConversation.account_id == phone_number.account_id,
                SMSConversation.status != ConversationStatus.OPTED_OUT.value,
            )
            .order_by(SMSConversation.last_message_at.desc())
            .first()
        )

        if conversation:
            if conversation.status == ConversationStatus.CLOSED.value:
                # New session after close — reopen and hand control back to AI.
                # Any previous handoff state belongs to the prior session.
                conversation.status = ConversationStatus.ACTIVE.value
                conversation.closed_at = None
                conversation.handler_mode = HandlerMode.AI.value
                conversation.needs_attention = False
            conversation.assistant_id = assistant.id
            self._is_new_session = self._check_session_boundary(conversation, sms_config)
            return conversation

        conversation = SMSConversation(
            account_id=phone_number.account_id,
            assistant_id=assistant.id,
            phone_number_id=phone_number.id,
            customer_number=from_number,
            botelier_number=to_number,
            status=ConversationStatus.ACTIVE.value,
            message_count=0,
        )
        self.db.add(conversation)
        self.db.flush()
        self._is_new_session = False

        logger.info(f"Created new SMS conversation {conversation.id} for {from_number}")
        return conversation

    def _check_session_boundary(
        self, conversation: SMSConversation, sms_config: Dict[str, Any]
    ) -> bool:
        """Check if enough time has elapsed to mark a session boundary."""
        session_timeout_hours = sms_config.get(
            "session_timeout_hours", DEFAULT_SESSION_TIMEOUT_HOURS
        )
        cutoff = datetime.utcnow() - timedelta(hours=session_timeout_hours)

        if conversation.last_message_at and conversation.last_message_at < cutoff:
            return True
        return False

    def _generate_ai_response(
        self,
        assistant: Assistant,
        sms_config: Dict[str, Any],
        conversation: SMSConversation,
        current_message: str,
    ) -> tuple:
        """Generate an AI response while keeping MCP on one asyncio task."""
        return self._run_async(
            self._generate_ai_response_async(
                assistant, sms_config, conversation, current_message
            )
        )

    async def _generate_ai_response_async(
        self,
        assistant: Assistant,
        sms_config: Dict[str, Any],
        conversation: SMSConversation,
        current_message: str,
    ) -> tuple:
        """Generate an AI response using the assistant's config.

        Returns (response_text, tools_called_list)

        The entire MCP lifecycle stays in this coroutine. AnyIO-backed MCP
        transports require the task that enters their context managers to also
        execute and close them; separate ``asyncio.run`` calls violate that
        invariant even when they happen on the same thread.
        """
        system_prompt = self._build_system_prompt(assistant, sms_config)

        history = self._load_conversation_history(conversation, sms_config)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": current_message})

        tools_schema = self._build_tools_schema(assistant) or []

        # Open the assistant's MCP connection (if eligible) and merge its tool
        # schemas for this turn only (Task #459). Native platform tools win any
        # name collision, so MCP schemas are pre-filtered against native names.
        native_names = {s["function"]["name"] for s in tools_schema}
        mcp_schemas = await self._open_mcp_for_turn_async(assistant, native_names)
        tools_schema = tools_schema + mcp_schemas

        llm_model = sms_config.get("llm_model") or assistant.llm_model or "gpt-4o-mini"
        temperature = assistant.temperature or 0.7

        tools_called = []

        try:
            kwargs = {
                "model": llm_model,
                "messages": messages,
                "temperature": temperature,
            }
            if tools_schema:
                kwargs["tools"] = tools_schema

            response = _openai_client.chat.completions.create(**kwargs)
            choice = response.choices[0]

            max_tool_rounds = 5
            round_count = 0

            while choice.finish_reason == "tool_calls" and round_count < max_tool_rounds:
                round_count += 1
                tool_calls = choice.message.tool_calls

                messages.append(choice.message)

                for tc in tool_calls:
                    fn_name = tc.function.name
                    fn_args = json.loads(tc.function.arguments) if tc.function.arguments else {}

                    tools_called.append({"name": fn_name, "arguments": fn_args})

                    result = await self._execute_tool_async(
                        assistant, fn_name, fn_args
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result)
                            if isinstance(result, dict)
                            else str(result),
                        }
                    )

                response = _openai_client.chat.completions.create(**kwargs)
                choice = response.choices[0]

            ai_text = choice.message.content or ""

            if response.usage:
                logger.debug(
                    f"SMS LLM usage: {response.usage.prompt_tokens} prompt, "
                    f"{response.usage.completion_tokens} completion tokens"
                )

            return ai_text.strip(), tools_called if tools_called else None

        except Exception as e:
            logger.exception(f"Error generating SMS AI response: {e}")
            return None, None
        finally:
            # Close the per-turn MCP session regardless of success/failure so a
            # remote MCP server connection never leaks across SMS turns.
            await self._close_mcp_for_turn_async()

    def _build_system_prompt(self, assistant: Assistant, sms_config: Dict[str, Any]) -> str:
        base_prompt = assistant.system_prompt or "You are a helpful assistant."

        kb_content = ""
        if assistant.knowledge_base_id:
            try:
                kb_content = load_knowledge_for_prompt(str(assistant.knowledge_base_id))
            except Exception as e:
                logger.error(f"Failed to load KB for SMS assistant {assistant.id}: {e}")

        prompt_parts = [base_prompt]

        if kb_content:
            prompt_parts.append(
                f"\n## KNOWLEDGE BASE\n"
                f"Use this information to answer questions directly and confidently.\n\n"
                f"{kb_content}"
            )

        prompt_parts.append(SMS_BEHAVIOR_RULES)

        prompt_additions = sms_config.get("prompt_additions", "")
        if prompt_additions:
            prompt_parts.append(f"\n## ADDITIONAL SMS INSTRUCTIONS\n{prompt_additions}")

        # Inject escalation protocol last so it has maximum recency weight
        # with the LLM and cannot be overridden by earlier instructions.
        prompt_parts.append(HANDOFF_INSTRUCTION)

        return "\n".join(prompt_parts)

    def _load_conversation_history(
        self, conversation: SMSConversation, sms_config: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        max_messages = sms_config.get("max_history_messages", DEFAULT_MAX_HISTORY_MESSAGES)

        recent_messages = (
            self.db.query(SMSMessage)
            .filter(
                SMSMessage.conversation_id == conversation.id,
            )
            .order_by(SMSMessage.created_at.desc())
            .limit(max_messages)
            .all()
        )

        recent_messages.reverse()

        history = []
        for msg in recent_messages:
            if msg.sender == MessageSender.CUSTOMER.value:
                history.append({"role": "user", "content": msg.content})
            else:
                history.append({"role": "assistant", "content": msg.content})

        return history

    def _build_tools_schema(self, assistant: Assistant) -> Optional[List[Dict[str, Any]]]:
        if not assistant.tool_set_id:
            return None

        tools = (
            self.db.query(Tool)
            .filter(
                Tool.tool_set_id == assistant.tool_set_id,
                Tool.is_active == "true",
            )
            .all()
        )

        if not tools:
            return None

        schema = []
        seen_names: set = set()
        for tool in tools:
            fn_schema = None
            if tool.tool_type == ToolType.API_REQUEST.value:
                fn_schema = self._build_api_request_schema(tool)
            elif tool.tool_type == ToolType.CAPABILITY.value:
                fn_schema = self._build_capability_schema(tool)
            elif tool.tool_type == ToolType.DYNAMIC_OPERATION.value:
                fn_schema = self._build_dynamic_operation_schema(tool)
            if not fn_schema:
                continue
            # Skip duplicate function names — e.g. two CAPABILITY tools pointing
            # at the same capability collapse to one abstract function name.
            # Registering the same name twice corrupts the LLM tool list. Parity
            # with the voice mapper + simulator dedup.
            fn_name = fn_schema["function"]["name"]
            if fn_name in seen_names:
                continue
            seen_names.add(fn_name)
            schema.append(fn_schema)

        return schema if schema else None

    # ── MCP (Model Context Protocol) support — Task #459 ─────────────────────
    #
    # SMS mirrors the voice + simulator channels: an assistant may link one
    # account-owned MCP connection whose remote tools become available to the
    # LLM. Unlike voice (Pipecat, long-lived call session), SMS has no persistent
    # session, so the async MCPClient is opened at the start of a turn and closed
    # at the end of the same turn. Execution flows through the shared
    # botelier.services.mcp_client.MCPClient (SSE / streamable_http transports).

    def _run_async(self, coro):
        """Run an MCP coroutine to completion from this synchronous code path.

        ``process_incoming_sms`` runs synchronously, but the Twilio webhook that
        calls it is an ``async`` FastAPI handler. Calling ``asyncio.run`` while an
        event loop is already running on the current thread raises
        ``RuntimeError``. To stay safe in both cases we:

          * use ``asyncio.run`` when no loop is running on this thread, and
          * offload to a dedicated worker thread with its own fresh event loop
            when a loop *is* already running.

        This never calls ``asyncio.run`` on a thread with a live loop.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop on this thread → safe to own one.
            return asyncio.run(coro)

        # A loop is running on this thread; run the coroutine in a separate
        # thread that owns its own loop so we never touch the live loop.
        import concurrent.futures

        def _runner():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(coro)
            finally:
                try:
                    loop.close()
                finally:
                    asyncio.set_event_loop(None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_runner).result()

    def _load_mcp_connection(self, assistant: Assistant):
        """Resolve the assistant's MCP connection with full enforcement.

        Returns the ``MCPConnection`` ONLY when it is safe to use:
          * the assistant references a connection,
          * the connection belongs to the assistant's account (ownership),
          * the connection is active, and
          * the connection status is CONNECTED.

        Any failure returns ``None`` so the MCP tools simply never appear —
        fail-closed, identical to how disconnected DYNAMIC_OPERATION tools are
        skipped.
        """
        connection_id = getattr(assistant, "mcp_connection_id", None)
        if not connection_id:
            return None

        from botelier.models.mcp_connection import MCPConnection, MCPConnectionStatus

        conn = (
            self.db.query(MCPConnection)
            .filter(MCPConnection.id == connection_id)
            .first()
        )
        if not conn:
            return None

        # Ownership: the connection must belong to the assistant's account.
        if str(conn.account_id) != str(assistant.account_id):
            logger.warning(
                f"SMS MCP: connection {connection_id} not owned by account "
                f"{assistant.account_id} — refusing to use it"
            )
            return None

        if not conn.is_active:
            return None

        if conn.status != MCPConnectionStatus.CONNECTED:
            logger.info(
                f"SMS MCP: connection {conn.name} is {conn.status} — skipping MCP tools"
            )
            return None

        return conn

    def _build_mcp_schemas(
        self, conn, enabled_tools: List[str], native_names: set
    ) -> List[Dict[str, Any]]:
        """Build OpenAI tool schemas for the enabled + discovered MCP tools.

        Only tools in the assistant's ``mcp_enabled_tools`` list are exposed, and
        any tool whose name collides with a native platform tool is dropped so the
        native tool wins the collision. Tracks the surviving names in
        ``_mcp_tool_names`` for execution routing.
        """
        discovered = conn.get_discovered_tools() or []
        enabled_set = set(enabled_tools or [])

        schemas: List[Dict[str, Any]] = []
        self._mcp_tool_names = set()

        for tool in discovered:
            name = tool.get("name")
            if not name or name not in enabled_set:
                continue
            # Native platform tools win name collisions — skip the MCP tool.
            if name in native_names or name in self._mcp_tool_names:
                continue

            parameters = tool.get("parameters") or {
                "type": "object",
                "properties": {},
                "required": [],
            }
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.get("description") or f"Execute {name}",
                        "parameters": parameters,
                    },
                }
            )
            self._mcp_tool_names.add(name)

        return schemas

    def _open_mcp_for_turn(
        self, assistant: Assistant, native_names: set
    ) -> List[Dict[str, Any]]:
        """Synchronous compatibility wrapper for non-production callers/tests."""
        return self._run_async(
            self._open_mcp_for_turn_async(assistant, native_names)
        )

    async def _open_mcp_for_turn_async(
        self, assistant: Assistant, native_names: set
    ) -> List[Dict[str, Any]]:
        """Open the MCP client for this turn and return its merged tool schemas.

        Returns an empty list (and opens nothing) when the assistant has no
        eligible MCP connection or no enabled tools. Never raises — an MCP setup
        failure degrades gracefully to "no MCP tools this turn".
        """
        self._mcp_client = None
        self._mcp_tool_names = set()

        conn = self._load_mcp_connection(assistant)
        if conn is None:
            return []

        enabled_tools = assistant.mcp_enabled_tools or []
        if not enabled_tools:
            return []

        schemas = self._build_mcp_schemas(conn, enabled_tools, native_names)
        if not schemas:
            return []

        from botelier.services.mcp_client import MCPClient

        transport_type = conn.transport_type.value if conn.transport_type else "sse"
        # MCPClient supports SSE and streamable_http; anything else is unsupported.
        if transport_type not in ("sse", "streamable_http"):
            logger.info(
                f"SMS MCP: transport '{transport_type}' unsupported for SMS — "
                f"skipping MCP tools"
            )
            self._mcp_tool_names = set()
            return []

        auth_type = conn.auth_type.value if conn.auth_type else "none"
        credentials = conn.get_credentials()

        client = MCPClient(
            server_url=conn.server_url,
            auth_type=auth_type,
            credentials=credentials,
            connection_config=conn.get_connection_config(),
            transport_type=transport_type,
        )

        try:
            success, error = await client.connect()
            if not success:
                logger.warning(f"SMS MCP: failed to connect to {conn.name}: {error}")
                await client.disconnect()
                self._mcp_tool_names = set()
                return []
        except Exception as e:
            logger.warning(f"SMS MCP: error opening connection {conn.name}: {e}")
            self._mcp_tool_names = set()
            return []

        self._mcp_client = client
        logger.info(
            f"SMS MCP: opened {conn.name} with {len(schemas)} enabled tool(s): "
            f"{sorted(self._mcp_tool_names)}"
        )
        return schemas

    def _execute_mcp_tool(self, fn_name: str, fn_args: Dict[str, Any]) -> Any:
        """Synchronous compatibility wrapper for non-production callers/tests."""
        return self._run_async(self._execute_mcp_tool_async(fn_name, fn_args))

    async def _execute_mcp_tool_async(
        self, fn_name: str, fn_args: Dict[str, Any]
    ) -> Any:
        """Execute an MCP tool through the live per-turn MCP client."""
        if self._mcp_client is None:
            return {"error": f"MCP tool '{fn_name}' unavailable", "status": "failed"}
        try:
            return await self._mcp_client.execute_tool(fn_name, fn_args)
        except Exception as e:
            logger.error(f"SMS MCP tool '{fn_name}' execution failed: {e}")
            return {"error": "MCP tool execution failed", "status": "failed"}

    def _close_mcp_for_turn(self):
        """Synchronous compatibility wrapper for non-production callers/tests."""
        return self._run_async(self._close_mcp_for_turn_async())

    async def _close_mcp_for_turn_async(self):
        """Disconnect + clear the per-turn MCP client so it never leaks."""
        client = self._mcp_client
        self._mcp_client = None
        self._mcp_tool_names = set()
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception as e:
            logger.debug(f"SMS MCP disconnect (non-fatal): {e}")

    def _build_capability_schema(self, tool: Tool) -> Optional[Dict[str, Any]]:
        """Build the OpenAI tool schema for a universal capability (Task #329).

        The LLM sees the abstract capability name + vendor-neutral parameters
        from the registry — identical to the voice channel — never the vendor.
        """
        from botelier.services.capabilities import build_capability_schema, get_capability

        capability_name = (tool.config or {}).get("capability")
        spec = get_capability(capability_name)
        schema = build_capability_schema(capability_name) if spec else None
        if not spec or not schema:
            return None

        description = schema["description"]
        response_instructions = (tool.config or {}).get("response_instructions", "")
        if response_instructions:
            description = (
                f"{description}\n\nWhen you receive the result, follow these "
                f"instructions: {response_instructions}"
            )

        return {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": description,
                "parameters": schema["parameters"],
            },
        }

    def _build_api_request_schema(self, tool: Tool) -> Optional[Dict[str, Any]]:
        parameters = tool.config.get("parameters", {})
        response_instructions = tool.config.get("response_instructions", "")

        description = tool.description
        if response_instructions:
            description = f"{description}\n\nWhen you receive the result, follow these instructions: {response_instructions}"

        properties = {}
        required = []
        for param_name, param_config in parameters.items():
            properties[param_name] = {
                "type": param_config.get("type", "string"),
                "description": param_config.get("description", ""),
            }
            if param_config.get("required", False):
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def _execute_tool(self, assistant: Assistant, fn_name: str, fn_args: Dict[str, Any]) -> Any:
        # MCP tools (Task #459) are routed to the live MCP client for this turn.
        # `_mcp_tool_names` was pre-filtered against native platform tool names,
        # so any name found here is unambiguously MCP-owned — native tools win
        # collisions because colliding MCP schemas are never exposed.
        if fn_name in self._mcp_tool_names:
            return self._execute_mcp_tool(fn_name, fn_args)

        # API_REQUEST tools expose the operator-chosen tool.name as the function
        # name, so match by name first.
        tool = (
            self.db.query(Tool)
            .filter(
                Tool.tool_set_id == assistant.tool_set_id,
                Tool.name == fn_name,
                Tool.is_active == "true",
            )
            .first()
        )

        if tool and tool.tool_type == ToolType.API_REQUEST.value:
            return self._execute_api_request(assistant, tool, fn_args)

        if tool and tool.tool_type == ToolType.DYNAMIC_OPERATION.value:
            return self._execute_dynamic_operation(assistant, tool, fn_args)

        # Capability tools expose the abstract capability name (e.g.
        # "search_availability"), not tool.name — resolve by matching the
        # capability stored in config.
        capability_tools = (
            self.db.query(Tool)
            .filter(
                Tool.tool_set_id == assistant.tool_set_id,
                Tool.tool_type == ToolType.CAPABILITY.value,
                Tool.is_active == "true",
            )
            .all()
        )
        for cap_tool in capability_tools:
            if (cap_tool.config or {}).get("capability") == fn_name:
                return self._execute_capability(assistant, fn_name, fn_args)

        if not tool:
            return {"error": f"Tool '{fn_name}' not found", "status": "failed"}

        return {"error": f"Unsupported tool type: {tool.tool_type}", "status": "failed"}

    async def _execute_tool_async(
        self, assistant: Assistant, fn_name: str, fn_args: Dict[str, Any]
    ) -> Any:
        """Execute MCP asynchronously; preserve existing native sync execution."""
        if fn_name in self._mcp_tool_names:
            return await self._execute_mcp_tool_async(fn_name, fn_args)
        return self._execute_tool(assistant, fn_name, fn_args)

    def _execute_capability(
        self, assistant: Assistant, capability_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Resolve + execute a universal capability for the SMS channel (Task #329).

        Uses the same CapabilityResolver + property scope as voice, so behavior
        is identical across channels.
        """
        from botelier.services.capabilities import CapabilityResolver

        try:
            resolver = CapabilityResolver(
                self.db, str(assistant.account_id), self.session_property_id
            )
            return resolver.execute_sync(
                capability_name,
                channel="sms",
                arguments=arguments,
                contact_ref=self._current_conversation_id,
            )
        except Exception as e:
            logger.error(f"Capability tool error: {e}")
            return {"error": "Capability request failed", "status": "failed"}

    def _execute_api_request(self, assistant: Assistant, tool: Tool, arguments: Dict[str, Any]) -> Any:
        from botelier.services.action_executor import (
            ActionContext,
            ActionExecutionRequest,
            execute_action_sync,
        )

        try:
            result = execute_action_sync(
                self.db,
                ActionExecutionRequest(
                    context=ActionContext(
                        account_id=str(assistant.account_id),
                        channel="sms",
                        tool_id=tool.id,
                        property_id=self.session_property_id,
                    ),
                    variables=arguments,
                    legacy_config=tool.config or {},
                ),
            )
            if result.success:
                response_mapping = tool.config.get("response_mapping") or tool.config.get("responseMapping") or {}
                return result.extracted_variables if response_mapping else result.data
            return {
                "error": result.error_message or "API request failed",
                "status": "failed",
                "error_type": result.error_type.value,
                "status_code": result.status_code,
            }
        except Exception as e:
            logger.error(f"API request tool error: {e}")
            return {"error": "API request failed", "status": "failed"}

    def _build_dynamic_operation_schema(self, tool: Tool) -> Optional[Dict[str, Any]]:
        """Build the OpenAI tool schema for a DYNAMIC_OPERATION tool (Universal Adapter).

        The schema comes from the published IntegrationActionVersion's
        ``input_schema``, which contains only LLM-owned parameters — identical to
        the voice channel.  Returns None (skip) when the backing connection is not
        CONNECTED, so disconnected tools never appear in the LLM's tool list.
        """
        from botelier.models.integration import (
            AccountIntegration,
            IntegrationAction,
            IntegrationActionVersion,
            IntegrationStatus,
        )

        tool_config = tool.config or {}
        action_id = tool_config.get("integration_action_id")
        if not action_id:
            return None

        # Connection-scoped + property-scope filter: skip tool if backing integration
        # is not CONNECTED, or if it is property-bound to a different property than
        # this SMS session.  Account-global connections (property_id NULL) always pass.
        connection_id = tool_config.get("connection_id")
        if connection_id:
            conn = self.db.query(AccountIntegration).filter(
                AccountIntegration.id == connection_id
            ).first()
            if not conn or conn.status != IntegrationStatus.CONNECTED:
                return None
            if conn.property_id is not None:
                session_prop = self.session_property_id
                if session_prop is None or str(conn.property_id) != str(session_prop):
                    return None

        action = self.db.query(IntegrationAction).filter(IntegrationAction.id == action_id).first()
        if not action or not action.published_version_id:
            return None
        version = self.db.query(IntegrationActionVersion).filter(
            IntegrationActionVersion.id == action.published_version_id
        ).first()
        if not version:
            return None

        input_schema = version.input_schema or {"type": "object", "properties": {}, "required": []}
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or tool.name,
                "parameters": input_schema,
            },
        }

    def _execute_dynamic_operation(
        self, assistant: Assistant, tool: Tool, arguments: Dict[str, Any]
    ) -> Any:
        """Execute a DYNAMIC_OPERATION tool through the certified integration runtime (SMS channel)."""
        from botelier.models.integration import IntegrationAction, IntegrationActionVersion
        from botelier.services.action_executor import (
            ActionContext,
            ActionExecutionRequest,
            execute_action_sync,
        )
        from botelier.services.integration_client import IntegrationAPIConfig

        tool_config = tool.config or {}
        action_id = tool_config.get("integration_action_id")
        connection_id = tool_config.get("connection_id")

        if not action_id:
            return {"error": "DYNAMIC_OPERATION tool missing integration_action_id", "status": "failed"}

        action = self.db.query(IntegrationAction).filter(IntegrationAction.id == action_id).first()
        if not action or not action.published_version_id:
            return {"error": "Operation has no published version", "status": "failed"}

        version = self.db.query(IntegrationActionVersion).filter(
            IntegrationActionVersion.id == action.published_version_id
        ).first()
        if not version or not version.config:
            return {"error": "Operation version missing config", "status": "failed"}

        exec_config = version.config
        # Shared builder (same one test_operation and the other channels use) so
        # SMS executes the identical request shape, including any persisted
        # request_overrides.
        from botelier.services.operation_publisher import build_operation_api_config

        config = build_operation_api_config(
            exec_config,
            fallback_integration_id=connection_id or "",
            fallback_endpoint_id=tool_config.get("operation_id") or "",
        )

        try:
            result = execute_action_sync(
                self.db,
                ActionExecutionRequest(
                    context=ActionContext(
                        account_id=str(assistant.account_id),
                        channel="sms",
                        tool_id=tool.id,
                        property_id=self.session_property_id,
                    ),
                    variables=arguments,
                    integration_config=config,
                    response_policy=exec_config.get("response_policy"),
                ),
            )
            if result.success:
                if config.response_variables:
                    return result.extracted_variables or {}
                return result.data
            return {
                "error": result.error_message or "Dynamic operation failed",
                "status": "failed",
                "error_type": result.error_type.value if result.error_type else "unknown",
                "status_code": result.status_code,
            }
        except Exception as e:
            logger.error(f"DYNAMIC_OPERATION SMS tool error: {e}")
            return {"error": "Dynamic operation failed", "status": "failed"}

    def _apply_response_mapping(
        self, data: Any, response_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        result = {}
        for variable_name, json_path in response_mapping.items():
            try:
                value = data
                for key in json_path.strip("$.").split("."):
                    if isinstance(value, dict):
                        value = value.get(key)
                    elif isinstance(value, list) and key.isdigit():
                        value = value[int(key)]
                    else:
                        value = None
                        break
                result[variable_name] = value
            except (KeyError, IndexError, TypeError):
                result[variable_name] = None
        return result

    def _send_twilio_sms(
        self,
        from_number: str,
        to_number: str,
        body: str,
        account_id,
        media_urls: Optional[List[str]] = None,
    ) -> Optional[str]:
        try:
            from botelier.models.account import Account

            account = self.db.query(Account).filter(Account.id == account_id).first()
            if not account:
                logger.error(f"Account {account_id} not found for SMS sending")
                return None

            account_sid = account.twilio_sub_account_sid
            auth_token = account.twilio_sub_auth_token

            if not account_sid or not auth_token:
                account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
                auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

            if not account_sid or not auth_token:
                logger.error("No Twilio credentials available for SMS sending")
                return None

            client = TwilioClient(account_sid, auth_token)

            from botelier.config.domain import get_public_base_url

            status_callback = f"{get_public_base_url()}/api/sms/status"

            kwargs: Dict[str, Any] = {
                "body": body,
                "from_": from_number,
                "to": to_number,
                "status_callback": status_callback,
            }
            if media_urls:
                kwargs["media_url"] = media_urls

            message = client.messages.create(**kwargs)

            logger.info(f"Sent SMS via Twilio: {message.sid}")
            return message.sid

        except Exception as e:
            logger.exception(f"Failed to send SMS via Twilio: {e}")
            return None
