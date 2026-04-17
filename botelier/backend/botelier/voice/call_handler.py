"""
Call Handler - Orchestrates Pipecat pipeline for incoming Twilio calls.

This module manages the lifecycle of voice call sessions, creating and running
Pipecat pipelines with TwilioFrameSerializer for real-time audio streaming.
"""

import os
import json
import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import WebSocket
from sqlalchemy.orm import Session
from loguru import logger

from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.frames.frames import (
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSAudioRawFrame,
)
from pipecat.pipeline.runner import PipelineRunner

from .engine import VoiceEngineFactory
from .greeting_cache import get_or_generate_greeting_audio
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


def _fetch_call_log_retry(call_sid: str):
    """Synchronous helper: open a fresh DB session, query for the CallLog,
    optionally stamp answered_at, then close the session.

    Returns (id, started_at) on success, None if the record is not found.
    Must be called via asyncio.to_thread so that the synchronous DB round-trip
    does not block the asyncio event loop.
    """
    from ..models.call_log import CallLog
    from ..database import SessionLocal as _SessionLocal
    _db = _SessionLocal()
    try:
        rec = _db.query(CallLog).filter(CallLog.call_sid == call_sid).first()
        if rec is None:
            return None
        if not rec.answered_at:
            rec.answered_at = datetime.utcnow()
            _db.commit()
        return (rec.id, rec.started_at)
    finally:
        _db.close()


