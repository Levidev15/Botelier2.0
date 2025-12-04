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
    - call_context: Stores LLM context for transcript extraction
    - call_start_times: Tracks call start times for duration calculation
    """
    
    def __init__(self):
        """Initialize call handler."""
        self.active_calls = {}
        self.call_mappers: Dict[str, FunctionMapper] = {}
        self.call_contexts: Dict[str, Any] = {}
        self.call_start_times: Dict[str, datetime] = {}
    
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
            
            # 7. Update active call with task and context
            self.active_calls[call_sid] = task
            self.call_contexts[call_sid] = context_aggregator
            self.call_start_times[call_sid] = datetime.utcnow()
            
            # 8. Queue greeting message
            await task.queue_frames([TTSSpeakFrame(text=config.greeting_message)])
            
            logger.info(f"▶️ Pipeline starting: STT ({config.stt_provider}) → LLM ({config.llm_provider}) → TTS ({config.tts_provider})")
            
            # 9. Run pipeline (blocks until call ends)
            # Pipecat handles all remaining WebSocket messages (media, dtmf, stop)
            runner = PipelineRunner()
            await runner.run(task)
            
            logger.info(f"✅ Call {call_sid} ended")
            
            # 10. Capture transcript and save to call log
            await self._save_call_transcript(call_sid, context_aggregator)
            
        except Exception as e:
            logger.exception(f"Error handling call {call_sid}: {e}")
            if websocket.client_state.name == "CONNECTED":
                await websocket.close()
            
            # Still try to save transcript on error
            if call_sid in self.call_contexts:
                try:
                    await self._save_call_transcript(call_sid, self.call_contexts[call_sid])
                except Exception as save_error:
                    logger.error(f"Failed to save transcript on error: {save_error}")
        finally:
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
            # Get or create FunctionMapper for this call session
            # This ensures FlowExecutor state persists across function calls
            if call_sid in self.call_mappers:
                mapper = self.call_mappers[call_sid]
                logger.debug(f"Reusing FunctionMapper for call {call_sid}")
            else:
                mapper = FunctionMapper(call_sid=call_sid)
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
    
    async def _save_call_transcript(self, call_sid: str, context_aggregator: Optional[Any]):
        """
        Save call transcript to database.
        
        Extracts conversation messages from Pipecat's LLM context
        and saves them to the call log using CallLogger service.
        
        Args:
            call_sid: Twilio call SID
            context_aggregator: Pipecat's LLMContextAggregatorPair with conversation context (may be None)
        """
        if not context_aggregator:
            logger.warning(f"No context aggregator available for call {call_sid}, skipping transcript")
            return
            
        db = None
        try:
            transcript = self._extract_transcript(context_aggregator)
            
            if not transcript:
                logger.warning(f"No transcript messages found for call {call_sid}")
                return
            
            duration_seconds = None
            if call_sid in self.call_start_times:
                start_time = self.call_start_times[call_sid]
                duration_seconds = max(0, int((datetime.utcnow() - start_time).total_seconds()))
            
            db = SessionLocal()
            call_logger = CallLogger(db)
            success = call_logger.complete_call(
                call_sid=call_sid,
                transcript=transcript,
                duration_seconds=duration_seconds
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
    
    def _extract_transcript(self, context_aggregator: Any) -> List[Dict[str, str]]:
        """
        Extract conversation messages from Pipecat's context aggregator.
        
        Filters to only user and assistant messages, excluding system prompts
        and tool/function call messages.
        
        Args:
            context_aggregator: Pipecat's LLMContextAggregatorPair
            
        Returns:
            List of transcript entries with role and content
        """
        transcript = []
        
        try:
            messages = None
            
            # LLMContextAggregatorPair has _user and _assistant aggregators
            # Both share the same context, so we can access it through either
            if hasattr(context_aggregator, '_user'):
                user_agg = context_aggregator._user
                if hasattr(user_agg, '_context'):
                    context = user_agg._context
                    if hasattr(context, 'get_messages'):
                        messages = context.get_messages()
                    elif hasattr(context, 'messages'):
                        messages = context.messages
            
            # Fallback: try _assistant aggregator
            if not messages and hasattr(context_aggregator, '_assistant'):
                asst_agg = context_aggregator._assistant
                if hasattr(asst_agg, '_context'):
                    context = asst_agg._context
                    if hasattr(context, 'get_messages'):
                        messages = context.get_messages()
                    elif hasattr(context, 'messages'):
                        messages = context.messages
            
            # Fallback: direct context access (older Pipecat versions)
            if not messages:
                if hasattr(context_aggregator, '_context'):
                    context = context_aggregator._context
                    if hasattr(context, 'get_messages'):
                        messages = context.get_messages()
                    elif hasattr(context, 'messages'):
                        messages = context.messages
            
            if not messages:
                logger.debug(f"No messages found. Aggregator type: {type(context_aggregator)}")
                return transcript
            
            logger.debug(f"Found {len(messages)} raw messages in context")
                
            for msg in messages:
                if not isinstance(msg, dict):
                    # Some messages might be objects, try to convert
                    if hasattr(msg, '__dict__'):
                        msg = msg.__dict__
                    else:
                        continue
                    
                role = msg.get("role")
                
                # Handle both 'content' and 'text' field names
                content = msg.get("content") or msg.get("text")
                
                # Skip non-conversation messages
                if role not in ("user", "assistant"):
                    continue
                    
                # Skip empty content
                if not content:
                    continue
                    
                # Handle content that might be a list (OpenAI format for multimodal)
                if isinstance(content, list):
                    # Extract text from content parts
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            text_parts.append(part)
                    content = " ".join(text_parts)
                
                if not isinstance(content, str) or not content.strip():
                    continue
                    
                # Skip assistant messages that are tool calls (no actual spoken content)
                if role == "assistant" and msg.get("tool_calls"):
                    continue
                    
                transcript.append({
                    "role": role,
                    "content": content.strip()
                })
            
            logger.debug(f"Extracted {len(transcript)} conversation messages")
                
        except Exception as e:
            logger.exception(f"Error extracting transcript: {e}")
            
        return transcript
