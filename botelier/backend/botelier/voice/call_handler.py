"""
Call Handler - Orchestrates Pipecat pipeline for incoming Twilio calls.

This module manages the lifecycle of voice call sessions, creating and running
Pipecat pipelines with TwilioFrameSerializer for real-time audio streaming.
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import WebSocket
from sqlalchemy.orm import Session
from loguru import logger

from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.runner import PipelineRunner

from .engine import VoiceEngineFactory
from .agent import VoiceAgentConfig
from .function_mapper import FunctionMapper
from ..models.assistant import Assistant
from ..models.phone_number import PhoneNumber
from ..database import SessionLocal
from ..services.call_logger import CallLogger
from ..services.call_event_queue import CallEventQueue

try:
    from pipecat.services.mcp_service import MCPClient as PipecatMCPClient
    from mcp.client.session_group import SseServerParameters
    PIPECAT_MCP_AVAILABLE = True
except ImportError:
    PIPECAT_MCP_AVAILABLE = False
    PipecatMCPClient = None
    SseServerParameters = None


class CallHandler:
    """
    Handles incoming Twilio call sessions.
    
    Orchestrates:
    - Database lookup: phone number → assistant
    - Pipecat pipeline creation with TwilioFrameSerializer
    - Real-time audio streaming via WebSocket
    - Call session lifecycle management
    - Function calling and knowledge base integration
    - Transcript capture on call end
    
    Call-scoped state:
    - active_calls: Tracks running call sessions
    - call_mappers: Stores FunctionMapper per call_sid for state persistence
    - call_contexts: Stores LLMContext per call_sid for transcript extraction
    - call_start_times: Tracks call start times for duration calculation
    - interrupted_responses: Tracks which assistant responses were interrupted
    """
    
    def __init__(self):
        """Initialize call handler."""
        self.active_calls = {}
        self.call_mappers: Dict[str, FunctionMapper] = {}
        self.call_contexts: Dict[str, Any] = {}
        self.call_start_times: Dict[str, datetime] = {}
        self.interrupted_responses: Dict[str, set] = {}  # call_sid -> set of interrupted message contents
        self.pending_responses: Dict[str, List[dict]] = {}  # call_sid -> list of {text, timestamp} per LLM turn (ALL turns, for timestamp lookup + incomplete recovery)
        self.user_turn_timestamps: Dict[str, List[dict]] = {}  # call_sid -> list of {text, timestamp} per user utterance
        self.call_mcp_clients: Dict[str, PipecatMCPClient] = {}  # call_sid -> Pipecat MCPClient for MCP tool execution
        self.call_event_queues: Dict[str, CallEventQueue] = {}  # call_sid -> CallEventQueue
        self.call_recording_sids: Dict[str, str] = {}  # call_sid -> Twilio RecordingSid
    
    async def handle_call(
        self,
        websocket: WebSocket,
        to_number: str,
        stream_sid: str,
        call_sid: str,
        db: Session,
        from_number: str = None,
    ):
        """
        Handle incoming call using Pipecat - Official Pattern.
        
        Args:
            websocket: FastAPI WebSocket (ALREADY ACCEPTED, 'start' event already read)
            to_number: Phone number being called (hotel's number)
            stream_sid: Twilio stream SID (from 'start' event)
            call_sid: Twilio call SID (from 'start' event)
            db: Database session
            from_number: Caller's phone number (for transfer callerId)
        
        Pattern (from Pipecat docs):
            1. WebSocket already accepted, 'start' event already consumed
            2. Look up assistant by phone number
            3. Create TwilioFrameSerializer with stream_sid/call_sid
            4. Create FastAPIWebsocketTransport with ALREADY-ACCEPTED websocket
            5. Build pipeline and run (Pipecat handles remaining messages)
        """
        try:
            logger.info(f"📞 Call {call_sid}: {to_number}")
            
            # 1. Look up which assistant is assigned to this phone number
            # Query database and close session immediately to avoid connection pool exhaustion
            hotel_twilio_sid = None
            hotel_twilio_token = None
            call_log_id = None
            call_started_at = None
            
            try:
                phone_record = db.query(PhoneNumber).filter(
                    PhoneNumber.phone_number == to_number
                ).first()
                
                if not phone_record or not phone_record.assistant_id:
                    logger.warning(f"⚠️ No assistant assigned to phone number: {to_number}")
                    db.close()
                    await websocket.close(code=1008, reason="No assistant assigned")
                    return
                
                # Fetch assistant configuration
                assistant = db.query(Assistant).filter(
                    Assistant.id == phone_record.assistant_id
                ).first()
                
                if not assistant:
                    logger.error(f"❌ Assistant not found: {phone_record.assistant_id}")
                    db.close()
                    return
                
                # Fetch call log for event queue and set answered_at.
                # answered_at is normally set by the Twilio in-progress status
                # callback, but that webhook is not reliably delivered in all
                # environments.  Setting it here (when audio streaming begins)
                # is the universal source of truth for when the call was answered.
                from ..models.call_log import CallLog
                call_log_record = db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
                if call_log_record:
                    call_log_id = call_log_record.id
                    call_started_at = call_log_record.started_at
                    if not call_log_record.answered_at:
                        call_log_record.answered_at = datetime.utcnow()
                        db.commit()
                
                logger.info(f"🤖 Assistant: '{assistant.name}' (ID: {assistant.id})")
                
                # Fetch account's Twilio sub-account credentials (for transfers)
                from ..models.account import Account as _CallAccount
                _call_acct = db.query(_CallAccount).filter(_CallAccount.id == assistant.account_id).first()
                if _call_acct:
                    hotel_twilio_sid = _call_acct.twilio_sub_account_sid
                    hotel_twilio_token = _call_acct.twilio_sub_auth_token
                    if hotel_twilio_sid:
                        logger.info(f"🏨 Using account sub-account: {hotel_twilio_sid[:10]}...")
                
                # Convert database model to VoiceAgentConfig
                config = self._create_agent_config(assistant)
                
                # Fetch tools for function calling (if enabled) before closing session
                tools = []
                if config.enable_function_calling and assistant.tool_set_id:
                    from ..models.tool import Tool
                    tools = db.query(Tool).filter(
                        Tool.tool_set_id == assistant.tool_set_id,
                        Tool.is_active == "true"
                    ).all()
                    logger.info(f"Loaded {len(tools)} tools from tool_set {assistant.tool_set_id}")
                elif config.enable_function_calling:
                    logger.info(f"No tool set assigned to assistant {assistant.id}")
                
                # Fetch MCP connection data if assistant has one configured
                mcp_connection_data = None
                mcp_enabled_tools = []
                logger.info(f"🔍 Checking MCP: assistant.mcp_connection_id = {assistant.mcp_connection_id}, PIPECAT_MCP_AVAILABLE = {PIPECAT_MCP_AVAILABLE}")
                if assistant.mcp_connection_id:
                    from ..models.mcp_connection import MCPConnection, MCPConnectionStatus
                    mcp_conn = db.query(MCPConnection).filter(
                        MCPConnection.id == assistant.mcp_connection_id,
                        MCPConnection.is_active == True
                    ).first()
                    if mcp_conn and mcp_conn.status == MCPConnectionStatus.CONNECTED:
                        credentials = None
                        if mcp_conn.credentials_encrypted:
                            try:
                                credentials = mcp_conn.get_credentials()
                            except Exception as cred_error:
                                logger.warning(f"Failed to decrypt MCP credentials (may be stale): {cred_error}")
                        
                        mcp_connection_data = {
                            "id": str(mcp_conn.id),
                            "server_url": mcp_conn.server_url,
                            "auth_type": mcp_conn.auth_type.value if mcp_conn.auth_type else "none",
                            "credentials": credentials,
                            "discovered_tools": mcp_conn.discovered_tools or [],
                        }
                        mcp_enabled_tools = assistant.mcp_enabled_tools or []
                        logger.info(f"Loaded MCP connection {mcp_conn.name} with {len(mcp_enabled_tools)} enabled tools")
                
                # Check call recording entitlement.
                call_recording_enabled = False
                if (assistant.call_settings or {}).get("call_recording_enabled"):
                    from ..models.account import Account
                    from ..auth.features import get_account_features
                    acct = db.query(Account).filter(Account.id == assistant.account_id).first()
                    if acct:
                        features = get_account_features(
                            subscription_tier=acct.subscription_tier.value,
                            feature_flags_override=acct.feature_flags or {},
                        )
                        call_recording_enabled = features.get("call_recording", False)
                    else:
                        logger.warning(f"Account not found for account_id {assistant.account_id} — recording skipped")

            finally:
                # CRITICAL: Close database session immediately after fetching data
                # WebSocket connections are long-lived - keeping sessions open exhausts the connection pool
                db.close()
            
            # 2. Get API keys
            api_keys = self._get_api_keys()
            
            # 3. Build function schemas and handlers (knowledge base ALWAYS available)
            # Note: MCP tools are registered separately after pipeline creation using Pipecat's MCPClient
            function_schemas, function_handlers = self._build_function_schemas_and_handlers(
                assistant=assistant,
                tools=tools,
                api_keys=api_keys,
                call_sid=call_sid,
                stream_sid=stream_sid,
                from_number=from_number,
                to_number=to_number,
                twilio_account_sid=hotel_twilio_sid,
                twilio_auth_token=hotel_twilio_token,
            )
            
            # 4. Create TwilioFrameSerializer (Pipecat pattern)
            serializer = TwilioFrameSerializer(
                stream_sid=stream_sid,
                call_sid=call_sid,
                account_sid=os.environ.get("TWILIO_ACCOUNT_SID"),
                auth_token=os.environ.get("TWILIO_AUTH_TOKEN"),
                params=TwilioFrameSerializer.InputParams(
                    auto_hang_up=True,  # Automatically hang up when pipeline ends
                )
            )
            
            # 5. Create WebSocket transport (WebSocket ALREADY ACCEPTED, 'start' ALREADY READ)
            transport = FastAPIWebsocketTransport(
                websocket=websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    add_wav_header=False,  # Twilio uses raw μ-law, not WAV
                    serializer=serializer,
                ),
            )
            
            # 6. Create Pipecat pipeline with function calling support
            # Create interruption callback to track interrupted responses
            def on_interruption(content: str):
                self.mark_response_interrupted(call_sid, content)

            # Create LLM response capture callback.
            # Called by LLMResponseCapture each time the LLM finishes generating a
            # complete response.  Stored in pending_responses so _extract_transcript
            # can (a) annotate committed assistant messages with their generation
            # timestamps, and (b) recover responses the LLM context never committed
            # (caller hung up mid-generation).
            self.pending_responses[call_sid] = []

            def on_llm_response(text: str, timestamp: datetime):
                start = self.call_start_times.get(call_sid)
                elapsed_s = (timestamp - start).total_seconds() if start else 0.0
                self.pending_responses[call_sid].append({
                    "text": text,
                    "elapsed_s": elapsed_s,
                })
                logger.debug(f"📝 Captured LLM response ({len(text)} chars) at T+{elapsed_s:.1f}s for call {call_sid}")

            # Create user turn capture callback.
            # Called by UserTurnCapture for each finalized user utterance, giving us
            # the elapsed time from call start when the STT finalized each turn.
            self.user_turn_timestamps[call_sid] = []

            def on_user_turn(text: str, timestamp: datetime):
                start = self.call_start_times.get(call_sid)
                elapsed_s = (timestamp - start).total_seconds() if start else 0.0
                self.user_turn_timestamps[call_sid].append({
                    "text": text,
                    "elapsed_s": elapsed_s,
                })
                logger.debug(f"🗣️  Captured user turn ({len(text)} chars) at T+{elapsed_s:.1f}s for call {call_sid}")
            
            pipeline, task, llm, context_aggregator, llm_context, tts_completion_watcher, first_speech_tracker, greeting_completion_tracker, idle_timeout_tracker = VoiceEngineFactory.create_pipeline(
                config=config,
                api_keys=api_keys,
                transport=transport,
                function_schemas=function_schemas if function_schemas else None,
                function_handlers=function_handlers if function_handlers else None,
                on_interruption=on_interruption,
                on_llm_response=on_llm_response,
                on_user_turn=on_user_turn,
            )

            # Link the TTS completion watcher to the FunctionMapper (if one was
            # created for this call) so transfer handlers can await actual TTS completion.
            if call_sid in self.call_mappers:
                self.call_mappers[call_sid].set_tts_completion_watcher(tts_completion_watcher)
            
            # 6.5 Register MCP tools if connection is configured (must happen AFTER pipeline creation)
            logger.info(f"🔍 MCP registration check: mcp_connection_data={mcp_connection_data is not None}, mcp_enabled_tools={mcp_enabled_tools}, PIPECAT_MCP_AVAILABLE={PIPECAT_MCP_AVAILABLE}")
            if mcp_connection_data and mcp_enabled_tools and PIPECAT_MCP_AVAILABLE:
                try:
                    # Build authentication headers based on auth_type
                    mcp_headers = self._build_mcp_headers(
                        auth_type=mcp_connection_data.get("auth_type", "none"),
                        credentials=mcp_connection_data.get("credentials"),
                    )
                    
                    # Create Pipecat MCP client with SSE parameters
                    sse_params = SseServerParameters(
                        url=mcp_connection_data["server_url"],
                        headers=mcp_headers if mcp_headers else None,
                        timeout=10.0,
                        sse_read_timeout=300.0,
                    )
                    
                    mcp_client = PipecatMCPClient(server_params=sse_params)
                    
                    # Get all available tools from MCP server
                    all_tools_schema = await mcp_client.get_tools_schema()
                    
                    # Filter to only enabled tools for this assistant
                    if all_tools_schema.standard_tools:
                        from pipecat.adapters.schemas.tools_schema import ToolsSchema
                        
                        filtered_tools = [
                            tool for tool in all_tools_schema.standard_tools
                            if tool.name in mcp_enabled_tools
                        ]
                        
                        if filtered_tools:
                            filtered_schema = ToolsSchema(standard_tools=filtered_tools)
                            await mcp_client.register_tools_schema(filtered_schema, llm)
                            logger.info(f"🔌 Registered {len(filtered_tools)} MCP tools with LLM for call {call_sid}: {[t.name for t in filtered_tools]}")
                        else:
                            logger.warning(f"No MCP tools matched enabled list: {mcp_enabled_tools}")
                    else:
                        logger.warning(f"MCP server returned no tools")
                    
                    # Store client for cleanup
                    self.call_mcp_clients[call_sid] = mcp_client
                    
                except Exception as e:
                    logger.error(f"Failed to register MCP tools: {e}")
            
            # 7. Update active call with task and context
            self.active_calls[call_sid] = task
            self.call_contexts[call_sid] = llm_context  # Store LLMContext directly for transcript extraction
            self.call_start_times[call_sid] = datetime.utcnow()
            self.interrupted_responses[call_sid] = set()  # Initialize interruption tracking

            # 7.5 Initialize and start the call event queue for pipeline events
            if call_log_id:
                event_queue = CallEventQueue(
                    call_log_id=call_log_id,
                    call_started_at=call_started_at or self.call_start_times[call_sid],
                )
                self.call_event_queues[call_sid] = event_queue
                await event_queue.start()

                # Log websocket_connected — stream established between Twilio and backend
                event_queue.log(
                    "websocket_connected",
                    event_source="pipecat",
                    severity="info",
                    details={"stream_sid": stream_sid},
                )

                # Write call_answered synchronously via a short-lived DB session.
                # A committed write is required here so that the Twilio in-progress
                # status callback (which may arrive milliseconds later) can use
                # _event_exists() to dedup and skip its own write.  The async event
                # queue drains with a ~0.5 s delay, which is not reliable enough for
                # that race window.  Opening a fresh session avoids re-using the
                # already-closed startup session.
                #
                # The existence check below mirrors the _event_exists() helper in
                # calls.py — it is intentionally inlined here to avoid importing a
                # private helper from an API module into the voice layer.
                from ..models.call_event import CallEvent as _CallEvent
                import uuid as _uuid
                _db_sync = SessionLocal()
                try:
                    _already = (
                        _db_sync.query(_CallEvent)
                        .filter(
                            _CallEvent.call_log_id == call_log_id,
                            _CallEvent.event_type == "call_answered",
                        )
                        .first()
                    )
                    if not _already:
                        _now = datetime.utcnow()
                        _started = call_started_at or self.call_start_times.get(call_sid)
                        _offset_ms = (
                            int((_now - _started).total_seconds() * 1000) if _started else None
                        )
                        _db_sync.add(
                            _CallEvent(
                                id=_uuid.uuid4(),
                                call_log_id=call_log_id,
                                event_type="call_answered",
                                event_source="pipecat",
                                severity="info",
                                occurred_at=_now,
                                offset_ms=_offset_ms,
                                details={"stream_sid": stream_sid},
                            )
                        )
                        _db_sync.commit()
                        logger.info("📞 call_answered event written synchronously (pipecat)")
                    else:
                        logger.debug("📞 call_answered already exists — skipping duplicate")
                except Exception as _e:
                    logger.error(f"❌ Failed to write call_answered event: {_e}")
                finally:
                    _db_sync.close()

                # Pass the queue reference to FunctionMapper so it can log pipeline events
                if call_sid in self.call_mappers:
                    self.call_mappers[call_sid].set_event_queue(event_queue)

                # Wire event_queue to the FirstUserSpeechTracker in the pipeline
                first_speech_tracker.set_event_queue(event_queue)
                # Wire event_queue to the GreetingCompletionTracker (first BotStoppedSpeakingFrame)
                greeting_completion_tracker.set_event_queue(event_queue)
                # Wire event_queue to the IdleTimeoutTracker (fires on caller silence)
                idle_timeout_tracker.set_event_queue(event_queue)

                # Wire a DB callback to GreetingCompletionTracker so ai_greeting_completed
                # is set as soon as the greeting TTS finishes — reliably from our side,
                # independent of Twilio status webhook timing.
                _greeting_call_sid = call_sid  # capture for closure
                async def _on_greeting_completed():
                    _gdb = SessionLocal()
                    try:
                        from ..services.call_logger import CallLogger as _CallLogger
                        _cl = _CallLogger(_gdb)
                        _cl.mark_greeting_completed(_greeting_call_sid)
                    except Exception as _ge:
                        logger.error(f"Failed to set ai_greeting_completed: {_ge}")
                    finally:
                        _gdb.close()
                greeting_completion_tracker.set_greeting_callback(_on_greeting_completed)

                # Wire WebSocket liveness check: if the caller hangs up during the
                # greeting, Pipecat continues draining buffered TTS frames and will
                # fire BotStoppedSpeakingFrame even after the WebSocket closes.
                # This guard ensures we do NOT mark the greeting as completed in
                # that case — the caller never heard those buffered frames.
                greeting_completion_tracker.set_call_active(
                    lambda: websocket.client_state.name == "CONNECTED"
                )

            # 8. Queue greeting message
            if call_sid in self.call_event_queues:
                self.call_event_queues[call_sid].log(
                    "greeting_started",
                    event_source="pipecat",
                    severity="info",
                )
            await task.queue_frames([TTSSpeakFrame(text=config.greeting_message)])
            
            logger.info(f"▶️ Pipeline starting: STT ({config.stt_provider}) → LLM ({config.llm_provider}) → TTS ({config.tts_provider})")

            # 8.5 Start Twilio call recording if enabled for this assistant/account.
            #
            # Why recording starts before runner.run():
            # recordings.create() is a Twilio REST API call that attaches a recording
            # to the live call object — it must be issued while the call is still active.
            # runner.run() blocks until the entire pipeline finishes (i.e. the call ends),
            # so recording MUST be started before run() or it would start after the call
            # has already ended. Recording begins capturing from the moment it is created
            # by Twilio, so starting just before run() means the full call audio is captured.
            #
            # Guards before starting:
            # (a) Duplicate-SID guard: skip if a recording is already active for this
            #     call_sid, preventing double-recording on unexpected reconnects.
            # (b) Transfer-state guard: skip if the CallLog already carries a terminal
            #     or transfer status, which would indicate this leg arrived as a
            #     transferred call where recording is undesirable.

            # Determine effective Twilio credentials for recording.
            # Prefer hotel-level sub-account creds; fall back to platform env vars so
            # that recording works even for accounts without a provisioned sub-account.
            _eff_twilio_sid = hotel_twilio_sid or os.environ.get("TWILIO_ACCOUNT_SID", "")
            _eff_twilio_token = hotel_twilio_token or os.environ.get("TWILIO_AUTH_TOKEN", "")

            if call_recording_enabled and _eff_twilio_sid and _eff_twilio_token:
                # (b) Check CallLog status in a fresh DB session.
                _transfer_statuses = {"transferred", "ended_early", "failed", "no_answer", "busy"}
                _skip_recording_for_status = False
                _db_rec_check = SessionLocal()
                try:
                    from ..models import CallLog as _CLCheck
                    _cl = _db_rec_check.query(_CLCheck).filter(
                        _CLCheck.call_sid == call_sid
                    ).first()
                    # Check both status AND has_transfer flag.
                    # has_transfer is normally set during the pipeline (after runner.run
                    # begins), so it will be False here for typical inbound calls.
                    # If a prior pathway already marked this call as transferred (e.g.
                    # via a race-condition re-entry), has_transfer provides an extra guard.
                    if _cl and (_cl.status in _transfer_statuses or _cl.has_transfer):
                        logger.info(
                            f"Skipping recording for {call_sid} — status='{_cl.status}' "
                            f"has_transfer={_cl.has_transfer}"
                        )
                        _skip_recording_for_status = True
                except Exception as _status_err:
                    logger.warning(f"Failed to check call status before recording: {_status_err}")
                finally:
                    _db_rec_check.close()

                if _skip_recording_for_status:
                    pass  # recording start skipped due to transfer/terminal state
                elif call_sid in self.call_recording_sids:
                    logger.warning(
                        f"Recording already active for {call_sid} "
                        f"(sid={self.call_recording_sids[call_sid]}) — skipping duplicate start"
                    )
                else:
                    try:
                        from twilio.rest import Client as _TwilioClient
                        from ..config.domain import get_public_base_url as _get_base_url
                        _rec_client = _TwilioClient(_eff_twilio_sid, _eff_twilio_token)
                        _base_url = _get_base_url()
                        _recording = _rec_client.calls(call_sid).recordings.create(
                            recording_channels="dual",
                            recording_status_callback=f"{_base_url}/api/calls/recording-status",
                            recording_status_callback_method="POST",
                        )
                        self.call_recording_sids[call_sid] = _recording.sid
                        logger.info(f"🎙️ Recording started for call {call_sid}: {_recording.sid}")
                    except Exception as _rec_err:
                        logger.error(f"Failed to start recording for call {call_sid}: {_rec_err}")

            # 9. Run pipeline (blocks until call ends)
            # Pipecat handles all remaining WebSocket messages (media, dtmf, stop)
            runner = PipelineRunner()
            await runner.run(task)
            
            logger.info(f"✅ Call {call_sid} ended")
            
            # 10. Capture transcript and save to call log
            await self._save_call_transcript(call_sid, llm_context)
            
        except Exception as e:
            logger.exception(f"Error handling call {call_sid}: {e}")
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()

            # Log pipeline_error event
            if call_sid in self.call_event_queues:
                self.call_event_queues[call_sid].log(
                    "pipeline_error",
                    event_source="app",
                    severity="error",
                    details={"error": str(e)},
                )
            
            # Still try to save transcript on error
            if call_sid in self.call_contexts:
                try:
                    await self._save_call_transcript(call_sid, self.call_contexts[call_sid])
                except Exception as save_error:
                    logger.error(f"Failed to save transcript on error: {save_error}")
        finally:
            # Cancel any pending post-speech transfer callback so a stale transfer
            # cannot fire after the call has already ended / pipeline has shut down.
            if call_sid in self.call_mappers:
                mapper = self.call_mappers[call_sid]
                watcher = getattr(mapper, "_tts_completion_watcher", None)
                if watcher is not None:
                    watcher.clear_callback()
                    logger.debug(f"Cleared pending TTS callback for call {call_sid}")
            # Flush and stop the event queue
            if call_sid in self.call_event_queues:
                try:
                    await self.call_event_queues[call_sid].flush_and_stop()
                except Exception as eq_err:
                    logger.warning(f"Error flushing event queue for call {call_sid}: {eq_err}")
                del self.call_event_queues[call_sid]
            # Cleanup call session state
            if call_sid in self.active_calls:
                del self.active_calls[call_sid]
            if call_sid in self.call_mappers:
                del self.call_mappers[call_sid]
                logger.debug(f"Cleaned up FunctionMapper for call {call_sid}")
            if call_sid in self.call_contexts:
                del self.call_contexts[call_sid]
            if call_sid in self.call_start_times:
                del self.call_start_times[call_sid]
            if call_sid in self.interrupted_responses:
                del self.interrupted_responses[call_sid]
            if call_sid in self.pending_responses:
                del self.pending_responses[call_sid]
            if call_sid in self.user_turn_timestamps:
                del self.user_turn_timestamps[call_sid]
            if call_sid in self.call_mcp_clients:
                del self.call_mcp_clients[call_sid]
                logger.debug(f"Cleaned up MCP client reference for call {call_sid}")
            if call_sid in self.call_recording_sids:
                del self.call_recording_sids[call_sid]
    
    def mark_response_interrupted(self, call_sid: str, content: str):
        """
        Mark an assistant response as interrupted.
        
        Called when the user interrupts the AI mid-response.
        
        Args:
            call_sid: Twilio call SID
            content: The content that was being spoken when interrupted
        """
        if call_sid not in self.interrupted_responses:
            self.interrupted_responses[call_sid] = set()
        
        if content and content.strip():
            # Store first 100 chars as key (enough to match uniquely)
            key = content.strip()[:100]
            self.interrupted_responses[call_sid].add(key)
            logger.debug(f"🛑 Marked interrupted: {key[:50]}...")
    
    def _create_agent_config(self, assistant: Assistant) -> VoiceAgentConfig:
        """
        Convert database Assistant model to VoiceAgentConfig.
        
        Injects knowledge base content directly into the system prompt for:
        - Immediate access without tool-call latency
        - Prompt caching on subsequent turns
        - Better answer quality (LLM has full context)
        
        Args:
            assistant: Database assistant model
            
        Returns:
            VoiceAgentConfig for pipeline creation
        """
        from botelier.voice.agent import AgentStatus
        from botelier.voice.knowledge_handler import load_knowledge_for_prompt
        
        status = AgentStatus.ACTIVE if assistant.is_active else AgentStatus.PAUSED
        
        base_prompt = assistant.system_prompt or "You are a friendly hotel assistant."
        
        kb_content = ""
        if assistant.knowledge_base_id:
            try:
                kb_content = load_knowledge_for_prompt(str(assistant.knowledge_base_id))
            except Exception as e:
                logger.error(f"Failed to load KB for assistant {assistant.id}: {e}")
                kb_content = ""
        else:
            logger.info(f"No knowledge base assigned to assistant {assistant.id}")
        
        if kb_content:
            enhanced_prompt = f"""{base_prompt}

## KNOWLEDGE BASE
You have access to the following Q&A knowledge base. Use this information to answer guest questions directly and confidently. Do NOT transfer the call or say you don't have information if the answer is in this knowledge base.

{kb_content}

## RESPONSE GUIDELINES
- Answer questions from the knowledge base naturally and conversationally
- Keep responses concise (under 50 words) since this is a phone call
- Only transfer to a human if: (1) the caller explicitly requests to speak with someone, OR (2) the question requires information NOT in the knowledge base AND the caller needs urgent assistance
- For general questions covered by the knowledge base, answer directly without offering to transfer"""
            logger.info(f"📚 Injected KB ({len(kb_content)} chars) into system prompt for assistant {assistant.id}")
        else:
            enhanced_prompt = base_prompt
            logger.info(f"📚 No KB content found for assistant {assistant.id}")
        
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
            llm_temperature=assistant.temperature or 0.7,
            llm_max_tokens=assistant.max_tokens or 150,
            llm_config=assistant.llm_config or {},
            tts_provider=assistant.tts_provider,
            tts_voice_id=assistant.tts_voice or "",
            tts_model=assistant.tts_model,
            tts_speed=1.0,
            tts_config=assistant.tts_config or {},
            system_prompt=enhanced_prompt,
            greeting_message=assistant.first_message or "Hello! How can I help you today?",
            enable_function_calling=True,
            enable_interruptions=True,
            enable_vad=assistant.vad_enabled,
            vad_provider=assistant.vad_provider,
            vad_config=assistant.vad_config or {},
        )
    
    def _get_api_keys(self) -> Dict[str, str]:
        """
        Get API keys from environment variables.
        
        Returns:
            Dictionary of provider API keys
        """
        return {
            "deepgram_api_key": os.environ.get("DEEPGRAM_API_KEY"),
            "openai_api_key": os.environ.get("OPENAI_API_KEY"),
            "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY"),
            "cartesia_api_key": os.environ.get("CARTESIA_API_KEY"),
            "elevenlabs_api_key": os.environ.get("ELEVENLABS_API_KEY"),
            "google_api_key": os.environ.get("GOOGLE_API_KEY"),
        }
    
    def _build_mcp_headers(
        self,
        auth_type: str,
        credentials: Optional[Dict[str, str]],
    ) -> Optional[Dict[str, str]]:
        """
        Build authentication headers for MCP server connection.
        
        Args:
            auth_type: Authentication type (none, api_key, bearer, basic)
            credentials: Authentication credentials dictionary
            
        Returns:
            Dictionary of headers, or None if no auth needed
        """
        if not auth_type or auth_type == "none" or not credentials:
            return None
        
        headers = {}
        
        if auth_type == "api_key":
            api_key = credentials.get("api_key", "")
            header_name = credentials.get("header_name", "X-API-Key")
            headers[header_name] = api_key
        
        elif auth_type == "bearer":
            token = credentials.get("token", "")
            headers["Authorization"] = f"Bearer {token}"
        
        elif auth_type == "basic":
            import base64
            username = credentials.get("username", "")
            password = credentials.get("password", "")
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        
        return headers if headers else None
    
    def _build_function_schemas_and_handlers(
        self,
        assistant: Assistant,
        tools: list,
        api_keys: Dict[str, str],
        call_sid: str,
        stream_sid: str = None,
        from_number: str = None,
        to_number: str = None,
        twilio_account_sid: str = None,
        twilio_auth_token: str = None,
    ) -> tuple[list, Dict[str, Any]]:
        """
        Build FunctionSchema objects and handlers for platform tools.
        
        This follows Pipecat's proper pattern of creating schemas before pipeline initialization.
        Note: MCP tools are registered separately after pipeline creation using Pipecat's MCPClient.
        
        Args:
            assistant: Database assistant model
            tools: List of Tool models (already fetched from database)
            api_keys: API keys for external services
            call_sid: Twilio call SID (for call transfers)
            stream_sid: Twilio stream SID (for stopping media stream on transfer)
            from_number: Caller's phone number
            to_number: Hotel's phone number that was called
            twilio_account_sid: Hotel's Twilio sub-account SID
            twilio_auth_token: Hotel's Twilio sub-account auth token
            
        Returns:
            Tuple of (function_schemas, function_handlers)
        """
        from pipecat.adapters.schemas.function_schema import FunctionSchema
        
        function_schemas = []
        function_handlers = {}
        
        # NOTE: Knowledge base is now injected directly into the system prompt
        # in _create_agent_config() for faster response times and prompt caching.
        # The query_hotel_knowledge tool is no longer registered here.
        
        # Add database tools
        if tools:
            # Get or create FunctionMapper for this call session
            # This ensures FlowExecutor state persists across function calls
            if call_sid in self.call_mappers:
                mapper = self.call_mappers[call_sid]
                logger.debug(f"Reusing FunctionMapper for call {call_sid}")
            else:
                mapper = FunctionMapper(
                    call_sid=call_sid,
                    stream_sid=stream_sid,
                    from_number=from_number,
                    to_number=to_number,
                    twilio_account_sid=twilio_account_sid,
                    twilio_auth_token=twilio_auth_token,
                    call_handler=self,
                    account_id=str(assistant.account_id),
                )
                self.call_mappers[call_sid] = mapper
                logger.info(f"Created FunctionMapper for call {call_sid}")
            
            for tool in tools:
                try:
                    # Check if this is a FLOW type tool - requires special handling
                    if tool.tool_type.value == "FLOW":
                        # Flow tools generate multiple function schemas (one per slot + API calls + etc.)
                        flow_schemas, flow_handlers = mapper.get_flow_functions(tool)
                        
                        for schema in flow_schemas:
                            # Convert OpenAI format to FunctionSchema
                            func_def = schema.get("function", schema)
                            tool_schema = FunctionSchema(
                                name=func_def["name"],
                                description=func_def.get("description", ""),
                                properties=func_def.get("parameters", {}).get("properties", {}),
                                required=func_def.get("parameters", {}).get("required", []),
                            )
                            function_schemas.append(tool_schema)
                        
                        function_handlers.update(flow_handlers)
                        logger.info(f"✅ Built {len(flow_schemas)} function schemas for flow: {tool.name}")
                    else:
                        # Regular tool - single function
                        function_schema_dict, handler = mapper.map_tool_to_function(tool)
                        
                        # Register non-flow tool schema for dynamic tool updates
                        # These tools remain available during flow execution
                        mapper.register_non_flow_tool_schema(function_schema_dict)
                        
                        # Convert dict to FunctionSchema
                        tool_schema = FunctionSchema(
                            name=function_schema_dict["name"],
                            description=function_schema_dict["description"],
                            properties=function_schema_dict.get("parameters", {}).get("properties", {}),
                            required=function_schema_dict.get("parameters", {}).get("required", []),
                        )
                        function_schemas.append(tool_schema)
                        function_handlers[function_schema_dict["name"]] = handler
                        
                        logger.info(f"✅ Built function schema for tool: {tool.name}")
                except Exception as e:
                    logger.error(f"Failed to build schema for tool {tool.name}: {e}")
        
        # Note: MCP tools are registered separately after pipeline creation using Pipecat's MCPClient.register_tools()
        logger.info(f"📋 Built {len(function_schemas)} platform function schemas")
        
        return function_schemas, function_handlers
    
    async def hangup_call(self, call_sid: str):
        """
        Terminate an active call.
        
        Args:
            call_sid: Twilio Call SID to terminate
        """
        if call_sid in self.active_calls:
            task = self.active_calls[call_sid]
            task.cancel()
            logger.info(f"Terminated call {call_sid}")
        else:
            logger.warning(f"Call {call_sid} not found in active calls")
    
    async def save_transcript_for_call(self, call_sid: str) -> bool:
        """
        Save transcript for a call from external context (e.g., connect-complete webhook).
        
        This is called when Twilio confirms the call has ended, allowing transcript
        capture even if the pipeline didn't exit cleanly.
        
        Args:
            call_sid: Twilio Call SID
            
        Returns:
            True if transcript was saved, False otherwise
        """
        if call_sid not in self.call_contexts:
            logger.debug(f"No context stored for call {call_sid}, transcript may have already been saved")
            return False
        
        try:
            llm_context = self.call_contexts[call_sid]
            await self._save_call_transcript(call_sid, llm_context)
            return True
        except Exception as e:
            logger.exception(f"Error saving transcript for call {call_sid}: {e}")
            return False
    
    async def _save_call_transcript(self, call_sid: str, llm_context: Optional[Any], extra_messages: Optional[list] = None):
        """
        Save call transcript to database.
        
        Uses tracked transcript (actual spoken content) if available,
        falls back to extracting from LLM context.
        
        Args:
            call_sid: Twilio call SID
            llm_context: Pipecat's LLMContext object with conversation history (may be None)
            extra_messages: Optional list of additional transcript entries to append after
                extraction (e.g. the spoken pre-transfer message that bypasses LLM context).
        """
        db = None
        try:
            if llm_context:
                transcript, tools_used = self._extract_transcript(call_sid, llm_context)
                if extra_messages:
                    transcript.extend(extra_messages)
                logger.info(f"Extracted transcript ({len(transcript)} messages) for call {call_sid}")
                if tools_used:
                    logger.info(f"🔧 Tools used during call {call_sid}: {tools_used}")
            else:
                transcript = []
                tools_used = []
                logger.warning(f"No LLM context available for call {call_sid}")
            
            if not transcript and not tools_used:
                logger.warning(f"No transcript messages or tools found for call {call_sid}")
                return
            
            duration_seconds = None
            if call_sid in self.call_start_times:
                start_time = self.call_start_times[call_sid]
                duration_seconds = max(0, int((datetime.utcnow() - start_time).total_seconds()))
            
            db = SessionLocal()
            call_logger = CallLogger(db)
            success = call_logger.complete_call(
                call_sid=call_sid,
                transcript=transcript if transcript else None,
                duration_seconds=duration_seconds,
                tools_used=tools_used
            )
            if success:
                logger.info(f"📝 Saved transcript ({len(transcript)} messages) for call {call_sid}")
            else:
                logger.warning(f"Failed to save transcript for call {call_sid}")
                
        except Exception as e:
            logger.exception(f"Error saving transcript for call {call_sid}: {e}")
        finally:
            if db:
                db.close()
    
    def _extract_transcript(self, call_sid: str, llm_context: Any) -> tuple:
        """
        Extract conversation messages and tool names from Pipecat's LLMContext.
        
        Filters to only user and assistant messages, excluding system prompts
        and tool/function call messages. Marks interrupted responses.
        Also collects unique tool names that were called during the conversation.
        
        Args:
            call_sid: Twilio call SID (for checking interrupted responses)
            llm_context: Pipecat's LLMContext object (passed directly from create_pipeline)
            
        Returns:
            Tuple of (transcript, tools_used) where:
                - transcript: List of transcript entries with role, content, and interrupted flag
                - tools_used: List of unique tool names called during the conversation
        """
        transcript = []
        tools_used_set = set()
        interrupted_set = self.interrupted_responses.get(call_sid, set())
        
        try:
            messages = None
            
            if hasattr(llm_context, 'get_messages'):
                messages = llm_context.get_messages()
                logger.debug(f"Got {len(messages) if messages else 0} messages via get_messages()")
            elif hasattr(llm_context, 'messages'):
                messages = llm_context.messages
                logger.debug(f"Got {len(messages) if messages else 0} messages via messages attr")
            elif isinstance(llm_context, dict):
                messages = llm_context.get('messages', [])
                logger.debug(f"Got {len(messages) if messages else 0} messages from dict")
            
            if not messages:
                logger.debug(f"No messages found. Context type: {type(llm_context)}")
                return transcript, list(tools_used_set)
            
            logger.debug(f"Found {len(messages)} raw messages in context")
                
            for msg in messages:
                if not isinstance(msg, dict):
                    if hasattr(msg, '__dict__'):
                        msg = msg.__dict__
                    else:
                        continue
                    
                role = msg.get("role")
                
                content = msg.get("content") or msg.get("text")
                
                if role == "assistant" and msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        if isinstance(tc, dict):
                            fn = tc.get("function", {})
                            name = fn.get("name") if isinstance(fn, dict) else None
                        elif hasattr(tc, "function"):
                            name = getattr(tc.function, "name", None)
                        else:
                            continue
                        if name:
                            tools_used_set.add(name)
                            transcript.append({
                                "role": "assistant",
                                "content": f"[Action: {name}]",
                                "interrupted": False
                            })
                    continue
                
                if role not in ("user", "assistant"):
                    continue
                    
                if not content:
                    continue
                    
                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            text_parts.append(part)
                    content = " ".join(text_parts)
                
                if not isinstance(content, str) or not content.strip():
                    continue
                
                content = content.strip()
                
                is_interrupted = False
                if role == "assistant" and interrupted_set:
                    key = content[:100]
                    if key in interrupted_set:
                        is_interrupted = True
                        logger.debug(f"Marking message as interrupted: {key[:50]}...")
                    
                transcript.append({
                    "role": role,
                    "content": content,
                    "interrupted": is_interrupted
                })
            
            tools_used = sorted(tools_used_set)
            logger.debug(f"Extracted {len(transcript)} conversation messages, {len(tools_used)} unique tools: {tools_used}")

            # --- Per-turn timestamp annotation ---
            # Timestamps are stored as elapsed seconds from call start (see
            # on_llm_response / on_user_turn callbacks).  Format as "M:SS" for
            # display in the transcript viewer.
            def _fmt_elapsed(elapsed_s: float) -> str:
                total = max(0, int(elapsed_s))
                return f"{total // 60}:{total % 60:02d}"

            # Build text-prefix → elapsed-timestamp lookup maps from the capture
            # buffers.  Matching by the first 80 chars of text is reliable: two
            # different messages are extremely unlikely to share the same 80-char
            # prefix within a single call.
            captured_user = self.user_turn_timestamps.get(call_sid, [])
            captured_assistant = self.pending_responses.get(call_sid, [])

            user_ts_map: dict = {}
            for entry in captured_user:
                key = entry["text"][:80].lower()
                if key not in user_ts_map:
                    user_ts_map[key] = _fmt_elapsed(entry["elapsed_s"])

            assistant_ts_map: dict = {}
            for entry in captured_assistant:
                key = entry["text"][:80].lower()
                if key not in assistant_ts_map:
                    assistant_ts_map[key] = _fmt_elapsed(entry["elapsed_s"])

            for msg in transcript:
                if msg.get("timestamp"):
                    continue  # already has a timestamp — leave it alone
                content = msg.get("content", "")
                key = content[:80].lower()
                ts = (
                    user_ts_map.get(key)
                    if msg["role"] == "user"
                    else assistant_ts_map.get(key)
                )
                if ts:
                    msg["timestamp"] = ts

            # --- Incomplete response recovery ---
            # If the transcript ends with a user message the LLM context never has the
            # AI's reply (caller hung up while the LLM was still generating).  Check the
            # pending_responses buffer populated by LLMResponseCapture and, when the last
            # captured response is not already represented in the context, append it so
            # reviewers and ACW see the full exchange.
            if transcript and transcript[-1]["role"] == "user" and captured_assistant:
                last_capture = captured_assistant[-1]
                captured_text = last_capture["text"]
                captured_key = captured_text[:80].lower()

                # Only append if the captured text is not already in the transcript.
                # This prevents re-appending a response that WAS committed to context
                # (i.e. the last caller turn ends the conversation but the AI's prior
                # response is already present in the context messages).
                already_committed = any(
                    entry["role"] == "assistant"
                    and entry.get("content", "")[:80].lower() == captured_key
                    for entry in transcript
                )

                if not already_committed:
                    transcript.append({
                        "role": "assistant",
                        "content": captured_text,
                        "interrupted": False,
                        "incomplete": True,
                        "timestamp": _fmt_elapsed(last_capture["elapsed_s"]),
                    })
                    logger.info(
                        f"📋 Recovered incomplete AI response ({len(captured_text)} chars) "
                        f"at T+{last_capture['elapsed_s']:.1f}s for call {call_sid} "
                        f"— caller hung up before LLM context committed"
                    )
                
        except Exception as e:
            logger.exception(f"Error extracting transcript: {e}")
            tools_used = []
            
        return transcript, tools_used
    