async def _prewarm_llm_cache(system_prompt: str, model: str, api_key: str, call_sid: str, event_queue=None) -> None:
    """Fire a single low-cost OpenAI call to warm the server-side prompt cache.

    Runs as a background asyncio task concurrent with the greeting audio playback
    (the STT-muted window that lasts 11–16 s).  By the time the greeting ends and
    the caller first speaks, the 5 k-token system prompt is already resident in
    OpenAI's prompt cache, dropping first-turn TTFB from ~1.9 s to ~0.6 s.

    This call is entirely outside the Pipecat pipeline — it never produces any
    audio and cannot interfere with the call.  Failures are logged as warnings
    and never propagate to the caller.

    When ``event_queue`` is provided, emits ``llm_prewarm_completed`` on success
    or ``llm_prewarm_failed`` on failure with a sanitized error_type/message.
    """
    import time as _time
    _t_start = _time.monotonic()
    try:
        import openai as _openai
        _client = _openai.AsyncOpenAI(api_key=api_key)
        await _client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}],
            max_tokens=1,
        )
        _duration_ms = int((_time.monotonic() - _t_start) * 1000)
        logger.info(f"🔥 LLM prompt cache pre-warmed for call {call_sid} (model={model}, {_duration_ms}ms)")
        if event_queue is not None:
            event_queue.log(
                "llm_prewarm_completed",
                event_source="pipecat",
                severity="info",
                details={"duration_ms": _duration_ms, "model": model},
            )
    except Exception as _pw_err:
        _duration_ms = int((_time.monotonic() - _t_start) * 1000)
        logger.warning(f"LLM pre-warm failed for call {call_sid} (non-fatal): {_pw_err}")
        if event_queue is not None:
            event_queue.log(
                "llm_prewarm_failed",
                event_source="pipecat",
                severity="warning",
                details={
                    "duration_ms": _duration_ms,
                    "model": model,
                    "error_class": type(_pw_err).__name__,
                    "error_message": str(_pw_err)[:200],
                },
            )


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
        self.call_recording_sids: Dict[str, str] = {}  # call_sid -> Twilio recording SID (set when recording starts)
        self.call_tasks: Dict[str, Any] = {}  # call_sid -> PipelineTask (cancelled by connect-complete when stream ends)
        # Task #96: track the asyncio.Task that runs mark_greeting_completed
        # in a thread, keyed by call_sid. Finalization paths await this (with
        # a 500 ms timeout) before calling complete_call so the late-firing
        # greeting callback never overwrites a completed row's status.
        self.greeting_mark_tasks: Dict[str, Any] = {}
        # SIDs for which connect_complete arrived BEFORE the pipeline finished
        # constructing/registering. handle_call checks this dict right after
        # registering the task and tears it down immediately, instead of
        # letting the pipeline run blind for 5 minutes until Pipecat's
        # internal idle timeout fires. Stored as {sid: insertion_timestamp}
        # so opportunistic TTL purging keeps the dict bounded even if a
        # delayed/retried connect_complete arrives long after pipeline
        # teardown (no later finally would otherwise clean it up).
        # Only touched on the asyncio event loop — no locking needed.
        self.pending_cancels: Dict[str, datetime] = {}
        # Purge pending_cancels entries older than this many seconds on every
        # write. Twilio retries arrive within minutes; 5 minutes is a generous
        # upper bound that still keeps memory bounded.
        self._pending_cancel_ttl_secs = 300
    
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
            should_record_call = False
            
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
                if call_log_record is None:
                    _call_log_found = False
                    for _attempt in range(3):
                        await asyncio.sleep(0.2)
                        _result = await asyncio.to_thread(_fetch_call_log_retry, call_sid)
                        if _result is not None:
                            call_log_id, call_started_at = _result
                            _call_log_found = True
                            logger.info(
                                f"call_log found on retry attempt {_attempt + 1} for {call_sid}"
                            )
                            break
                    if not _call_log_found:
                        logger.warning(
                            f"call_log not found after 3 retries for {call_sid} — "
                            f"recording and event queue will be skipped"
                        )
                if call_log_record and call_log_id is None:
                    # Record was found by the INITIAL query (not a retry) —
                    # update answered_at via the original session.
                    call_log_id = call_log_record.id
                    call_started_at = call_log_record.started_at
                    if not call_log_record.answered_at:
                        call_log_record.answered_at = datetime.utcnow()
                        db.commit()
                if call_log_id is not None:
                    logger.info(
                        f"call_log_id={call_log_id} resolved for {call_sid} — "
                        f"event queue and recording will be active"
                    )
                
                logger.info(f"🤖 Assistant: '{assistant.name}' (ID: {assistant.id})")
                
                # Fetch account's Twilio sub-account credentials (for transfers)
                from ..models.account import Account as _CallAccount
                _call_acct = db.query(_CallAccount).filter(_CallAccount.id == assistant.account_id).first()
                if _call_acct:
                    hotel_twilio_sid = _call_acct.twilio_sub_account_sid
                    hotel_twilio_token = _call_acct.twilio_sub_auth_token
                    if hotel_twilio_sid:
                        logger.info(f"🏨 Using account sub-account: {hotel_twilio_sid[:10]}...")

                    # Resolve whether this call should be recorded.
                    # Done here (while DB is open) so we don't need the session later.
                    from ..auth.features import get_account_features as _get_acct_features
                    _acct_features = _get_acct_features(
                        subscription_tier=getattr(_call_acct, "subscription_tier", None) or "free",
                        feature_flags_override=(_call_acct.feature_flags or {}),
                    )
                    _acct_recording_allowed = _acct_features.get("call_recording", False)
                    _asst_recording_enabled = bool(
                        (assistant.call_settings or {}).get("call_recording_enabled", False)
                    )
                    should_record_call = _acct_recording_allowed and _asst_recording_enabled
                    logger.debug(
                        f"🎙️ Recording check — account_allowed={_acct_recording_allowed}, "
                        f"assistant_enabled={_asst_recording_enabled}, should_record={should_record_call}"
                    )

                # Convert database model to VoiceAgentConfig
                # _create_agent_config is async — it loads the knowledge base in
                # a thread pool to avoid blocking the event loop.
                config = await self._create_agent_config(assistant)
                
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
            #
            # auto_hang_up=False: disables the automatic REST hangup that
            # TwilioFrameSerializer sends when EndFrame flows through it.
            #
            # Rationale: with auto_hang_up=True, warm transfers fail with HTTP
            # 404 because TwilioFrameSerializer's _hang_up_call() fires and
            # terminates the Twilio call before (or immediately after) our
            # _execute_transfer REST call can send the <Dial> TwiML.  With
            # auto_hang_up=False the pipeline ends cleanly on our side, the
            # WebSocket connection closes, and Twilio handles call teardown via
            # its own TwiML execution path:
            #   - Warm transfer: Twilio bridges via <Dial> after <Stop><Stream>
            #   - Cold transfer: Twilio SIP REFERs the call away
            #   - Normal hangup: caller hangs up → WebSocket close → Twilio
            #     ends the call naturally (no separate hangup REST needed)
            serializer = TwilioFrameSerializer(
                stream_sid=stream_sid,
                call_sid=call_sid,
                account_sid=os.environ.get("TWILIO_ACCOUNT_SID"),
                auth_token=os.environ.get("TWILIO_AUTH_TOKEN"),
                params=TwilioFrameSerializer.InputParams(
                    auto_hang_up=False,
                )
            )
            
            # 5. Create WebSocket transport (WebSocket ALREADY ACCEPTED, 'start' ALREADY READ)
            #
            # Twilio Media Streams are always 8 kHz μ-law on both directions.
            # audio_in_sample_rate=8000  — inbound μ-law decoded to 8 kHz PCM for STT
            # audio_out_sample_rate=8000 — TTS output resampled to 8 kHz before μ-law
            #                              encoding by TwilioFrameSerializer
            #
            # Without these, Pipecat's resampling chain is misconfigured: Deepgram TTS
            # defaults to 24 kHz linear16, causing 3× playback speed / corrupted audio.
            #
            # create_transport_params() sets vad_analyzer on the transport only for
            # WebRTC/AIC providers.  Silero VAD + SmartTurn are integrated directly
            # into LLMUserAggregatorParams inside create_pipeline() to avoid the
            # race condition that caused the first utterance to be silently dropped.
            _vad_p = VoiceEngineFactory.create_transport_params(config)
            _ws_params_kwargs = dict(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_in_sample_rate=8000,   # Twilio sends μ-law at 8 kHz
                audio_out_sample_rate=8000,  # Twilio expects μ-law at 8 kHz
                add_wav_header=False,        # Twilio uses raw μ-law, not WAV
                serializer=serializer,
                vad_analyzer=_vad_p.vad_analyzer,
            )
            _turn_analyzer = getattr(_vad_p, "turn_analyzer", None)
            if _turn_analyzer is not None:
                _ws_params_kwargs["turn_analyzer"] = _turn_analyzer
            transport = FastAPIWebsocketTransport(
                websocket=websocket,
                params=FastAPIWebsocketParams(**_ws_params_kwargs),
            )
            # Silero VAD is wired via LLMUserAggregatorParams (no transport-level VAD),
            # so check config directly for the log rather than _vad_p.vad_analyzer.
            _vad_label = (
                f"enabled ({config.vad_provider})"
                if (config.enable_vad and config.vad_provider)
                else "disabled"
            )
            logger.info(f"🔊 Transport sample rates: in=8000Hz, out=8000Hz | VAD={_vad_label}")
            
            # 6. Create Pipecat pipeline with function calling support
            # Create interruption callback to track interrupted responses
            def on_interruption(content: str):
                self.mark_response_interrupted(call_sid, content)

            # Monotonic clock reference used for per-stage latency logging in the
            # pipeline processors (UserTurnCapture, LLMResponseCapture).
            _call_start_mono = time.monotonic()

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
            
            pipeline, task, llm, context_aggregator, llm_context, tts_completion_watcher, first_speech_tracker, greeting_completion_tracker, idle_timeout_tracker, user_turn_capture, tts_latency_tracker = VoiceEngineFactory.create_pipeline(
                config=config,
                api_keys=api_keys,
                transport=transport,
                function_schemas=function_schemas if function_schemas else None,
                function_handlers=function_handlers if function_handlers else None,
                on_interruption=on_interruption,
                on_llm_response=on_llm_response,
                on_user_turn=on_user_turn,
                call_start_mono=_call_start_mono,
            )

            # Link the TTS completion watcher to the FunctionMapper (if one was
            # created for this call) so transfer handlers can await actual TTS completion.
            if call_sid in self.call_mappers:
                self.call_mappers[call_sid].set_tts_completion_watcher(tts_completion_watcher)
            
            # 6.5 Register MCP tools if connection is configured (must happen AFTER pipeline creation)
            # The event_queue is created below (section 7.5) — we capture timing and outcome
            # in a local dict here and emit the event once the queue is available.
            _mcp_event_payload = None  # Tuple[event_type, details] or None if MCP skipped
            logger.info(f"🔍 MCP registration check: mcp_connection_data={mcp_connection_data is not None}, mcp_enabled_tools={mcp_enabled_tools}, PIPECAT_MCP_AVAILABLE={PIPECAT_MCP_AVAILABLE}")
            if mcp_connection_data and mcp_enabled_tools and PIPECAT_MCP_AVAILABLE:
                import time as _time_mcp
                _mcp_t_start = _time_mcp.monotonic()
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
                    _tools_registered = 0
                    if all_tools_schema.standard_tools:
                        from pipecat.adapters.schemas.tools_schema import ToolsSchema
                        
                        filtered_tools = [
                            tool for tool in all_tools_schema.standard_tools
                            if tool.name in mcp_enabled_tools
                        ]
                        
                        if filtered_tools:
                            filtered_schema = ToolsSchema(standard_tools=filtered_tools)
                            await mcp_client.register_tools_schema(filtered_schema, llm)
                            _tools_registered = len(filtered_tools)
                            logger.info(f"🔌 Registered {len(filtered_tools)} MCP tools with LLM for call {call_sid}: {[t.name for t in filtered_tools]}")
                        else:
                            logger.warning(f"No MCP tools matched enabled list: {mcp_enabled_tools}")
                    else:
                        logger.warning(f"MCP server returned no tools")
                    
                    # Store client for cleanup
                    self.call_mcp_clients[call_sid] = mcp_client

                    _mcp_duration_ms = int((_time_mcp.monotonic() - _mcp_t_start) * 1000)
                    _mcp_event_payload = (
                        "mcp_registration_completed",
                        "info",
                        {
                            "duration_ms": _mcp_duration_ms,
                            "tools_registered_count": _tools_registered,
                        },
                    )

                except Exception as e:
                    _mcp_duration_ms = int((_time_mcp.monotonic() - _mcp_t_start) * 1000)
                    logger.error(f"Failed to register MCP tools: {e}")
                    _mcp_event_payload = (
                        "mcp_registration_failed",
                        "error",
                        {
                            "duration_ms": _mcp_duration_ms,
                            "error_class": type(e).__name__,
                            "error_message": str(e)[:200],
                        },
                    )
            
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
                #
                # All scalar values are captured before entering the thread so that
                # no ORM objects or mutable async state cross the thread boundary.
                from ..models.call_event import CallEvent as _CallEvent
                import uuid as _uuid
                _t_call_log_id = call_log_id
                _t_stream_sid = stream_sid
                _t_started = call_started_at or self.call_start_times.get(call_sid)

                def _write_call_answered() -> None:
                    _db = SessionLocal()
                    try:
                        _already = (
                            _db.query(_CallEvent)
                            .filter(
                                _CallEvent.call_log_id == _t_call_log_id,
                                _CallEvent.event_type == "call_answered",
                            )
                            .first()
                        )
                        if not _already:
                            _now = datetime.utcnow()
                            _offset_ms = (
                                int((_now - _t_started).total_seconds() * 1000)
                                if _t_started
                                else None
                            )
                            _db.add(
                                _CallEvent(
                                    id=_uuid.uuid4(),
                                    call_log_id=_t_call_log_id,
                                    event_type="call_answered",
                                    event_source="pipecat",
                                    severity="info",
                                    occurred_at=_now,
                                    offset_ms=_offset_ms,
                                    details={"stream_sid": _t_stream_sid},
                                )
                            )
                            _db.commit()
                            logger.info("📞 call_answered event written synchronously (pipecat)")
                        else:
                            logger.debug("📞 call_answered already exists — skipping duplicate")
                    except Exception as _e:
                        logger.error(f"❌ Failed to write call_answered event: {_e}")
                    finally:
                        _db.close()

                await asyncio.to_thread(_write_call_answered)

                # Fire in-call recording as a non-blocking background task.
                # This replaces the phone-number-level VoiceRecord approach; no
                # Reconfigure step is needed.  Failures are logged but never abort
                # the call.
                if should_record_call:
                    from ..services.recording_sync import start_in_call_recording as _start_rec
                    from ..config.domain import get_public_base_url as _get_base_url
                    _rec_task = asyncio.create_task(
                        _start_rec(
                            call_sid=call_sid,
                            account_sub_sid=hotel_twilio_sid,
                            account_sub_token=hotel_twilio_token,
                            base_url=_get_base_url(),
                        )
                    )
                    # Store the recording SID when the task completes so transfer
                    # handlers can stop the recording before handing off.
                    # done_callback runs synchronously in the event loop — no awaiting.
                    # Guard with active_calls check: if cleanup already ran the SID
                    # must not be re-inserted as a stale entry.
                    def _on_rec_started(_t, _sid_store=self.call_recording_sids,
                                        _active=self.active_calls, _csid=call_sid):
                        try:
                            sid = _t.result()
                            if sid and _csid in _active:
                                _sid_store[_csid] = sid
                        except Exception:
                            pass
                    _rec_task.add_done_callback(_on_rec_started)
                    logger.info(f"🎙️ In-call recording task queued for {call_sid}")

                # Pass the queue reference to FunctionMapper so it can log pipeline events
                if call_sid in self.call_mappers:
                    self.call_mappers[call_sid].set_event_queue(event_queue)

                # Wire event_queue to the FirstUserSpeechTracker in the pipeline
                first_speech_tracker.set_event_queue(event_queue)
                # Wire event_queue to the GreetingCompletionTracker (first BotStoppedSpeakingFrame)
                greeting_completion_tracker.set_event_queue(event_queue)
                # Wire event_queue to the IdleTimeoutTracker (fires on caller silence)
                idle_timeout_tracker.set_event_queue(event_queue)
                # Wire event_queue to UserTurnCapture (emits turn_finalized per user utterance)
                user_turn_capture.set_event_queue(event_queue)
                # Wire event_queue to TtsPipelineLatencyTracker (emits turn_latency per responded turn)
                tts_latency_tracker.set_event_queue(event_queue)

                # Emit deferred MCP registration event now that the queue is running.
                # _mcp_event_payload is populated above when MCP ran; None means MCP was skipped.
                if _mcp_event_payload is not None:
                    _mcp_ev_type, _mcp_sev, _mcp_details = _mcp_event_payload
                    event_queue.log(
                        _mcp_ev_type,
                        event_source="pipecat",
                        severity=_mcp_sev,
                        details=_mcp_details,
                    )

                # Wire a DB callback to GreetingCompletionTracker so ai_greeting_completed
                # is set as soon as the greeting TTS finishes — reliably from our side,
                # independent of Twilio status webhook timing.
                _greeting_call_sid = call_sid  # capture for closure
                _handler = self  # capture for closure — track task handle per call
                async def _on_greeting_completed():
                    def _sync_mark_greeting():
                        from ..services.call_logger import CallLogger as _CallLogger
                        gdb = SessionLocal()
                        try:
                            _cl = _CallLogger(gdb)
                            _cl.mark_greeting_completed(_greeting_call_sid)
                        finally:
                            gdb.close()
                    # Task #96: expose the underlying thread future as a task so
                    # finalization paths (_save_call_transcript, defensive finally)
                    # can wait up to 500 ms for this DB write to land before
                    # they compute the terminal status. Prevents the race where
                    # complete_call stamps ended_early and mark_greeting_completed
                    # subsequently corrects it back to completed (or vice versa).
                    _mark_task = asyncio.create_task(
                        asyncio.to_thread(_sync_mark_greeting),
                        name=f"mark_greeting_completed:{_greeting_call_sid}",
                    )
                    _handler.greeting_mark_tasks[_greeting_call_sid] = _mark_task
                    try:
                        await _mark_task
                    except Exception as _ge:
                        logger.error(f"Failed to set ai_greeting_completed: {_ge}")
                greeting_completion_tracker.set_greeting_callback(_on_greeting_completed)

                # Wire WebSocket liveness check: if the caller hangs up during the
                # greeting, Pipecat continues draining buffered TTS frames and will
                # fire BotStoppedSpeakingFrame even after the WebSocket closes.
                # This guard ensures we do NOT mark the greeting as completed in
                # that case — the caller never heard those buffered frames.
                greeting_completion_tracker.set_call_active(
                    lambda: websocket.client_state.name == "CONNECTED"
                )

                # Task #98 — wire a DB callback to FirstUserSpeechTracker so
                # call_logs.caller_spoke flips to TRUE the moment the first
                # caller transcription arrives. Mirrors the greeting callback
                # pattern above. Used by the analytics partition to keep silent
                # calls out of the AI Handled bucket.
                _speech_call_sid = call_sid  # capture for closure
                async def _on_first_user_speech():
                    def _sync_mark_caller_spoke():
                        from ..services.call_logger import CallLogger as _CallLogger
                        sdb = SessionLocal()
                        try:
                            _cl = _CallLogger(sdb)
                            _cl.mark_caller_spoke(_speech_call_sid)
                        finally:
                            sdb.close()
                    try:
                        await asyncio.to_thread(_sync_mark_caller_spoke)
                    except Exception as _se:
                        logger.error(f"Failed to set caller_spoke: {_se}")
                first_speech_tracker.set_first_speech_callback(_on_first_user_speech)

            # 8. Queue greeting message
            if call_sid in self.call_event_queues:
                self.call_event_queues[call_sid].log(
                    "greeting_started",
                    event_source="pipecat",
                    severity="info",
                )
            # Attempt to play cached PCM greeting to avoid a Deepgram TTS token.
            # Falls back to TTSSpeakFrame (normal TTS path) on any error.
            _greeting_played_from_cache = False
            if config.tts_provider.lower() == "deepgram" and api_keys.get("deepgram_api_key"):
                try:
                    _voice = config.tts_voice_id or "aura-2-helena-en"
                    _tts_cfg = {"voice": _voice}
                    _audio = await get_or_generate_greeting_audio(
                        greeting_text=config.greeting_message,
                        tts_config=_tts_cfg,
                        api_key=api_keys["deepgram_api_key"],
                        assistant_id=str(assistant.id),
                    )
                    # Split into 320-byte frames (20 ms @ 8 kHz linear16 PCM).
                    # TTSAudioRawFrame is required — the transport only processes
                    # OutputAudioRawFrame subclasses, and uses TTSAudioRawFrame
                    # to track bot-speaking state and set _tts_audio_received so
                    # that TTSStoppedFrame correctly fires BotStoppedSpeakingFrame.
                    _chunk_size = 320  # 8000 Hz * 2 bytes/sample * 0.020 s
                    _frames = [TTSStartedFrame()]
                    for _i in range(0, len(_audio), _chunk_size):
                        _frames.append(
                            TTSAudioRawFrame(
                                audio=_audio[_i : _i + _chunk_size],
                                sample_rate=8000,
                                num_channels=1,
                            )
                        )
                    _frames.append(TTSStoppedFrame())
                    await task.queue_frames(_frames)
                    _greeting_played_from_cache = True
                    logger.info("🎙️ Greeting played from cache (no Deepgram TTS token)")
                except Exception as _cache_err:
                    logger.warning(
                        f"Greeting cache failed, falling back to TTSSpeakFrame: {_cache_err}"
                    )

            if not _greeting_played_from_cache:
                await task.queue_frames([TTSSpeakFrame(text=config.greeting_message)])

            # Pre-warm the OpenAI prompt cache during the greeting window.
            # The greeting plays for 11–16 s while the STT is muted — this
            # background task fires a max_tokens=1 call so the 5 k-token system
            # prompt is resident in OpenAI's cache before the caller first speaks.
            # Result: first-turn TTFB drops from ~1.9 s (cold) to ~0.6 s (warm).
            _openai_key = api_keys.get("openai_api_key")
            if config.llm_provider.lower() == "openai" and _openai_key:
                asyncio.create_task(
                    _prewarm_llm_cache(
                        system_prompt=config.system_prompt,
                        model=config.llm_model,
                        api_key=_openai_key,
                        call_sid=call_sid,
                        event_queue=self.call_event_queues.get(call_sid),
                    )
                )

            logger.info(f"▶️ Pipeline starting: STT ({config.stt_provider}) → LLM ({config.llm_provider}) → TTS ({config.tts_provider})")

            # 9. Run pipeline (blocks until call ends)
            # Pipecat handles all remaining WebSocket messages (media, dtmf, stop)
            runner = PipelineRunner()
            self.call_tasks[call_sid] = task
            # Race fix: if connect_complete arrived BEFORE we got here (caller
            # hung up faster than the pipeline could construct), a pending
            # cancel intent is waiting in self.pending_cancels. Honour it
            # immediately so the runner sees the CancelFrame on its first
            # iteration and exits, instead of running blind for 5 minutes
            # until Pipecat's internal idle timeout fires.
            if call_sid in self.pending_cancels:
                pending_recorded_at = self.pending_cancels.pop(call_sid, None)
                logger.info(
                    f"Honouring pending cancel for {call_sid} — connect_complete "
                    f"arrived before pipeline registration; tearing down immediately"
                )
                # Record the race firing so we can quantify how often it
                # actually triggers post-fix (Task #94 observability).
                if call_sid in self.call_event_queues:
                    delta_ms = None
                    if pending_recorded_at is not None:
                        try:
                            delta_ms = int(
                                (datetime.utcnow() - pending_recorded_at).total_seconds() * 1000
                            )
                        except Exception:
                            delta_ms = None
                    self.call_event_queues[call_sid].log(
                        "pipeline_registered_after_cancel",
                        event_source="app",
                        severity="warning",
                        details={"cancel_to_register_ms": delta_ms},
                    )
                try:
                    await task.cancel()
                except Exception as e:
                    logger.warning(f"Error applying pending cancel for {call_sid}: {e}")
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

            # ── Task #96: defensive finalization ──────────────────────────────
            # Last line of defence for bugs in the try/except blocks above.
            # If the row is still in a non-terminal status at this point, the
            # pipeline has fully shut down and *nothing else* is going to
            # finalize it — drive complete_call(forced_by="finally_defensive")
            # using a fresh short-lived session so we never leave a CallLog
            # stuck on initiated/ringing/in_progress.
            try:
                await self._await_greeting_mark(call_sid, timeout=0.5)
                def _sync_defensive_finalize():
                    from ..models.call_log import CallLog as _CallLog, CallStatus as _CS
                    _db = SessionLocal()
                    try:
                        row = _db.query(_CallLog).filter(_CallLog.call_sid == call_sid).first()
                        if row is None:
                            return
                        if row.status not in (
                            _CS.INITIATED.value,
                            _CS.RINGING.value,
                            _CS.IN_PROGRESS.value,
                        ):
                            return
                        CallLogger(_db).complete_call(
                            call_sid=call_sid,
                            forced_by="finally_defensive",
                        )
                    finally:
                        _db.close()
                await asyncio.to_thread(_sync_defensive_finalize)
            except Exception as _fin_err:
                logger.warning(
                    f"Defensive finalization failed for {call_sid}: {_fin_err}"
                )

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
            if call_sid in self.call_tasks:
                del self.call_tasks[call_sid]
            # Task #96: drop the greeting-mark task handle — the underlying
            # DB write is either already committed or its exception was
            # logged by _on_greeting_completed.
            if call_sid in self.greeting_mark_tasks:
                del self.greeting_mark_tasks[call_sid]
            # Always remove the pending-cancel intent at end of life so the
            # dict never grows unboundedly under abnormal terminations.
            self.pending_cancels.pop(call_sid, None)

    def is_pipeline_active(self, call_sid: str) -> bool:
        """
        Task #96: True iff a pipeline for ``call_sid`` is still registered
        in-process. Used by the stuck-call sweeper and the Twilio ``/status``
        safety-net to avoid racing with a healthy finalization.
        """
        return call_sid in self.active_calls or call_sid in self.call_tasks

    async def _await_greeting_mark(self, call_sid: str, timeout: float = 0.5) -> None:
        """
        Task #96: wait up to ``timeout`` seconds for a pending
        mark_greeting_completed thread-task to finish before reading
        ``ai_greeting_completed`` in a finalization path.

        Safe to call when no task exists — returns immediately. Never raises;
        a timeout or task exception is logged and swallowed so the caller can
        still finalize the row. Non-cancelling on timeout: the underlying DB
        write will still commit when it completes; its result is accepted on
        the next webhook or sweeper tick via the existing race-correction
        branch in ``mark_greeting_completed``.
        """
        task = self.greeting_mark_tasks.get(call_sid)
        if task is None or task.done():
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f"_await_greeting_mark: greeting-mark task still pending after "
                f"{timeout:.2f}s for {call_sid} — proceeding with finalization "
                f"(race correction will reclassify on next read if needed)"
            )
        except Exception as e:
            logger.warning(f"_await_greeting_mark: greeting-mark task failed for {call_sid}: {e}")

    async def cancel_call_pipeline(self, call_sid: str) -> None:
        """
        Cancel the running PipelineTask for a call.

        Called from connect_complete when Twilio signals the media stream has
        ended.  Sends a CancelFrame through the pipeline, which triggers a
        clean ordered shutdown of all processors (STT, LLM, TTS) and unblocks
        runner.run(task) so the handle_call finally block runs immediately.

        Safe to call multiple times or when no pipeline is running — if
        call_sid is not in call_tasks the method records a pending-cancel
        intent so handle_call can honour it as soon as the pipeline finishes
        registering. This avoids the fast-hangup race where connect_complete
        arrives before the pipeline is in self.call_tasks and the pipeline
        would otherwise run blind for ~5 minutes until Pipecat's idle timeout.
        Idempotent against Twilio retry semantics — second call either finds
        the cancel already executed (task gone) or already pending (set add
        is a no-op).
        """
        task = self.call_tasks.get(call_sid)
        if task is None:
            # Always record a pending-cancel intent. We must NOT gate this on
            # active_calls membership, because connect_complete can arrive
            # extremely fast — even before handle_call reaches its
            # active_calls[call_sid] = task line. handle_call honours the
            # pending intent the moment it registers the task.
            #
            # To prevent unbounded growth from late retries/replays where no
            # subsequent handle_call/finally will ever run for this SID, we
            # opportunistically purge entries older than _pending_cancel_ttl_secs
            # on every write. Twilio retries arrive within minutes, so a 5-min
            # TTL is generous yet still bounded.
            now = datetime.utcnow()
            ttl = self._pending_cancel_ttl_secs
            if self.pending_cancels:
                expired = [
                    sid for sid, ts in self.pending_cancels.items()
                    if (now - ts).total_seconds() > ttl
                ]
                for sid in expired:
                    self.pending_cancels.pop(sid, None)
            self.pending_cancels[call_sid] = now
            logger.debug(
                f"cancel_call_pipeline: no active pipeline for {call_sid} "
                f"— recording pending cancel (will be honoured at registration "
                f"or expire in {ttl}s)"
            )
            return
        logger.info(f"Cancelling pipeline for call {call_sid} via connect-complete signal")
        try:
            await task.cancel()
        except Exception as e:
            logger.warning(f"cancel_call_pipeline: error cancelling pipeline for {call_sid}: {e}")

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
    
    async def _create_agent_config(self, assistant: Assistant) -> VoiceAgentConfig:
        """
        Convert database Assistant model to VoiceAgentConfig.
        
        Injects knowledge base content directly into the system prompt for:
        - Immediate access without tool-call latency
        - Prompt caching on subsequent turns
        - Better answer quality (LLM has full context)
        
        The knowledge base load is run in a thread (asyncio.to_thread) so that
        the synchronous SQLAlchemy query does not block the event loop during
        call setup.
        
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
                kb_content = await asyncio.to_thread(
                    load_knowledge_for_prompt, str(assistant.knowledge_base_id)
                )
            except Exception as e:
                logger.error(f"Failed to load KB for assistant {assistant.id}: {e}")
                kb_content = ""
        else:
            logger.info(f"No knowledge base assigned to assistant {assistant.id}")
        
        if kb_content:
            # Task #106 — order matters for OpenAI prompt caching.
            #
            # OpenAI's prompt cache hits on the longest STABLE prefix from the
            # start of the messages array. The persona (`base_prompt`) and the
            # static RESPONSE GUIDELINES below are byte-stable across every
            # call to the same assistant. KB content is also stable for the
            # 5-minute in-process TTL window (knowledge_handler._kb_cache),
            # but it is the only segment that can change mid-day when an
            # operator edits the KB. By placing the volatile KB block LAST,
            # the much larger persona+guidelines prefix stays cacheable even
            # when a KB edit invalidates the trailing tokens — protecting
            # cached_tokens / prompt_tokens ratio on every subsequent turn.
            #
            # The new turn_latency.cached_tokens telemetry lets us measure
            # the effect of this ordering on the next deploy without guessing.
            enhanced_prompt = f"""{base_prompt}

