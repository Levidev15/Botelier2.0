"""
Call Handler - Orchestrates Pipecat pipeline for incoming Twilio calls.

This module manages the lifecycle of voice call sessions, creating and running
Pipecat pipelines with TwilioFrameSerializer for real-time audio streaming.
"""

import os
import json
import asyncio
from typing import Optional, Dict, Any
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


class CallHandler:
    """
    Handles incoming Twilio call sessions.
    
    Orchestrates:
    - Database lookup: phone number → assistant
    - Pipecat pipeline creation with TwilioFrameSerializer
    - Real-time audio streaming via WebSocket
    - Call session lifecycle management
    - Function calling and knowledge base integration
    """
    
    def __init__(self):
        """Initialize call handler."""
        self.active_calls: Dict[str, asyncio.Task] = {}
    
    async def handle_call(self, websocket: WebSocket, to_number: str, db: Session):
        """
        Handle incoming call by creating Pipecat pipeline and streaming audio.
        
        Args:
            websocket: FastAPI WebSocket connection from Twilio (NOT yet accepted)
            to_number: Phone number being called (from query params)
            db: Database session
        
        Flow:
            1. Look up phone number → assistant in database
            2. Accept WebSocket and read Twilio 'start' event for stream_sid/call_sid
            3. Create Pipecat pipeline with TwilioFrameSerializer
            4. Run pipeline (Pipecat handles all WebSocket messages)
        """
        call_sid = None
        try:
            logger.info(f"📞 Incoming call to: {to_number}")
            
            # 1. Look up which assistant is assigned to this phone number
            # Query database and close session immediately to avoid connection pool exhaustion
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
                
                logger.info(f"🤖 Assistant: '{assistant.name}' (ID: {assistant.id})")
                
                # Convert database model to VoiceAgentConfig
                config = self._create_agent_config(assistant)
                
                # Fetch tools for function calling (if enabled) before closing session
                tools = []
                if config.enable_function_calling:
                    from ..models.tool import Tool
                    tools = db.query(Tool).filter(
                        Tool.hotel_id == assistant.hotel_id,
                        Tool.is_active == "true"
                    ).all()
                
            finally:
                # CRITICAL: Close database session immediately after fetching data
                # WebSocket connections are long-lived - keeping sessions open exhausts the connection pool
                db.close()
                logger.debug("✅ Database session closed")
            
            # 2. Accept WebSocket and read Twilio 'start' event
            await websocket.accept()
            logger.debug("✅ WebSocket accepted")
            
            # Read events until we get 'start' (Twilio sends 'connected' first)
            stream_sid = None
            call_sid = None
            start_message = None
            
            for _ in range(3):  # Max 3 events
                data = await websocket.receive_text()
                message = json.loads(data)
                event_type = message.get("event")
                
                if event_type == "start":
                    start_data = message.get("start", {})
                    # CRITICAL: streamSid is at start_data["streamSid"], NOT top-level
                    stream_sid = start_data.get("streamSid")
                    call_sid = start_data.get("callSid")
                    start_message = data  # Save raw message to replay to Pipecat
                    logger.info(f"📞 Call started - Stream: {stream_sid}, Call: {call_sid}")
                    break
            
            if not stream_sid or not call_sid:
                logger.error("❌ Never received 'start' event")
                await websocket.close()
                return
            
            # 3. Check for duplicate call (prevent multiple pipelines for same call)
            if call_sid in self.active_calls:
                logger.warning(f"⚠️ Call {call_sid} already has active pipeline, ignoring duplicate")
                return
            
            # 4. Get API keys from environment
            api_keys = self._get_api_keys()
            
            # 5. Create TwilioFrameSerializer with stream_sid/call_sid from start event
            serializer = TwilioFrameSerializer(
                stream_sid=stream_sid,
                call_sid=call_sid,
                account_sid=os.environ.get("TWILIO_ACCOUNT_SID"),
                auth_token=os.environ.get("TWILIO_AUTH_TOKEN"),
                params=TwilioFrameSerializer.InputParams(
                    auto_hang_up=True,  # Automatically hang up when pipeline ends
                )
            )
            
            # 6. Create WebSocket transport (WebSocket already accepted)
            transport = FastAPIWebsocketTransport(
                websocket=websocket,
                params=FastAPIWebsocketParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                    add_wav_header=False,  # Twilio uses raw μ-law, not WAV
                    serializer=serializer,
                ),
            )
            
            # 7. Create Pipecat pipeline
            pipeline, task = VoiceEngineFactory.create_pipeline(
                config=config,
                api_keys=api_keys,
                transport=transport,
            )
            
            # 8. Register call BEFORE starting pipeline (prevents duplicates)
            self.active_calls[call_sid] = None  # Placeholder until pipeline starts
            
            # 9. Set up function calling if enabled
            if config.enable_function_calling and tools:
                await self._setup_function_calling(assistant, tools, task, api_keys)
            
            # 10. Update active call with actual task
            self.active_calls[call_sid] = task
            
            # 11. Queue greeting message
            await task.queue_frames([
                TTSSpeakFrame(text=config.greeting_message)
            ])
            
            logger.info(f"Starting Pipecat pipeline for call {call_sid}")
            logger.info(f"Pipeline: STT ({config.stt_provider}) → LLM ({config.llm_provider}) → TTS ({config.tts_provider})")
            
            # 12. Run pipeline (blocks until call ends)
            # Pipecat now handles all remaining WebSocket messages (media, dtmf, stop)
            runner = PipelineRunner()
            await runner.run(task)
            
            logger.info(f"Call {call_sid} ended")
            
        except Exception as e:
            logger.exception(f"Error handling call {call_sid}: {e}")
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()
        finally:
            # Cleanup
            if call_sid in self.active_calls:
                del self.active_calls[call_sid]
    
    def _create_agent_config(self, assistant: Assistant) -> VoiceAgentConfig:
        """
        Convert database Assistant model to VoiceAgentConfig.
        
        Args:
            assistant: Database assistant model
            
        Returns:
            VoiceAgentConfig for pipeline creation
        """
        from botelier.voice.agent import AgentStatus
        
        status = AgentStatus.ACTIVE if assistant.is_active else AgentStatus.PAUSED
        
        return VoiceAgentConfig(
            agent_id=str(assistant.id),
            hotel_id=str(assistant.hotel_id),
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
            system_prompt=assistant.system_prompt or "You are a friendly hotel assistant.",
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
    
    async def _setup_function_calling(
        self,
        assistant: Assistant,
        tools: list,
        task,
        api_keys: Dict[str, str]
    ):
        """
        Set up function calling with hotel's configured tools.
        
        Args:
            assistant: Database assistant model
            tools: List of Tool models (already fetched from database)
            task: Pipecat PipelineTask
            api_keys: API keys for external services
        """
        try:
            if not tools:
                logger.debug(f"No active tools found for hotel {assistant.hotel_id}")
                return
            
            # Create function mapper
            mapper = FunctionMapper()
            
            # Get LLM from pipeline
            llm = task.pipeline.processors[3]  # LLM is at index 3 in pipeline
            
            # Register each tool as a function
            for tool in tools:
                try:
                    function_schema, handler = mapper.map_tool_to_function(tool)
                    
                    # Register with LLM
                    llm.register_function(
                        function_name=function_schema["name"],
                        handler=handler,
                    )
                    
                    logger.info(f"Registered tool: {tool.name}")
                except Exception as e:
                    logger.error(f"Failed to register tool {tool.name}: {e}")
            
            logger.info(f"Registered {len(tools)} tools for assistant {assistant.name}")
            
        except Exception as e:
            logger.error(f"Error setting up function calling: {e}")
    
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
