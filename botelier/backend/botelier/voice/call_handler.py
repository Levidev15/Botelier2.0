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
from ..services.mcp_client import mcp_client_pool, MCPClient


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
        self.call_mcp_clients: Dict[str, MCPClient] = {}  # call_sid -> MCPClient for MCP tool execution
    
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
                
                # Fetch hotel's Twilio sub-account credentials (for transfers)
                from ..models.hotel import Hotel
                hotel = db.query(Hotel).filter(Hotel.id == assistant.hotel_id).first()
                if hotel:
                    hotel_twilio_sid = hotel.twilio_sub_account_sid
                    hotel_twilio_token = hotel.twilio_sub_auth_token
                    if hotel_twilio_sid:
                        logger.info(f"🏨 Using hotel sub-account: {hotel_twilio_sid[:10]}...")
                
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
                if assistant.mcp_connection_id:
                    from ..models.mcp_connection import MCPConnection, MCPConnectionStatus
                    mcp_conn = db.query(MCPConnection).filter(
                        MCPConnection.id == assistant.mcp_connection_id,
                        MCPConnection.is_active == True
                    ).first()
                    if mcp_conn and mcp_conn.status == MCPConnectionStatus.CONNECTED:
                        mcp_connection_data = {
                            "id": str(mcp_conn.id),
                            "server_url": mcp_conn.server_url,
                            "auth_type": mcp_conn.auth_type.value if mcp_conn.auth_type else "none",
                            "credentials": mcp_conn.get_credentials() if mcp_conn.credentials_encrypted else None,
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
            
            # 2.5. Connect to MCP server if configured
            mcp_client = None
            if mcp_connection_data:
                try:
                    mcp_client = await mcp_client_pool.get_or_create_client(
                        connection_id=mcp_connection_data["id"],
                        server_url=mcp_connection_data["server_url"],
                        auth_type=mcp_connection_data["auth_type"],
                        credentials=mcp_connection_data["credentials"],
                    )
                    self.call_mcp_clients[call_sid] = mcp_client
                    logger.info(f"🔌 MCP client connected for call {call_sid}")
                except Exception as e:
                    logger.error(f"Failed to connect to MCP server: {e}")
                    mcp_client = None
            
            # 3. Build function schemas and handlers (knowledge base ALWAYS available)
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
                mcp_client=mcp_client,
                mcp_enabled_tools=mcp_enabled_tools,
                mcp_connection_data=mcp_connection_data,
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
            
            pipeline, task, llm, context_aggregator, llm_context = VoiceEngineFactory.create_pipeline(
                config=config,
                api_keys=api_keys,
                transport=transport,
                function_schemas=function_schemas if function_schemas else None,
                function_handlers=function_handlers if function_handlers else None,
                on_interruption=on_interruption,
            )
            
            # 7. Update active call with task and context
            self.active_calls[call_sid] = task
            self.call_contexts[call_sid] = llm_context  # Store LLMContext directly for transcript extraction
            self.call_start_times[call_sid] = datetime.utcnow()
            self.interrupted_responses[call_sid] = set()  # Initialize interruption tracking
            
            # 8. Queue greeting message
            await task.queue_frames([TTSSpeakFrame(text=config.greeting_message)])
            
            logger.info(f"▶️ Pipeline starting: STT ({config.stt_provider}) → LLM ({config.llm_provider}) → TTS ({config.tts_provider})")
            
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
            if call_sid in self.interrupted_responses:
                del self.interrupted_responses[call_sid]
            if call_sid in self.call_mcp_clients:
                del self.call_mcp_clients[call_sid]
                logger.debug(f"Cleaned up MCP client reference for call {call_sid}")
    
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
        mcp_client: Optional[MCPClient] = None,
        mcp_enabled_tools: Optional[List[str]] = None,
        mcp_connection_data: Optional[Dict[str, Any]] = None,
    ) -> tuple[list, Dict[str, Any]]:
        """
        Build FunctionSchema objects and handlers for knowledge base and tools.
        
        This follows Pipecat's proper pattern of creating schemas before pipeline initialization.
        
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
            mcp_client: Connected MCP client (if any)
            mcp_enabled_tools: List of enabled MCP tool names
            mcp_connection_data: MCP connection configuration data
            
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
                    account_id=str(assistant.hotel_id),
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
        
        # Add MCP tools if client is connected and tools are enabled
        # Track existing tool names to avoid collisions
        existing_tool_names = set(function_handlers.keys())
        mcp_tool_count = 0
        
        if mcp_client and mcp_connection_data and mcp_enabled_tools:
            discovered_tools = mcp_connection_data.get("discovered_tools", [])
            
            for mcp_tool in discovered_tools:
                tool_name = mcp_tool.get("name")
                if not tool_name or tool_name not in mcp_enabled_tools:
                    continue
                
                # Skip tools that conflict with platform tools (platform tools take priority)
                if tool_name in existing_tool_names:
                    logger.warning(f"⚠️ Skipping MCP tool '{tool_name}': name collision with platform tool")
                    continue
                
                try:
                    # Build function schema from MCP tool definition
                    parameters = mcp_tool.get("parameters", {})
                    tool_schema = FunctionSchema(
                        name=tool_name,
                        description=mcp_tool.get("description", f"Execute {tool_name}"),
                        properties=parameters.get("properties", {}),
                        required=parameters.get("required", []),
                    )
                    function_schemas.append(tool_schema)
                    
                    # Create async handler that executes MCP tool
                    # Use closure to capture mcp_client and tool_name
                    def create_mcp_handler(client: MCPClient, name: str):
                        async def mcp_tool_handler(**kwargs):
                            try:
                                result = await client.execute_tool(name, kwargs)
                                if result.get("success"):
                                    return result.get("result", "Tool executed successfully")
                                else:
                                    return f"Error: {result.get('error', 'Unknown error')}"
                            except Exception as e:
                                logger.error(f"MCP tool {name} execution failed: {e}")
                                return f"Error executing tool: {str(e)}"
                        return mcp_tool_handler
                    
                    function_handlers[tool_name] = create_mcp_handler(mcp_client, tool_name)
                    existing_tool_names.add(tool_name)
                    mcp_tool_count += 1
                    logger.info(f"✅ Built MCP function schema for tool: {tool_name}")
                    
                except Exception as e:
                    logger.error(f"Failed to build MCP tool schema for {tool_name}: {e}")
        
        logger.info(f"📋 Built {len(function_schemas)} function schemas ({len(tools)} platform tools + {mcp_tool_count} MCP tools)")
        
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
    
    async def _save_call_transcript(self, call_sid: str, llm_context: Optional[Any]):
        """
        Save call transcript to database.
        
        Uses tracked transcript (actual spoken content) if available,
        falls back to extracting from LLM context.
        
        Args:
            call_sid: Twilio call SID
            llm_context: Pipecat's LLMContext object with conversation history (may be None)
        """
        db = None
        try:
            # Extract transcript from LLM context
            if llm_context:
                transcript = self._extract_transcript(call_sid, llm_context)
                logger.info(f"Extracted transcript ({len(transcript)} messages) for call {call_sid}")
            else:
                transcript = []
                logger.warning(f"No LLM context available for call {call_sid}")
            
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
    
    def _extract_transcript(self, call_sid: str, llm_context: Any) -> List[Dict[str, str]]:
        """
        Extract conversation messages from Pipecat's LLMContext.
        
        Filters to only user and assistant messages, excluding system prompts
        and tool/function call messages. Marks interrupted responses.
        
        Args:
            call_sid: Twilio call SID (for checking interrupted responses)
            llm_context: Pipecat's LLMContext object (passed directly from create_pipeline)
            
        Returns:
            List of transcript entries with role, content, and interrupted flag
        """
        transcript = []
        interrupted_set = self.interrupted_responses.get(call_sid, set())
        
        try:
            messages = None
            
            # LLMContext provides get_messages() method
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
                
                content = content.strip()
                
                # Check if this assistant message was interrupted
                is_interrupted = False
                if role == "assistant" and interrupted_set:
                    # Check if the first 100 chars match any interrupted message
                    key = content[:100]
                    if key in interrupted_set:
                        is_interrupted = True
                        logger.debug(f"Marking message as interrupted: {key[:50]}...")
                    
                transcript.append({
                    "role": role,
                    "content": content,
                    "interrupted": is_interrupted
                })
            
            logger.debug(f"Extracted {len(transcript)} conversation messages")
                
        except Exception as e:
            logger.exception(f"Error extracting transcript: {e}")
            
        return transcript
    