## RESPONSE GUIDELINES
- Answer questions from the knowledge base naturally and conversationally
- Keep responses concise (under 50 words) since this is a phone call
- Only transfer to a human if: (1) the caller explicitly requests to speak with someone, OR (2) the question requires information NOT in the knowledge base AND the caller needs urgent assistance
- For general questions covered by the knowledge base, answer directly without offering to transfer

## KNOWLEDGE BASE
You have access to the following Q&A knowledge base. Use this information to answer guest questions directly and confidently. Do NOT transfer the call or say you don't have information if the answer is in this knowledge base.

{kb_content}"""
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

        Thread-safety contract:
        - _extract_transcript only accesses plain Python dicts (self.interrupted_responses,
          self.pending_responses, self.user_turn_timestamps) and iterates llm_context messages.
          No I/O. Safe on the event loop.
        - SessionLocal(), CallLogger.complete_call(), and db.close() all run inside _sync_save,
          which executes in a worker thread via asyncio.to_thread. No session ever touches the
          event loop.
        - transcript is a list of plain dicts (role: str, content: str, timestamp: str, etc.).
          tools_used is a list of strings. Both are safe to pass across thread boundaries.
        - No ORM object is created on the event loop; none leaves the worker thread.
        """
        try:
            # ── Extract on event loop — pure Python, no I/O ──────────────────────
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

            # Datetime arithmetic — no I/O, safe on event loop
            duration_seconds = None
            if call_sid in self.call_start_times:
                start_time = self.call_start_times[call_sid]
                duration_seconds = max(0, int((datetime.utcnow() - start_time).total_seconds()))

            # ── Capture plain values before thread boundary ───────────────────────
            # transcript is a list of plain dicts; tools_used is a list of strings.
            # All other values are plain Python scalars.
            _cap_call_sid   = call_sid
            _cap_transcript = transcript if transcript else None
            _cap_duration   = duration_seconds
            _cap_tools      = tools_used

            # Task #96: before computing the terminal status, give any in-flight
            # mark_greeting_completed write a short window to land so the row's
            # ai_greeting_completed flag reflects reality when complete_call reads it.
            await self._await_greeting_mark(call_sid, timeout=0.5)

            # ── All DB work in a thread — session never touches the event loop ────
            def _sync_save():
                db = SessionLocal()
                try:
                    cl = CallLogger(db)
                    return cl.complete_call(
                        call_sid=_cap_call_sid,
                        transcript=_cap_transcript,
                        duration_seconds=_cap_duration,
                        tools_used=_cap_tools,
                    )
                finally:
                    db.close()

            success = await asyncio.to_thread(_sync_save)
            if success:
                logger.info(f"📝 Saved transcript ({len(transcript)} messages) for call {call_sid}")
            else:
                logger.warning(f"Failed to save transcript for call {call_sid}")

        except Exception as e:
            logger.exception(f"Error saving transcript for call {call_sid}: {e}")
    
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
    
