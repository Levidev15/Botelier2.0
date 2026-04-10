"""
Function Mapper - Converts database tools to Pipecat function calls.

This module bridges the gap between hotel-configured tools in the database
and the actual Pipecat function calling system during voice conversations.
"""

import os
import httpx
from typing import Dict, Any, List, Callable, Optional, TYPE_CHECKING
from loguru import logger
from ..config.domain import get_public_base_url

if TYPE_CHECKING:
    from .call_handler import CallHandler
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.adapters.schemas.function_schema import FunctionSchema
from twilio.rest import Client as TwilioClient

from botelier.models.tool import Tool, ToolType
from botelier.flow_executor import FlowExecutor, parse_flow_config


class FunctionMapper:
    """
    Maps database tool configurations to executable Pipecat functions.
    
    Usage:
        # At voice agent initialization
        tools = db.query(Tool).filter(Tool.is_active == "true").all()
        mapper = FunctionMapper(
            call_sid="CA1234...",
            stream_sid="MZ1234...",
            from_number="+15551234567",
            to_number="+15559876543",
            twilio_account_sid="AC...",  # Hotel's sub-account
            twilio_auth_token="xxx",      # Hotel's sub-account token
        )
        
        # Register all tools with LLM
        for tool in tools:
            function_schema, handler = mapper.map_tool_to_function(tool)
            llm.register_function(function_schema['name'], handler)
    """
    
    def __init__(
        self,
        call_sid: str = None,
        stream_sid: str = None,
        from_number: str = None,
        to_number: str = None,
        twilio_account_sid: str = None,
        twilio_auth_token: str = None,
        call_handler: "CallHandler" = None,
        db_session = None,
        account_id: str = None,
    ):
        """
        Initialize function mapper with call context and Twilio credentials.
        
        Args:
            call_sid: Twilio call SID (required for call transfers)
            stream_sid: Twilio stream SID (for stopping the media stream)
            from_number: Original caller's phone number (for callerId on transfer)
            to_number: The hotel's phone number that was called
            twilio_account_sid: Hotel's Twilio sub-account SID
            twilio_auth_token: Hotel's Twilio sub-account auth token
            call_handler: Reference to CallHandler for transcript saving
            db_session: SQLAlchemy database session for integration API calls
            account_id: Account ID for multi-tenant integration access
        """
        self.call_sid = call_sid
        self.stream_sid = stream_sid
        self.from_number = from_number
        self.to_number = to_number
        self.call_handler = call_handler
        self.db_session = db_session
        self.account_id = account_id

        # Store flow executors by tool name for state persistence across turns
        self._flow_executors: Dict[str, FlowExecutor] = {}

        # Store non-flow tool schemas for inclusion in dynamic tool updates
        # These tools should always remain available even during flow execution
        self._non_flow_tool_schemas: List[Dict[str, Any]] = []

        # TTS completion watcher — set by CallHandler after pipeline creation.
        # Used by transfer handlers to await real TTS completion instead of a
        # fixed sleep, ensuring the pre-transfer message is never clipped.
        self._tts_completion_watcher = None

        # TTS service instance — set by CallHandler after pipeline creation.
        # Used by transfer handlers to check audio context state after interruptions
        # and create a fresh context when needed before pushing TTSSpeakFrame.
        self._tts_service = None

        # Stores the spoken pre-transfer message so _execute_transfer can append
        # it to the saved transcript.  TTSSpeakFrame bypasses the LLM context, so
        # the message would otherwise be invisible to the ACW LLM.
        self._pending_pre_transfer_message: Optional[str] = None

        # CallEventQueue — injected by CallHandler after pipeline initialization.
        # Used to log pipeline events non-blockingly.
        self._event_queue = None

        # Track whether user_first_speech has been logged yet
        self._first_speech_logged = False

        # Twilio client for call transfers - use hotel's sub-account credentials
        self.twilio_client = None
        self.twilio_account_sid = twilio_account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = twilio_auth_token or os.environ.get("TWILIO_AUTH_TOKEN")

        if self.twilio_account_sid and self.twilio_auth_token:
            self.twilio_client = TwilioClient(self.twilio_account_sid, self.twilio_auth_token)
            logger.info(f"✅ Twilio client initialized for call {call_sid} (Account: {self.twilio_account_sid[:10]}...)")
    
    
    def set_tts_completion_watcher(self, watcher) -> None:
        """
        Attach the TtsCompletionWatcher created by the voice pipeline.

        Called by CallHandler immediately after pipeline creation so that
        transfer handlers can use wait_for_bot_done() instead of fixed sleeps.

        Args:
            watcher: TtsCompletionWatcher instance from VoiceEngineFactory.create_pipeline()
        """
        self._tts_completion_watcher = watcher
        logger.debug(f"TtsCompletionWatcher linked to FunctionMapper for call {self.call_sid}")

    def set_tts_service(self, tts_service) -> None:
        """
        Attach the TTS service instance created by the voice pipeline.

        Called by CallHandler immediately after pipeline creation so that
        transfer handlers can check audio context state after interruptions and
        create a fresh context when needed before pushing a TTSSpeakFrame.

        Args:
            tts_service: TTSService instance from VoiceEngineFactory.create_pipeline()
        """
        self._tts_service = tts_service
        logger.debug(f"TTS service linked to FunctionMapper for call {self.call_sid}")

    def set_event_queue(self, event_queue) -> None:
        """
        Attach the CallEventQueue for this call.

        Called by CallHandler after pipeline creation so pipeline events
        (user_first_speech, transfer_initiated) can be logged non-blockingly.

        Args:
            event_queue: CallEventQueue instance
        """
        self._event_queue = event_queue
        logger.debug(f"CallEventQueue linked to FunctionMapper for call {self.call_sid}")

    def log_event(self, event_type: str, event_source: str = "pipecat", severity: str = "info", details: dict = None) -> None:
        """Log a pipeline event via the event queue (non-blocking)."""
        if self._event_queue is not None:
            self._event_queue.log(event_type, event_source=event_source, severity=severity, details=details)

    async def wait_for_bot_done(self, timeout: float = 15.0) -> None:
        """
        Wait until the bot has finished speaking.

        Legacy/fallback method — kept for edge cases.  Transfer handlers should
        use TtsCompletionWatcher.schedule_after_speech() instead so the Twilio
        REST call happens outside Pipecat's 10-second function-call timeout.

        This method is a pure waiter — it does NOT reset the watcher.
        Callers that push a new TTSSpeakFrame must call
        ``self._tts_completion_watcher.reset()`` *before* the push so the
        watcher captures the correct BotStoppedSpeakingFrame.  Callers that
        only want to ensure the bot is already idle should call this without
        resetting so that an already-set event returns immediately.

        Falls back to a short fixed delay when the watcher is unavailable.

        Args:
            timeout: Maximum seconds to wait (default 15).  Transfer proceeds
                     regardless once the timeout expires.
        """
        import asyncio

        if self._tts_completion_watcher is not None:
            logger.info(f"⏳ Awaiting TTS completion before transfer for call {self.call_sid}")
            completed = await self._tts_completion_watcher.wait_until_done(timeout=timeout)
            if completed:
                logger.info(f"✅ TTS completion confirmed for call {self.call_sid}")
            else:
                logger.warning(
                    f"⚠️ TTS completion timed out after {timeout}s for call {self.call_sid} "
                    "— proceeding with transfer anyway"
                )
        else:
            # Fallback: watcher not available (no tools registered for this call)
            logger.warning(
                f"No TtsCompletionWatcher available for call {self.call_sid} — "
                "using 3 s fallback delay before transfer"
            )
            await asyncio.sleep(3.0)

    def track_tool_usage(self, tool_name: str, is_flow: bool = False):
        """Record tool usage in call log."""
        if not self.call_sid:
            return
        try:
            from ..database import SessionLocal
            from ..services.call_logger import CallLogger
            
            db = SessionLocal()
            try:
                call_logger = CallLogger(db)
                call_logger.record_tool_usage(
                    call_sid=self.call_sid,
                    tool_name=tool_name,
                    is_flow=is_flow
                )
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to track tool usage: {e}")
    
    def register_non_flow_tool_schema(self, schema_dict: Dict[str, Any]):
        """
        Register a non-flow tool schema for inclusion in dynamic tool updates.
        
        These tools remain available during flow execution.
        """
        self._non_flow_tool_schemas.append(schema_dict)
    
    def update_llm_tools_for_flow(self, tool_name: str):
        """
        Update the LLM context tools to only expose the current/next slot function.
        
        This is called after each slot collection to enforce strict flow order.
        The LLM will only see the function for the current slot, preventing it
        from calling functions for slots that should be collected later.
        
        Non-flow tools (transfer, end call, etc.) and knowledge base remain available.
        """
        if not self.call_handler or not self.call_sid:
            logger.warning("Cannot update LLM tools: missing call_handler or call_sid")
            return
        
        llm_context = self.call_handler.call_contexts.get(self.call_sid)
        if not llm_context:
            logger.warning(f"Cannot update LLM tools: no context for call {self.call_sid}")
            return
        
        executor = self._flow_executors.get(tool_name)
        if not executor:
            logger.warning(f"Cannot update LLM tools: no executor for flow {tool_name}")
            return
        
        try:
            flow_schemas = executor.get_function_schemas()
            
            function_schema_objects = []
            
            # 1. Always include knowledge base
            knowledge_schema = FunctionSchema(
                name="query_hotel_knowledge",
                description="Query the hotel's knowledge base to answer guest questions about the hotel, amenities, policies, services, and local information.",
                properties={
                    "question": {
                        "type": "string",
                        "description": "The guest's question to look up in the knowledge base",
                    },
                },
                required=["question"],
            )
            function_schema_objects.append(knowledge_schema)
            
            # 2. Include non-flow tools (transfer, end call, etc.)
            for non_flow_schema in self._non_flow_tool_schemas:
                func_schema = FunctionSchema(
                    name=non_flow_schema["name"],
                    description=non_flow_schema.get("description", ""),
                    properties=non_flow_schema.get("parameters", {}).get("properties", {}),
                    required=non_flow_schema.get("parameters", {}).get("required", []),
                )
                function_schema_objects.append(func_schema)
            
            # 3. Include flow trigger function
            trigger_schema = FunctionSchema(
                name=f"start_{tool_name}",
                description=f"Start the {tool_name} conversation flow",
                properties={},
                required=[],
            )
            function_schema_objects.append(trigger_schema)
            
            # 4. Include current flow functions (only current slot due to get_function_schemas logic)
            for schema in flow_schemas:
                func_def = schema.get("function", schema)
                func_schema = FunctionSchema(
                    name=func_def["name"],
                    description=func_def.get("description", ""),
                    properties=func_def.get("parameters", {}).get("properties", {}),
                    required=func_def.get("parameters", {}).get("required", []),
                )
                function_schema_objects.append(func_schema)
            
            new_tools = ToolsSchema(standard_tools=function_schema_objects)
            llm_context.set_tools(new_tools)
            
            func_names = [f.name for f in function_schema_objects]
            logger.info(f"🔄 Updated LLM tools for flow {tool_name}: {func_names}")
            
        except Exception as e:
            logger.error(f"Failed to update LLM tools for flow {tool_name}: {e}")
    
    def map_tool_to_function(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """
        Convert a database tool to a Pipecat function schema and handler.
        
        Args:
            tool: Database tool model
            
        Returns:
            Tuple of (function_schema, handler_function)
            
        Example:
            schema, handler = mapper.map_tool_to_function(transfer_tool)
            # schema = {"name": "transfer_to_front_desk", "description": "...", "parameters": {...}}
            # handler = async function that actually performs the transfer
        """
        if tool.tool_type == ToolType.TRANSFER_CALL:
            return self._map_transfer_call(tool)
        elif tool.tool_type == ToolType.API_REQUEST:
            return self._map_api_request(tool)
        elif tool.tool_type == ToolType.END_CALL:
            return self._map_end_call(tool)
        elif tool.tool_type == ToolType.SEND_SMS:
            return self._map_send_sms(tool)
        elif tool.tool_type == ToolType.SEND_EMAIL:
            return self._map_send_email(tool)
        elif tool.tool_type == ToolType.FLOW:
            return self._map_flow(tool)
        else:
            raise ValueError(f"Unknown tool type: {tool.tool_type}")
    
    def _map_transfer_call(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """
        Map transfer call tool to Pipecat function.
        
        Function schema tells LLM:
        - When to call this function (description)
        - What parameters it needs (usually none for simple transfer)
        
        Handler function:
        - Says pre-transfer message
        - Transfers call to configured number
        - Ends bot's session
        """
        stored_phone = tool.config.get("phone_number") or ""
        country_code = tool.config.get("country_code") or ""
        raw_extension = tool.config.get("extension") or ""
        # Normalise extension to digits-only for safe TwiML/SIP interpolation.
        import re as _re_ext
        extension_digits = _re_ext.sub(r'[^\d]', '', raw_extension)
        extension = extension_digits if extension_digits else None
        # Configurable pause before DTMF extension digits. TwiML sendDigits uses
        # 'w' for a 0.5-second pause (NOT comma, which is silently ignored).
        extension_pause_seconds = float(tool.config.get("extension_pause_seconds") or 1.0)
        extension_pause_commas = "w" * max(1, round(extension_pause_seconds / 0.5))
        # Build E.164 dial target. New records store country_code + local digits
        # separately; legacy records stored the full E.164 in phone_number.
        if country_code and not stored_phone.startswith("+"):
            phone_number = f"{country_code}{stored_phone}"
        else:
            phone_number = stored_phone
        pre_message = tool.config.get("pre_transfer_message", "One moment please...")
        transfer_mode = tool.config.get("transfer_mode", "warm")
        
        # OpenAI function schema
        function_schema = {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {},  # No parameters needed for simple transfer
                "required": []
            }
        }
        
        # Handler function using Pipecat's FunctionCallParams pattern
        async def transfer_handler(params: FunctionCallParams):
            """
            Handler called when LLM decides to transfer call.

            Transfer Flow (decoupled from Pipecat function-call timeout):
                1. AI says pre-transfer message via Pipecat TTS (assistant's configured voice).
                2. Register _execute_transfer as a one-shot callback on TtsCompletionWatcher,
                   then return immediately to Pipecat — well within the 10s timeout.
                3. When BotStoppedSpeakingFrame arrives (speech done), the watcher fires
                   _execute_transfer as an asyncio task, outside Pipecat's timeout window.
                4. _execute_transfer: saves transcript, builds TwiML, calls Twilio REST API.
                5. Pipeline ends when Twilio closes the WebSocket after receiving the update.

            Fallback (no watcher): schedules _execute_transfer after a 3s fixed delay.
            """
            import re as _re
            import asyncio as _asyncio

            # Track tool usage
            self.track_tool_usage(tool.name)

            # Log transfer_initiated event (non-blocking)
            self.log_event(
                "transfer_initiated",
                event_source="app",
                severity="info",
                details={"tool": tool.name, "transfer_to": phone_number, "transfer_mode": transfer_mode},
            )

            async def _execute_transfer():
                """
                Performs the actual Twilio transfer — runs as an asyncio task after
                TTS finishes, completely outside Pipecat's function-call timeout.

                Pushes EndFrame only after a confirmed successful Twilio update
                (2xx response from calls().update()).  On 404 / any transfer error
                EndFrame is NOT pushed so the pipeline remains active — the AI can
                continue the conversation or Twilio's natural WebSocket close will
                end the pipeline when the call actually terminates.

                With auto_hang_up=False (TwilioFrameSerializer), EndFrame closes
                the WebSocket without issuing a Twilio REST hangup, so Twilio
                continues executing the TwiML it received (warm <Dial> or cold REFER).
                """
                _transfer_succeeded = False
                try:
                    if self.twilio_client and self.call_sid:
                        try:
                            from ..database import SessionLocal
                            from ..services.call_logger import CallLogger

                            db = SessionLocal()
                            try:
                                call_logger = CallLogger(db)

                                # Stop any active call recording before transferring.
                                # Uses _asyncio.to_thread so the blocking Twilio SDK call
                                # never stalls the event loop. Failures are warned only.
                                _rec_sid = (self.call_handler.call_recording_sids.get(self.call_sid)
                                            if self.call_handler else None)
                                if _rec_sid:
                                    try:
                                        await _asyncio.to_thread(
                                            lambda: self.twilio_client.calls(self.call_sid)
                                                        .recordings(_rec_sid)
                                                        .update(status="stopped")
                                        )
                                        logger.info(f"🛑 Recording {_rec_sid} stopped before transfer for call {self.call_sid}")
                                        self.call_handler.call_recording_sids.pop(self.call_sid, None)
                                    except Exception as _stop_err:
                                        logger.warning(f"Failed to stop recording before transfer for call {self.call_sid}: {_stop_err}")

                                # Save transcript BEFORE transfer (WebSocket closes after).
                                # Append the pre-transfer message that was spoken via TTSSpeakFrame
                                # (bypasses LLM context, so must be injected manually here).
                                if self.call_handler and hasattr(self.call_handler, '_save_call_transcript'):
                                    try:
                                        llm_context = self.call_handler.call_contexts.get(self.call_sid)
                                        extra = []
                                        if self._pending_pre_transfer_message:
                                            extra.append({
                                                "role": "assistant",
                                                "content": self._pending_pre_transfer_message,
                                                "interrupted": False
                                            })
                                            self._pending_pre_transfer_message = None
                                        await self.call_handler._save_call_transcript(
                                            self.call_sid, llm_context,
                                            extra_messages=extra if extra else None
                                        )
                                        logger.info(f"📝 Saved transcript before transfer for call {self.call_sid}")
                                    except Exception as e:
                                        logger.error(f"Error saving transcript before transfer: {e}")

                                # Build mode-specific TwiML.
                                # Cold REFER: <Stop><Stream> is intentionally omitted — Twilio closes
                                # the WebSocket naturally on REFER, so including it would cut off any
                                # audio still in flight before the transfer completes.
                                # Warm <Dial>: <Stop><Stream> is required so Twilio stops the media
                                # stream and bridges the caller to the new leg.
                                twiml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<Response>']

                                if transfer_mode == "cold":
                                    # Cold Transfer (SIP REFER)
                                    # Twilio sends a SIP REFER to the destination and exits the bridge.
                                    # Charges stop at this point. No /transfer-status callbacks will arrive.
                                    # SIP URI requires E.164 digits only (e.g. +14155551234).
                                    # Extension is appended to the user part with DTMF pauses (,,ext).
                                    digits_only = _re.sub(r'[^\d+]', '', phone_number)
                                    sip_user = f"{digits_only},,{extension}" if extension else digits_only
                                    sip_uri = f"sip:{sip_user}@pstn.twilio.com"
                                    twiml_parts.append(f'<Refer><Sip>{sip_uri}</Sip></Refer>')
                                    twiml_parts.append('</Response>')
                                    transfer_twiml = '\n'.join(twiml_parts)

                                    logger.info(f"🔄 Cold SIP REFER transfer for call {self.call_sid} to {phone_number} ({sip_uri})")
                                    logger.debug(f"Cold Transfer TwiML:\n{transfer_twiml}")

                                    def _do_cold_transfer():
                                        call_logger.record_transfer(
                                            call_sid=self.call_sid,
                                            transfer_to=phone_number,
                                            transfer_type="cold"
                                        )
                                        self.twilio_client.calls(self.call_sid).update(twiml=transfer_twiml)
                                    await _asyncio.to_thread(_do_cold_transfer)
                                    logger.info(f"✅ Cold SIP REFER transfer initiated for call {self.call_sid} to {phone_number}")
                                    _transfer_succeeded = True

                                    # Twilio does NOT call /connect-complete after a REST API <Refer> update,
                                    # so ACW must be triggered here directly. Transcript was saved above.
                                    try:
                                        from ..services.acw_service import run_acw_background as _run_acw_bg
                                        from ..models import Assistant as _Assistant
                                        _call_log = call_logger.get_call_log(self.call_sid)
                                        if _call_log and _call_log.assistant_id:
                                            _asst = db.query(_Assistant).filter(_Assistant.id == _call_log.assistant_id).first()
                                            if _asst and (_asst.acw_config or {}).get("auto_run"):
                                                import threading
                                                threading.Thread(target=_run_acw_bg, args=(_call_log.id,), daemon=True).start()
                                                logger.info(f"ACW background thread started for cold transfer call {self.call_sid}")
                                    except Exception as _acw_e:
                                        logger.error(f"Failed to start ACW thread after cold transfer: {_acw_e}")

                                else:
                                    # Warm Transfer (Twilio bridges both legs)
                                    # Twilio stays in the call and bridges the caller to the new number.
                                    # Status callbacks arrive at /transfer-status to track the second leg.
                                    # <Stop><Stream> is required here so Twilio closes the media stream
                                    # before bridging the caller to the new leg via <Dial>.
                                    if self.stream_sid:
                                        twiml_parts.append(f'<Stop><Stream name="{self.stream_sid}"/></Stop>')
                                    caller_id = self.to_number or os.environ.get("TWILIO_PHONE_NUMBER", "")
                                    if caller_id:
                                        twiml_parts.append(f'<Dial timeout="30" callerId="{caller_id}">')
                                    else:
                                        twiml_parts.append('<Dial timeout="30">')

                                    base_url = get_public_base_url()
                                    status_callback = f"{base_url}/api/calls/transfer-status"
                                    send_digits_attr = f' sendDigits="{extension_pause_commas}{extension}"' if extension else ""
                                    twiml_parts.append(
                                        f'<Number statusCallback="{status_callback}" '
                                        f'statusCallbackEvent="initiated ringing answered completed"'
                                        f'{send_digits_attr}>'
                                        f'{phone_number}</Number>'
                                    )

                                    twiml_parts.append('</Dial>')
                                    twiml_parts.append('</Response>')
                                    transfer_twiml = '\n'.join(twiml_parts)

                                    logger.info(f"🔄 Warm transfer for call {self.call_sid} to {phone_number}")
                                    logger.debug(f"Warm Transfer TwiML:\n{transfer_twiml}")

                                    def _do_warm_transfer():
                                        call_logger.record_transfer(
                                            call_sid=self.call_sid,
                                            transfer_to=phone_number,
                                            transfer_type="external"
                                        )
                                        self.twilio_client.calls(self.call_sid).update(twiml=transfer_twiml)
                                    await _asyncio.to_thread(_do_warm_transfer)
                                    logger.info(f"✅ Warm transfer initiated for call {self.call_sid} to {phone_number}")
                                    _transfer_succeeded = True

                            finally:
                                db.close()

                        except Exception as e:
                            logger.error(f"❌ Twilio transfer failed for call {self.call_sid}: {e}")
                    else:
                        missing = []
                        if not self.twilio_client:
                            missing.append("Twilio client")
                        if not self.call_sid:
                            missing.append("call_sid")
                        logger.warning(f"⚠️ Cannot transfer call: missing {', '.join(missing)}")
                finally:
                    # Gate EndFrame on a confirmed successful Twilio update.
                    #
                    # SUCCESS (2xx): the transfer TwiML was accepted — end our
                    # pipeline now.  With auto_hang_up=False the WebSocket closes
                    # without a REST hangup, so Twilio executes <Dial>/<Refer>
                    # independently.  The synchronous calls().update() call above
                    # guarantees TwiML is submitted BEFORE this EndFrame fires.
                    #
                    # FAILURE (404 / exception / missing credentials): do NOT push
                    # EndFrame — leave the pipeline running so the AI can continue
                    # the conversation.  If the call is truly gone (404), Twilio
                    # will close the WebSocket on its side and the transport will
                    # push EndFrame naturally.
                    if _transfer_succeeded:
                        await params.llm.push_frame(EndFrame())
                    else:
                        logger.warning(
                            f"Transfer did not succeed for {self.call_sid} — "
                            f"EndFrame not pushed; pipeline remains active"
                        )

            # Register _execute_transfer to fire after speech ends (outside Pipecat timeout).
            # Reset first so the watcher waits for the TTSSpeakFrame we're about to push.
            if self._tts_completion_watcher is not None:
                self._tts_completion_watcher.reset()
                self._tts_completion_watcher.schedule_after_speech(_execute_transfer)
                logger.info(f"📋 Transfer callback registered for call {self.call_sid} — will fire after TTS")
            else:
                # Fallback: no watcher available, use a fixed delay.
                async def _delayed_transfer():
                    await _asyncio.sleep(3.0)
                    await _execute_transfer()
                _asyncio.create_task(_delayed_transfer())
                logger.warning(f"No TtsCompletionWatcher for call {self.call_sid} — using 3s fallback delay for transfer")

            # Push the pre-transfer message.  The transfer fires via callback
            # once BotStoppedSpeakingFrame arrives; the callback then pushes
            # EndFrame to close the pipeline after the Twilio REST call.
            #
            # IMPORTANT: Do NOT call result_callback here.  Calling it causes
            # Pipecat to feed the function result back into the LLM, which starts
            # a new LLM generation cycle that cancels in-flight TTS.
            #
            # WHY THE SLEEP: When the LLM calls a function, Pipecat emits both
            # FunctionCallsStartedFrame and FunctionCallInProgressFrame downstream.
            # FunctionCallInProgressFrame cleans up the current TTS context ~67ms
            # after this handler runs.  Without the sleep, our TTSSpeakFrame opens
            # a new context immediately, which FunctionCallInProgressFrame then
            # wipes before Deepgram audio arrives (~125ms in prod).  Sleeping 250ms
            # (raised from 150ms) lets FunctionCallInProgressFrame fully clear the
            # stale context, so our TTSSpeakFrame opens a fresh context that lives
            # long enough to receive audio.  The watcher's 5s timeout is the safety
            # net if TTS still fails for any reason.
            #
            # Yielding control (asyncio.sleep(0)) ensures any pending async
            # callbacks from FunctionCallInProgressFrame have fully executed before
            # we check and restore TTS context state.
            # Record what will be spoken so _execute_transfer can append it to
            # the saved transcript (TTSSpeakFrame bypasses the LLM context).
            self._pending_pre_transfer_message = pre_message
            await _asyncio.sleep(0)
            await _asyncio.sleep(0.25)

            # If the TTS service supports audio contexts (AudioContextWordTTSService
            # subclass in production Pipecat), an interruption may have cleared the
            # active context leaving context_id as None.  Create a fresh named context
            # so the transfer phrase audio has somewhere valid to land, preventing
            # "unable to append audio to context: no context ID provided" frame drops.
            # Creating a context is lightweight (just registers a UUID → Queue entry)
            # and is only attempted when the service exposes this documented API.
            if self._tts_service is not None and hasattr(self._tts_service, "create_audio_context"):
                import uuid as _uuid
                _ctx_id = str(_uuid.uuid4())
                try:
                    await self._tts_service.create_audio_context(_ctx_id)
                    logger.debug(
                        f"Created fresh TTS audio context {_ctx_id} before transfer phrase "
                        f"for call {self.call_sid}"
                    )
                except Exception as _ctx_err:
                    logger.warning(
                        f"Failed to create TTS audio context before transfer phrase "
                        f"for call {self.call_sid}: {_ctx_err}"
                    )

            await params.llm.push_frame(TTSSpeakFrame(pre_message))
        
        return function_schema, transfer_handler
    
    def _extract_nested_value(self, data: Any, path: str) -> Any:
        """Extract a value from nested data using dot notation (e.g., 'data.guest.name'). Also supports JSONPath prefix ($.)."""
        if path.startswith("$."):
            path = path[2:]
        parts = path.replace("[", ".").replace("]", "").split(".")
        current = data
        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def _apply_response_mapping(self, data: Any, response_mapping: Dict[str, str]) -> Dict[str, Any]:
        """Apply response mapping to extract specific fields from API response."""
        result = {}
        for variable_name, json_path in response_mapping.items():
            value = self._extract_nested_value(data, json_path)
            result[variable_name] = value
        return result

    def _map_api_request(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """
        Map API request tool to Pipecat function.
        
        This allows AI to call external APIs during conversations.
        Parameters are extracted from the API config.
        Supports response mapping (extracting specific fields) and
        response instructions (telling the LLM how to present data).
        """
        url = tool.config.get("url")
        method = tool.config.get("method", "GET")
        headers = tool.config.get("headers", {})
        parameters = tool.config.get("parameters", {})
        body = tool.config.get("body")
        body_template = tool.config.get("body_template")
        response_mapping = tool.config.get("response_mapping", {})
        response_instructions = tool.config.get("response_instructions", "")
        request_timeout = tool.config.get("timeout", 30)
        
        # Build function schema with parameters from config
        description = tool.description
        if response_instructions:
            description = f"{tool.description}\n\nWhen you receive the result, follow these instructions: {response_instructions}"
        
        function_schema = {
            "name": tool.name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": parameters,
                "required": [k for k, v in parameters.items() if v.get("required", False)]
            }
        }
        
        mapper = self
        
        async def api_handler(params: FunctionCallParams):
            """
            Handler that makes HTTP request to external API.
            
            The LLM extracts parameter values from conversation and passes them here.
            """
            arguments = params.arguments
            
            import re as re_module
            import json as json_module
            
            def substitute_placeholders(template: str, values: dict) -> str:
                def replacer(match):
                    key = match.group(1).strip()
                    return str(values.get(key, match.group(0)))
                result = re_module.sub(r'\{\{(\w+)\}\}', replacer, template)
                try:
                    result = result.format(**values)
                except (KeyError, ValueError, IndexError):
                    pass
                return result
            
            formatted_url = substitute_placeholders(url, arguments)
            formatted_headers = {k: substitute_placeholders(v, arguments) for k, v in headers.items()}
            
            request_body = None
            if body_template:
                try:
                    formatted_body_str = substitute_placeholders(body_template, arguments)
                    request_body = json_module.loads(formatted_body_str)
                except (KeyError, json_module.JSONDecodeError):
                    request_body = body
            elif body:
                request_body = body
            
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                try:
                    if method == "GET":
                        response = await client.get(formatted_url, headers=formatted_headers)
                    elif method == "POST":
                        response = await client.post(formatted_url, headers=formatted_headers, json=request_body)
                    elif method == "PUT":
                        response = await client.put(formatted_url, headers=formatted_headers, json=request_body)
                    elif method == "PATCH":
                        response = await client.patch(formatted_url, headers=formatted_headers, json=request_body)
                    elif method == "DELETE":
                        response = await client.delete(formatted_url, headers=formatted_headers)
                    else:
                        await params.result_callback({
                            "error": f"Unsupported HTTP method: {method}",
                            "status": "failed"
                        })
                        return
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    if response_mapping:
                        shaped_data = mapper._apply_response_mapping(data, response_mapping)
                        await params.result_callback(shaped_data)
                    else:
                        await params.result_callback(data)
                    
                except httpx.TimeoutException:
                    await params.result_callback({
                        "error": "API request timed out",
                        "status": "failed"
                    })
                except httpx.HTTPError as e:
                    await params.result_callback({
                        "error": str(e),
                        "status": "failed"
                    })
        
        return function_schema, api_handler
    
    def _map_end_call(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map end call tool to Pipecat function."""
        goodbye_message = tool.config.get("goodbye_message", "Thank you for calling. Goodbye!")
        
        function_schema = {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
        
        async def end_call_handler(params: FunctionCallParams):
            """End the call gracefully."""
            # Track tool usage
            self.track_tool_usage(tool.name)
            
            # Say goodbye
            await params.llm.push_frame(
                TTSSpeakFrame(goodbye_message)
            )
            
            # End session
            await params.llm.push_frame(EndFrame())
            
            await params.result_callback({"status": "call_ended"})
        
        return function_schema, end_call_handler
    
    def _map_send_sms(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map send SMS tool to Pipecat function."""
        # Placeholder - implement when SMS integration is ready
        raise NotImplementedError("SMS sending not yet implemented")
    
    def _map_send_email(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map send email tool to Pipecat function."""
        # Placeholder - implement when email integration is ready
        raise NotImplementedError("Email sending not yet implemented")
    
    def _map_flow(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """
        Map a conversation flow tool to Pipecat function.
        
        Flows are visual conversation workflows with nodes for:
        - Collecting slot information (name, dates, phone, etc.)
        - Making API requests
        - Conditional branching
        - Transferring calls
        - Ending conversations
        
        The flow executor converts the visual flow into function schemas
        that the LLM can call to progress through the flow.
        """
        flow_config_dict = tool.config or {}
        
        # Parse the flow configuration
        if not flow_config_dict.get("nodes"):
            logger.warning(f"Flow tool {tool.name} has no nodes configured")
            # Return a placeholder schema
            return {
                "name": tool.name,
                "description": tool.description or "Execute conversation flow",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }, self._create_empty_flow_handler(tool.name)
        
        # Parse the flow config into typed objects
        flow_config = parse_flow_config(flow_config_dict)
        
        # Create flow executor with db context for integration API calls
        executor = FlowExecutor(
            flow_config,
            db_session=self.db_session,
            account_id=self.account_id
        )
        
        # Store executor for this flow (we might need to access collected data)
        if not hasattr(self, '_flow_executors'):
            self._flow_executors = {}
        self._flow_executors[tool.name] = executor
        
        # Return main flow trigger function
        # The LLM calls this when it detects the guest wants to start this flow
        function_schema = {
            "name": f"start_{tool.name}",
            "description": f"Start the {tool.name} flow. {tool.description or ''}",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
        
        async def flow_trigger_handler(params: FunctionCallParams):
            """Handler for starting the flow."""
            logger.info(f"🎬 Starting flow: {tool.name}")
            
            # Track flow usage
            self.track_tool_usage(tool.name, is_flow=True)
            
            # Get greeting from the flow
            greeting = executor.get_greeting()
            
            # Speak the greeting
            await params.llm.push_frame(TTSSpeakFrame(greeting))
            
            # Return flow info to LLM so it knows what to collect
            progress = executor.get_progress()
            
            await params.result_callback({
                "status": "flow_started",
                "message": greeting,
                "next_action": "collect_information",
                "progress": progress
            })
        
        return function_schema, flow_trigger_handler
    
    def _create_empty_flow_handler(self, flow_name: str):
        """Create a placeholder handler for empty flows."""
        async def empty_handler(params: FunctionCallParams):
            await params.result_callback({
                "status": "error",
                "message": f"Flow {flow_name} has no configured steps"
            })
        return empty_handler
    
    def get_flow_functions(self, tool: Tool) -> tuple[list[Dict[str, Any]], Dict[str, Callable]]:
        """
        Get all function schemas and handlers for a flow tool.
        
        A flow generates multiple functions:
        - One trigger function to start the flow
        - One function per variable to collect
        - API request functions
        - Transfer and end call functions
        
        The executor is stored and reused across calls to maintain state
        throughout the conversation.
        
        Returns:
            Tuple of (list of function schemas, dict of handlers)
        """
        flow_config_dict = tool.config or {}
        tool_name = str(tool.name)
        
        if not flow_config_dict.get("nodes"):
            # Empty flow - return just the trigger function
            schema, handler = self._map_flow(tool)
            return [schema], {schema["name"]: handler}
        
        # Check if we already have an executor for this flow (state persistence)
        if tool_name in self._flow_executors:
            executor = self._flow_executors[tool_name]
            logger.debug(f"Reusing existing FlowExecutor for {tool_name}")
        else:
            # Parse and create new executor with db context for integration API calls
            flow_config = parse_flow_config(dict(flow_config_dict))
            executor = FlowExecutor(
                flow_config,
                db_session=self.db_session,
                account_id=self.account_id
            )
            self._flow_executors[tool_name] = executor
            logger.info(f"Created new FlowExecutor for {tool_name}")
        
        # Get ALL function schemas for handler registration (so all handlers exist)
        all_function_schemas = executor.get_all_function_schemas()
        
        # Create handlers for ALL functions (handlers must exist for any function LLM might call)
        handlers = {}
        for schema in all_function_schemas:
            func_name = schema["function"]["name"]
            handlers[func_name] = self._create_flow_function_handler(tool_name, func_name)
        
        # Get current function schemas for initial tool exposure (only current slot)
        function_schemas = executor.get_function_schemas()
        
        # Add trigger function
        trigger_schema = {
            "type": "function",
            "function": {
                "name": f"start_{tool_name}",
                "description": f"Start the {tool_name} conversation flow when the guest wants to {tool.description or 'complete this task'}",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
        function_schemas.insert(0, trigger_schema)
        handlers[f"start_{tool_name}"] = self._create_flow_trigger_handler(tool_name)
        
        return function_schemas, handlers
    
    def _create_flow_function_handler(self, tool_name: str, function_name: str):
        """
        Create a handler for a specific flow function.
        
        Uses tool_name to look up the stored executor, ensuring state
        is preserved across multiple function calls during a conversation.
        """
        async def handler(params: FunctionCallParams):
            # Look up the stored executor for this flow
            executor = self._flow_executors.get(tool_name)
            if not executor:
                logger.error(f"No executor found for flow {tool_name}")
                await params.result_callback({
                    "status": "error",
                    "message": "Flow not initialized"
                })
                return
            
            # Execute the function and get result
            result = await executor.handle_function_call(function_name, dict(params.arguments))
            
            # Log collected data for debugging
            if result.get("collected"):
                logger.info(f"Flow {tool_name} collected: {result['collected']}")
                
                # CRITICAL: Update LLM tools to only expose the next slot's function
                # This enforces strict flow order by dynamically updating available tools
                self.update_llm_tools_for_flow(tool_name)
            
            # Handle special actions
            if result.get("action") == "transfer":
                target = result.get("target")
                flow_transfer_mode = result.get("transfer_mode", "warm")
                import asyncio as _asyncio_flow
                import re as _re_flow

                if self.twilio_client and self.call_sid and target:
                    async def _execute_flow_transfer():
                        """
                        Performs the Twilio REST call for a flow-triggered transfer.
                        Runs as an asyncio task after speech ends — outside Pipecat's
                        function-call timeout. Pushes EndFrame after initiating transfer.
                        """
                        try:
                            from ..database import SessionLocal
                            from ..services.call_logger import CallLogger as _CLFlow
                            _db_flow = SessionLocal()
                            try:
                                _cl_flow = _CLFlow(_db_flow)

                                # Save transcript BEFORE the Twilio REST call for both cold and
                                # warm transfers — the WebSocket closes immediately after the update
                                # and /connect-complete is never called for cold transfers.
                                if self.call_handler and hasattr(self.call_handler, '_save_call_transcript'):
                                    try:
                                        llm_context = self.call_handler.call_contexts.get(self.call_sid)
                                        await self.call_handler._save_call_transcript(self.call_sid, llm_context)
                                        logger.info(f"📝 Saved transcript before flow transfer for call {self.call_sid}")
                                    except Exception as _e:
                                        logger.error(f"Error saving transcript before flow transfer: {_e}")

                                # Stop any active call recording before transferring.
                                # Uses _asyncio_flow.to_thread so the blocking Twilio SDK
                                # call never stalls the event loop. Failures are warned only.
                                _flow_rec_sid = (self.call_handler.call_recording_sids.get(self.call_sid)
                                                 if self.call_handler else None)
                                if _flow_rec_sid:
                                    try:
                                        await _asyncio_flow.to_thread(
                                            lambda: self.twilio_client.calls(self.call_sid)
                                                        .recordings(_flow_rec_sid)
                                                        .update(status="stopped")
                                        )
                                        logger.info(f"🛑 Recording {_flow_rec_sid} stopped before flow transfer for call {self.call_sid}")
                                        self.call_handler.call_recording_sids.pop(self.call_sid, None)
                                    except Exception as _stop_err_flow:
                                        logger.warning(f"Failed to stop recording before flow transfer for call {self.call_sid}: {_stop_err_flow}")

                                # Build mode-specific TwiML.
                                # Cold REFER: omit <Stop><Stream> so Twilio lets audio drain naturally.
                                # Warm <Dial>: include <Stop><Stream> to close stream before bridging.
                                twiml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<Response>']

                                if flow_transfer_mode == "cold":
                                    digits_only = _re_flow.sub(r'[^\d+]', '', target)
                                    sip_uri = f"sip:{digits_only}@pstn.twilio.com"
                                    twiml_parts.append(f'<Refer><Sip>{sip_uri}</Sip></Refer>')
                                    twiml_parts.append('</Response>')
                                    _cl_flow.record_transfer(call_sid=self.call_sid, transfer_to=target, transfer_type="cold")
                                    logger.info(f"🔄 Cold SIP REFER flow transfer to {target}")
                                else:
                                    # Warm transfer: close the stream before bridging via <Dial>
                                    if self.stream_sid:
                                        twiml_parts.append(f'<Stop><Stream name="{self.stream_sid}"/></Stop>')
                                    caller_id = self.to_number or os.environ.get("TWILIO_PHONE_NUMBER", "")
                                    if caller_id:
                                        twiml_parts.append(f'<Dial timeout="30" callerId="{caller_id}">')
                                    else:
                                        twiml_parts.append('<Dial timeout="30">')
                                    base_url = get_public_base_url()
                                    status_callback = f"{base_url}/api/calls/transfer-status"
                                    twiml_parts.append(
                                        f'<Number statusCallback="{status_callback}" '
                                        f'statusCallbackEvent="initiated ringing answered completed">'
                                        f'{target}</Number>'
                                    )
                                    twiml_parts.append('</Dial>')
                                    twiml_parts.append('</Response>')
                                    _cl_flow.record_transfer(call_sid=self.call_sid, transfer_to=target, transfer_type="external")
                                    logger.info(f"🔄 Warm flow transfer to {target}")

                                self.twilio_client.calls(self.call_sid).update(twiml='\n'.join(twiml_parts))
                                logger.info(f"✅ Flow transfer to {target} initiated")

                                # Trigger ACW for cold flow transfers — Twilio won't call /connect-complete
                                if flow_transfer_mode == "cold":
                                    try:
                                        from ..services.acw_service import run_acw_background as _run_acw_bg2
                                        from ..models import Assistant as _Assistant2
                                        _flow_call_log = _cl_flow.get_call_log(self.call_sid)
                                        if _flow_call_log and _flow_call_log.assistant_id:
                                            _flow_asst = _db_flow.query(_Assistant2).filter(_Assistant2.id == _flow_call_log.assistant_id).first()
                                            if _flow_asst and (_flow_asst.acw_config or {}).get("auto_run"):
                                                import threading
                                                threading.Thread(target=_run_acw_bg2, args=(_flow_call_log.id,), daemon=True).start()
                                                logger.info(f"ACW background thread started for cold flow transfer call {self.call_sid}")
                                    except Exception as _acw_e2:
                                        logger.error(f"Failed to start ACW thread after cold flow transfer: {_acw_e2}")
                            finally:
                                _db_flow.close()
                        except Exception as e:
                            logger.error(f"Flow transfer failed: {e}")
                        finally:
                            # End the pipeline — runs regardless of transfer success/failure
                            await params.llm.push_frame(EndFrame())

                    # Schedule the transfer to fire after any in-flight speech ends.
                    # No reset() here — speech was initiated upstream, not by this handler.
                    # schedule_after_speech fires immediately if speech is already done.
                    if self._tts_completion_watcher is not None:
                        self._tts_completion_watcher.schedule_after_speech(_execute_flow_transfer)
                        logger.info(f"📋 Flow transfer callback registered for call {self.call_sid} — will fire after speech")
                    else:
                        async def _delayed_flow_transfer():
                            await _asyncio_flow.sleep(3.0)
                            await _execute_flow_transfer()
                        _asyncio_flow.create_task(_delayed_flow_transfer())
                        logger.warning(f"No TtsCompletionWatcher for call {self.call_sid} — using 3s fallback delay for flow transfer")
                else:
                    # No Twilio client / call_sid / target — end the pipeline immediately
                    await params.llm.push_frame(EndFrame())
                # Return immediately — do NOT call result_callback for transfer actions.
                # Calling it would trigger a new LLM generation cycle, which cancels
                # any in-flight TTS context before Deepgram audio arrives, preventing
                # BotStoppedSpeakingFrame from firing and killing the transfer callback.
                return

            elif result.get("action") == "end":
                end_msg = result.get("message", "Goodbye!")
                await params.llm.push_frame(TTSSpeakFrame(end_msg))
                await params.llm.push_frame(EndFrame())
                return

            # Add current progress to result for LLM context (non-terminal actions only)
            result["progress"] = executor.get_progress()

            await params.result_callback(result)
        
        return handler
    
    def _create_flow_trigger_handler(self, tool_name: str):
        """
        Create handler for starting a flow.
        
        Uses tool_name to look up the stored executor.
        """
        async def handler(params: FunctionCallParams):
            logger.info(f"🎬 Starting flow: {tool_name}")
            
            # Track flow usage in call logs
            self.track_tool_usage(tool_name, is_flow=True)
            
            # Look up the stored executor
            executor = self._flow_executors.get(tool_name)
            if not executor:
                logger.error(f"No executor found for flow {tool_name}")
                await params.result_callback({
                    "status": "error",
                    "message": "Flow not initialized"
                })
                return
            
            greeting = executor.get_greeting()
            progress = executor.get_progress()
            
            # Update LLM tools to only expose the first slot's function
            # This ensures strict flow order from the start
            self.update_llm_tools_for_flow(tool_name)
            
            # Get list of variables to collect for context
            variables_to_collect = [
                {"key": v.key, "type": v.type.value, "description": v.description}
                for v in executor.flow_config.variables
                if v.key not in executor.state.collected_slots
            ]
            
            await params.result_callback({
                "status": "flow_started",
                "greeting": greeting,
                "progress": progress,
                "variables_to_collect": variables_to_collect,
                "instructions": "Collect the required information by calling the collect_* functions as you gather data from the guest. Ask for each piece of information naturally in conversation."
            })
        
        return handler


# Helper function to load tools for a voice agent
def load_tools_for_assistant(assistant_id: str, db_session) -> List[tuple[Dict[str, Any], Callable]]:
    """
    Load all active tools for an assistant and convert to Pipecat functions.
    
    Usage:
        # In voice agent initialization
        from botelier.voice.function_mapper import load_tools_for_assistant
        
        tools = load_tools_for_assistant("assistant-123", db)
        mapper = FunctionMapper()
        
        for tool in tools:
            schema, handler = mapper.map_tool_to_function(tool)
            llm.register_function(schema['name'], handler)
    
    Args:
        assistant_id: Assistant ID to load tools for
        db_session: SQLAlchemy database session
        
    Returns:
        List of (function_schema, handler) tuples ready for LLM registration
    """
    from botelier.models.tool import Tool
    
    # Query active tools
    tools = db_session.query(Tool).filter(
        Tool.assistant_id == assistant_id,
        Tool.is_active == "true"
    ).all()
    
    # Convert to Pipecat functions
    mapper = FunctionMapper()
    return [mapper.map_tool_to_function(tool) for tool in tools]
