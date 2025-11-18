"""
Call Handler - Orchestrates Pipecat pipeline for incoming Twilio calls.

This module manages the lifecycle of voice call sessions, creating and running
Pipecat pipelines with TwilioFrameSerializer for real-time audio streaming.
"""

import os
import asyncio
from typing import Optional, Dict, Any
from fastapi import WebSocket
from sqlalchemy.orm import Session
from loguru import logger

from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.frames.frames import TTSSpeakFrame

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
    
    def __init__(self, db: Session):
        """
        Initialize call handler with database session.
        
        Args:
            db: SQLAlchemy database session for lookups
        """
        self.db = db
        self.active_calls: Dict[str, asyncio.Task] = {}
    
    async def handle_call(
        self,
        websocket: WebSocket,
        stream_sid: str,
        call_sid: str,
        from_number: str,
        to_number: str,
    ):
        """
        Handle incoming call by creating Pipecat pipeline and streaming audio.
        
        Args:
            websocket: FastAPI WebSocket connection from Twilio
            stream_sid: Twilio Media Stream ID
            call_sid: Twilio Call SID
            from_number: Caller's phone number
            to_number: Botelier phone number that received the call
        
        Flow:
            1. Look up phone number → assistant
            2. Fetch assistant configuration
            3. Create Pipecat pipeline with TwilioFrameSerializer
            4. Stream greeting message
            5. Run pipeline (blocking until call ends)
            6. Cleanup
        """
        try:
            # 1. Look up which assistant is assigned to this phone number
            phone_record = self.db.query(PhoneNumber).filter(
                PhoneNumber.phone_number == to_number
            ).first()
            
            if not phone_record or not phone_record.assistant_id:
                logger.warning(f"No assistant assigned to phone number: {to_number}")
                await websocket.close()
                return
            
            # 2. Fetch assistant configuration
            assistant = self.db.query(Assistant).filter(
                Assistant.id == phone_record.assistant_id
            ).first()
            
            if not assistant:
                logger.error(f"Assistant not found: {phone_record.assistant_id}")
                await websocket.close()
                return
            
            logger.info(f"Handling call for assistant '{assistant.name}' (ID: {assistant.id})")
            
            # 3. Convert database model to VoiceAgentConfig
            config = self._create_agent_config(assistant)
            
            # 4. Get API keys from environment
            api_keys = self._get_api_keys()
            
            # 5. Create TwilioFrameSerializer (Pipecat component - hidden from hotels)
            serializer = TwilioFrameSerializer(
                stream_sid=stream_sid,
                call_sid=call_sid,
                account_sid=os.environ.get("TWILIO_ACCOUNT_SID"),
                auth_token=os.environ.get("TWILIO_AUTH_TOKEN"),
                params=TwilioFrameSerializer.InputParams(
                    auto_hang_up=True,  # Automatically hang up when pipeline ends
                )
            )
            
            # 6. Create WebSocket transport with Twilio serializer
            transport = FastAPIWebsocketTransport(
                websocket=websocket,
                serializer=serializer,
                params=VoiceEngineFactory.create_transport_params(config),
            )
            
            # 7. Create Pipecat pipeline
            pipeline, task = VoiceEngineFactory.create_pipeline(
                config=config,
                api_keys=api_keys,
                transport=transport,
            )
            
            # 8. Set up function calling if enabled
            if config.enable_function_calling:
                await self._setup_function_calling(assistant, task, api_keys)
            
            # 9. Track active call
            self.active_calls[call_sid] = task
            
            # 10. Queue greeting message
            await task.queue_frames([
                TTSSpeakFrame(text=config.greeting_message)
            ])
            
            logger.info(f"Starting pipeline for call {call_sid}")
            
            # 11. Run pipeline (blocks until call ends)
            await task.run()
            
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
        return VoiceAgentConfig(
            agent_id=str(assistant.id),
            hotel_id=str(assistant.hotel_id),
            name=assistant.name,
            description=assistant.description,
            status=assistant.status,
            stt_provider=assistant.stt_provider,
            stt_model=assistant.stt_model,
            stt_language=assistant.stt_language or "en",
            stt_config=assistant.stt_config or {},
            llm_provider=assistant.llm_provider,
            llm_model=assistant.llm_model,
            llm_temperature=assistant.temperature or 0.7,
            llm_max_tokens=assistant.max_tokens or 150,
            llm_config=assistant.llm_config or {},
            tts_provider=assistant.tts_provider,
            tts_voice_id=assistant.tts_voice_id,
            tts_model=assistant.tts_model,
            tts_speed=assistant.tts_speed or 1.0,
            tts_config=assistant.tts_config or {},
            system_prompt=assistant.system_prompt or "You are a friendly hotel assistant.",
            greeting_message=assistant.greeting_message or "Hello! How can I help you today?",
            enable_function_calling=True,  # Always enable for tool support
            enable_interruptions=True,
            enable_vad=True,
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
        task,
        api_keys: Dict[str, str]
    ):
        """
        Set up function calling with hotel's configured tools.
        
        Args:
            assistant: Database assistant model
            task: Pipecat PipelineTask
            api_keys: API keys for external services
        """
        try:
            # Import Tool model
            from ..models.tool import Tool
            
            # Fetch active tools for this hotel
            tools = self.db.query(Tool).filter(
                Tool.hotel_id == assistant.hotel_id,
                Tool.is_active == True
            ).all()
            
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
