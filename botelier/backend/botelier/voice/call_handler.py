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
        self.active_calls = {}
    
    async def handle_call(self, websocket: WebSocket, to_number: str, stream_sid: str, call_sid: str, db: Session):
        """
        Handle incoming call using Pipecat - Official Pattern.
        
        Args:
            websocket: FastAPI WebSocket (ALREADY ACCEPTED, 'start' event already read)
            to_number: Phone number being called
            stream_sid: Twilio stream SID (from 'start' event)
            call_sid: Twilio call SID (from 'start' event)
            db: Database session
        
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
            
            # 2. Get API keys
            api_keys = self._get_api_keys()
            
            # 3. Build function schemas and handlers (knowledge base ALWAYS available)
            function_schemas, function_handlers = self._build_function_schemas_and_handlers(
                assistant, tools, api_keys, call_sid
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
            pipeline, task, llm, context_aggregator = VoiceEngineFactory.create_pipeline(
                config=config,
                api_keys=api_keys,
                transport=transport,
                function_schemas=function_schemas if function_schemas else None,
                function_handlers=function_handlers if function_handlers else None,
            )
            
            # 7. Update active call with task
            self.active_calls[call_sid] = task
            
            # 8. Queue greeting message
            await task.queue_frames([TTSSpeakFrame(text=config.greeting_message)])
            
            logger.info(f"▶️ Pipeline starting: STT ({config.stt_provider}) → LLM ({config.llm_provider}) → TTS ({config.tts_provider})")
            
            # 9. Run pipeline (blocks until call ends)
            # Pipecat handles all remaining WebSocket messages (media, dtmf, stop)
            runner = PipelineRunner()
            await runner.run(task)
            
            logger.info(f"✅ Call {call_sid} ended")
            
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
    
    def _build_function_schemas_and_handlers(
        self,
        assistant: Assistant,
        tools: list,
        api_keys: Dict[str, str],
        call_sid: str
    ) -> tuple[list, Dict[str, Any]]:
        """
        Build FunctionSchema objects and handlers for knowledge base and tools.
        
        This follows Pipecat's proper pattern of creating schemas before pipeline initialization.
        
        Args:
            assistant: Database assistant model
            tools: List of Tool models (already fetched from database)
            api_keys: API keys for external services
            call_sid: Twilio call SID (for call transfers)
            
        Returns:
            Tuple of (function_schemas, function_handlers)
        """
        from pipecat.adapters.schemas.function_schema import FunctionSchema
        from botelier.voice.knowledge_handler import query_hotel_knowledge
        
        function_schemas = []
        function_handlers = {}
        
        # 1. Add knowledge base function (ALWAYS available, even with zero custom tools)
        knowledge_schema = FunctionSchema(
            name="query_hotel_knowledge",
            description="Query the hotel's knowledge base to answer guest questions about the hotel, amenities, policies, services, and local information. Use this when guests ask questions about the hotel.",
            properties={
                "question": {
                    "type": "string",
                    "description": "The guest's question to look up in the knowledge base",
                },
            },
            required=["question"],
        )
        function_schemas.append(knowledge_schema)
        
        async def knowledge_handler_wrapper(params):
            """Wrapper to inject hotel_id into knowledge base queries."""
            params.arguments["hotel_id"] = str(assistant.hotel_id)
            await query_hotel_knowledge(params)
        
        function_handlers["query_hotel_knowledge"] = knowledge_handler_wrapper
        logger.info(f"✅ Built knowledge base function schema for hotel {assistant.hotel_id}")
        
        # 2. Add database tools
        if tools:
            mapper = FunctionMapper(call_sid=call_sid)
            
            for tool in tools:
                try:
                    function_schema_dict, handler = mapper.map_tool_to_function(tool)
                    
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
        
        logger.info(f"📋 Built {len(function_schemas)} function schemas (1 knowledge base + {len(tools)} tools)")
        
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
