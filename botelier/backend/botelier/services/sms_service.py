"""
SMS Service - Handles AI-powered SMS conversations.

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

import os
import json
import re
import httpx
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID
from loguru import logger
from openai import OpenAI
from sqlalchemy.orm import Session
from twilio.rest import Client as TwilioClient

from botelier.database import SessionLocal
from botelier.models.assistant import Assistant
from botelier.models.phone_number import PhoneNumber
from botelier.models.knowledge_entry import KnowledgeEntry
from botelier.models.tool import Tool, ToolType
from botelier.models.tool_set import ToolSet
from botelier.models.sms_conversation import (
    SMSConversation, SMSMessage,
    ConversationStatus, MessageDirection, MessageSender, MessageStatus
)
from botelier.voice.knowledge_handler import load_knowledge_for_prompt


OPT_OUT_KEYWORDS = {"stop", "cancel", "unsubscribe", "end", "quit"}
OPT_IN_KEYWORDS = {"start", "yes", "unstop"}

DEFAULT_SESSION_TIMEOUT_HOURS = 24
DEFAULT_MAX_HISTORY_MESSAGES = 20
DEFAULT_MAX_RESPONSE_LENGTH = 480

SMS_BEHAVIOR_RULES = """
SMS BEHAVIOR RULES:
- Keep responses concise and under 300 characters when possible
- Do not use TTS-specific formatting (no currency speech conversion)
- Use natural texting tone (slightly less formal than phone)
- If the answer is lengthy, break into key bullet points
- Do not end every message with "How can I help you?"
- Never include emojis unless specifically instructed to
"""


class SMSService:
    """Handles SMS AI conversation processing."""

    def __init__(self, db: Session):
        self.db = db
        self.openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    def process_incoming_sms(
        self,
        from_number: str,
        to_number: str,
        body: str,
        twilio_sid: Optional[str] = None,
        media_urls: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Process an incoming SMS and generate an AI response.

        Returns the AI response text, or None if no response should be sent
        (e.g., opt-out confirmation).
        """
        phone_number = self.db.query(PhoneNumber).filter(
            PhoneNumber.phone_number == to_number,
            PhoneNumber.sms_enabled == True,
            PhoneNumber.is_active == True,
        ).first()

        if not phone_number:
            logger.warning(f"SMS received on number {to_number} but no SMS-enabled phone number found")
            return None

        sms_assistant_id = phone_number.sms_assistant_id or phone_number.assistant_id
        if not sms_assistant_id:
            logger.warning(f"No assistant assigned for SMS on {to_number}")
            return None

        assistant = self.db.query(Assistant).filter(
            Assistant.id == sms_assistant_id,
            Assistant.is_active == True,
        ).first()

        if not assistant:
            logger.warning(f"Assistant {sms_assistant_id} not found or inactive")
            return None

        sms_config = assistant.sms_config or {}
        if not sms_config.get("enabled", False):
            logger.info(f"SMS is disabled on assistant {assistant.id}")
            return None

        normalized_body = body.strip().lower()

        # TCPA: STOP must always work immediately regardless of conversation state.
        if normalized_body in OPT_OUT_KEYWORDS:
            return self._handle_opt_out(from_number, to_number, phone_number, twilio_sid)

        conversation = self._find_or_create_conversation(
            from_number, to_number, phone_number, assistant, sms_config
        )

        # Opt-in (YES/START/UNSTOP) only triggers re-subscription when the
        # conversation is actually opted-out. In an active conversation these
        # words are normal customer messages and should be handled by the AI.
        if conversation.status == ConversationStatus.OPTED_OUT.value:
            if normalized_body in OPT_IN_KEYWORDS:
                return self._handle_opt_in(from_number, to_number, phone_number, twilio_sid)
            logger.info(f"Ignoring SMS from opted-out number {from_number}")
            return None

        inbound_msg = SMSMessage(
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND.value,
            sender=MessageSender.CUSTOMER.value,
            content=body,
            media_urls=media_urls,
            session_boundary=getattr(self, '_is_new_session', False),
            twilio_sid=twilio_sid,
            status=MessageStatus.RECEIVED.value,
        )
        self.db.add(inbound_msg)
        conversation.message_count = (conversation.message_count or 0) + 1
        conversation.last_message_at = datetime.utcnow()
        self.db.flush()

        ai_response, tools_called = self._generate_ai_response(
            assistant, sms_config, conversation, body
        )

        if not ai_response:
            ai_response = "I'm sorry, I wasn't able to process your message. Please try again."

        max_length = sms_config.get("max_response_length", DEFAULT_MAX_RESPONSE_LENGTH)
        if max_length and len(ai_response) > max_length:
            ai_response = ai_response[:max_length - 3] + "..."

        twilio_sid_out = self._send_twilio_sms(
            to_number, from_number, ai_response, phone_number.hotel_id
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
            f"Conv: {conversation.id} | Tools: {tools_called or 'none'}"
        )

        return ai_response

    def _handle_opt_out(
        self, from_number: str, to_number: str,
        phone_number: PhoneNumber, twilio_sid: Optional[str]
    ) -> str:
        conversation = self.db.query(SMSConversation).filter(
            SMSConversation.customer_number == from_number,
            SMSConversation.botelier_number == to_number,
            SMSConversation.hotel_id == phone_number.hotel_id,
        ).order_by(SMSConversation.last_message_at.desc()).first()

        if conversation:
            conversation.status = ConversationStatus.OPTED_OUT.value
            conversation.closed_at = datetime.utcnow()
        else:
            conversation = SMSConversation(
                hotel_id=phone_number.hotel_id,
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
        self, from_number: str, to_number: str,
        phone_number: PhoneNumber, twilio_sid: Optional[str]
    ) -> str:
        conversation = self.db.query(SMSConversation).filter(
            SMSConversation.customer_number == from_number,
            SMSConversation.botelier_number == to_number,
            SMSConversation.hotel_id == phone_number.hotel_id,
            SMSConversation.status == ConversationStatus.OPTED_OUT.value,
        ).order_by(SMSConversation.last_message_at.desc()).first()

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
        """
        Find or create a unified conversation thread.

        All messages from the same customer to the same Botelier number
        are grouped into one thread. Session boundaries are tracked on
        individual messages rather than splitting into separate conversations.
        """
        conversation = self.db.query(SMSConversation).filter(
            SMSConversation.customer_number == from_number,
            SMSConversation.botelier_number == to_number,
            SMSConversation.hotel_id == phone_number.hotel_id,
            SMSConversation.status != ConversationStatus.OPTED_OUT.value,
        ).order_by(SMSConversation.last_message_at.desc()).first()

        if conversation:
            if conversation.status == ConversationStatus.CLOSED.value:
                conversation.status = ConversationStatus.ACTIVE.value
                conversation.closed_at = None
            conversation.assistant_id = assistant.id
            self._is_new_session = self._check_session_boundary(conversation, sms_config)
            return conversation

        conversation = SMSConversation(
            hotel_id=phone_number.hotel_id,
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
        session_timeout_hours = sms_config.get("session_timeout_hours", DEFAULT_SESSION_TIMEOUT_HOURS)
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
        """
        Generate an AI response using the assistant's config.

        Returns (response_text, tools_called_list)
        """
        system_prompt = self._build_system_prompt(assistant, sms_config)

        history = self._load_conversation_history(conversation, sms_config)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": current_message})

        tools_schema = self._build_tools_schema(assistant)

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

            response = self.openai_client.chat.completions.create(**kwargs)
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

                    result = self._execute_tool(assistant, fn_name, fn_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result) if isinstance(result, dict) else str(result),
                    })

                response = self.openai_client.chat.completions.create(**kwargs)
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

        return "\n".join(prompt_parts)

    def _load_conversation_history(
        self, conversation: SMSConversation, sms_config: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        max_messages = sms_config.get("max_history_messages", DEFAULT_MAX_HISTORY_MESSAGES)

        recent_messages = self.db.query(SMSMessage).filter(
            SMSMessage.conversation_id == conversation.id,
        ).order_by(SMSMessage.created_at.desc()).limit(max_messages).all()

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

        tools = self.db.query(Tool).filter(
            Tool.tool_set_id == assistant.tool_set_id,
            Tool.is_active == "true",
        ).all()

        if not tools:
            return None

        schema = []
        for tool in tools:
            if tool.tool_type == ToolType.API_REQUEST.value:
                fn_schema = self._build_api_request_schema(tool)
                if fn_schema:
                    schema.append(fn_schema)

        return schema if schema else None

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

    def _execute_tool(
        self, assistant: Assistant, fn_name: str, fn_args: Dict[str, Any]
    ) -> Any:
        tool = self.db.query(Tool).filter(
            Tool.tool_set_id == assistant.tool_set_id,
            Tool.name == fn_name,
            Tool.is_active == "true",
        ).first()

        if not tool:
            return {"error": f"Tool '{fn_name}' not found", "status": "failed"}

        if tool.tool_type == ToolType.API_REQUEST.value:
            return self._execute_api_request(tool, fn_args)

        return {"error": f"Unsupported tool type: {tool.tool_type}", "status": "failed"}

    def _execute_api_request(self, tool: Tool, arguments: Dict[str, Any]) -> Any:
        url = tool.config.get("url", "")
        method = tool.config.get("method", "GET")
        headers = tool.config.get("headers", {})
        body_template = tool.config.get("body_template")
        response_mapping = tool.config.get("response_mapping", {})
        request_timeout = tool.config.get("timeout", 30)

        def substitute(template: str, values: dict) -> str:
            def replacer(match):
                key = match.group(1).strip()
                return str(values.get(key, match.group(0)))
            result = re.sub(r'\{\{(\w+)\}\}', replacer, template)
            try:
                result = result.format(**values)
            except (KeyError, ValueError, IndexError):
                pass
            return result

        formatted_url = substitute(url, arguments)
        formatted_headers = {k: substitute(v, arguments) for k, v in headers.items()}

        request_body = None
        if body_template:
            try:
                formatted_str = substitute(body_template, arguments)
                request_body = json.loads(formatted_str)
            except (KeyError, json.JSONDecodeError):
                request_body = None

        try:
            with httpx.Client(timeout=request_timeout) as client:
                if method == "GET":
                    resp = client.get(formatted_url, headers=formatted_headers)
                elif method == "POST":
                    resp = client.post(formatted_url, headers=formatted_headers, json=request_body)
                elif method == "PUT":
                    resp = client.put(formatted_url, headers=formatted_headers, json=request_body)
                elif method == "PATCH":
                    resp = client.patch(formatted_url, headers=formatted_headers, json=request_body)
                elif method == "DELETE":
                    resp = client.delete(formatted_url, headers=formatted_headers)
                else:
                    return {"error": f"Unsupported HTTP method: {method}", "status": "failed"}

                resp.raise_for_status()
                data = resp.json()

                if response_mapping:
                    return self._apply_response_mapping(data, response_mapping)

                return data

        except httpx.TimeoutException:
            return {"error": "API request timed out", "status": "failed"}
        except httpx.HTTPError as e:
            return {"error": str(e), "status": "failed"}
        except Exception as e:
            logger.error(f"API request tool error: {e}")
            return {"error": "API request failed", "status": "failed"}

    def _apply_response_mapping(self, data: Any, response_mapping: Dict[str, str]) -> Dict[str, Any]:
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
        self, from_number: str, to_number: str, body: str, hotel_id,
        media_urls: Optional[List[str]] = None,
    ) -> Optional[str]:
        try:
            from botelier.models.hotel import Hotel
            hotel = self.db.query(Hotel).filter(Hotel.id == hotel_id).first()
            if not hotel:
                logger.error(f"Hotel {hotel_id} not found for SMS sending")
                return None

            account_sid = hotel.twilio_sub_account_sid
            auth_token = hotel.twilio_sub_auth_token

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
