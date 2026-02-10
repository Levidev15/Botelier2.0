"""
Function Mapper - Converts database tools to Pipecat function calls.

This module bridges the gap between hotel-configured tools in the database
and the actual Pipecat function calling system during voice conversations.
"""

import os
import httpx
from typing import Dict, Any, List, Callable, TYPE_CHECKING
from loguru import logger

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
        
        # Twilio client for call transfers - use hotel's sub-account credentials
        self.twilio_client = None
        self.twilio_account_sid = twilio_account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.twilio_auth_token = twilio_auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
        
        if self.twilio_account_sid and self.twilio_auth_token:
            self.twilio_client = TwilioClient(self.twilio_account_sid, self.twilio_auth_token)
            logger.info(f"✅ Twilio client initialized for call {call_sid} (Account: {self.twilio_account_sid[:10]}...)")
    
    
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
        phone_number = tool.config.get("phone_number")
        pre_message = tool.config.get("pre_transfer_message", "One moment please...")
        
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
            
            Transfer Flow:
                1. AI says pre-transfer message via Pipecat TTS (uses assistant's configured voice)
                2. Wait for TTS audio to complete streaming to caller
                3. Record transfer in database (so connect-complete won't hang up)
                4. Build TwiML with:
                   - <Stop><Stream> to close the media stream
                   - <Dial> to connect to the transfer target
                   - NOTE: No <Say> tag - the pre-transfer message was already spoken via TTS
                5. Update call via Twilio REST API
                
            The pipeline ends when Twilio closes the WebSocket after receiving
            the update. Twilio executes the TwiML and bridges the caller.
            """
            import asyncio
            
            # Track tool usage
            self.track_tool_usage(tool.name)
            
            # Speak pre-transfer message using the assistant's configured TTS voice
            await params.llm.push_frame(
                TTSSpeakFrame(pre_message)
            )
            
            # Wait for TTS audio to finish streaming to the caller
            # This ensures the caller hears the complete message before transfer
            # Conservative estimate: ~400ms per word (typical speech rate) + 1.5s buffer
            # for TTS generation latency and network streaming
            word_count = len(pre_message.split())
            wait_time = max(2.5, (word_count * 0.4) + 1.5)
            logger.info(f"⏳ Waiting {wait_time:.1f}s for TTS to complete before transfer ({word_count} words)")
            await asyncio.sleep(wait_time)
            
            transfer_success = False
            if self.twilio_client and self.call_sid:
                try:
                    # Record transfer in database BEFORE Twilio redirect
                    from ..database import SessionLocal
                    from ..services.call_logger import CallLogger
                    
                    db = SessionLocal()
                    try:
                        call_logger = CallLogger(db)
                        
                        # Save transcript BEFORE transfer (WebSocket closes after)
                        if self.call_handler and hasattr(self.call_handler, '_save_call_transcript'):
                            try:
                                # Get LLM context if available
                                llm_context = self.call_handler.call_contexts.get(self.call_sid)
                                await self.call_handler._save_call_transcript(self.call_sid, llm_context)
                                logger.info(f"📝 Saved transcript before transfer for call {self.call_sid}")
                            except Exception as e:
                                logger.error(f"Error saving transcript before transfer: {e}")
                        
                        call_logger.record_transfer(
                            call_sid=self.call_sid,
                            transfer_to=phone_number,
                            transfer_type="external"
                        )
                        logger.info(f"📝 Recorded transfer for call {self.call_sid}")
                    finally:
                        db.close()
                    
                    # Build the transfer TwiML
                    # NOTE: We do NOT include <Say> because the pre-transfer message
                    # was already spoken via Pipecat TTS using the assistant's configured voice
                    twiml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<Response>']
                    
                    # 1. Stop the media stream (critical for transfer to work)
                    if self.stream_sid:
                        twiml_parts.append(f'<Stop><Stream name="{self.stream_sid}"/></Stop>')
                    
                    # 2. Build Dial element
                    # Use the caller's original number as callerId (they called us)
                    # Or fall back to the hotel's number (the number that was called)
                    caller_id = self.to_number or os.environ.get("TWILIO_PHONE_NUMBER", "")
                    if caller_id:
                        twiml_parts.append(f'<Dial timeout="30" callerId="{caller_id}">')
                    else:
                        twiml_parts.append('<Dial timeout="30">')
                    
                    # 3. Add the Number element with status callback
                    base_url = os.environ.get("PUBLIC_BASE_URL", "")
                    if base_url:
                        status_callback = f"{base_url}/api/calls/transfer-status"
                        twiml_parts.append(
                            f'<Number statusCallback="{status_callback}" '
                            f'statusCallbackEvent="initiated ringing answered completed">'
                            f'{phone_number}</Number>'
                        )
                    else:
                        twiml_parts.append(f'<Number>{phone_number}</Number>')
                    
                    twiml_parts.append('</Dial>')
                    twiml_parts.append('</Response>')
                    
                    dial_twiml = '\n'.join(twiml_parts)
                    
                    logger.info(f"🔄 Transferring call {self.call_sid} to {phone_number}")
                    logger.debug(f"Transfer TwiML:\n{dial_twiml}")
                    
                    # Update the call with the new TwiML
                    self.twilio_client.calls(self.call_sid).update(twiml=dial_twiml)
                    transfer_success = True
                    logger.info(f"✅ Call {self.call_sid} transfer initiated to {phone_number}")
                    
                except Exception as e:
                    logger.error(f"❌ Twilio transfer failed for call {self.call_sid}: {e}")
            else:
                missing = []
                if not self.twilio_client:
                    missing.append("Twilio client")
                if not self.call_sid:
                    missing.append("call_sid")
                logger.warning(f"⚠️ Cannot transfer call: missing {', '.join(missing)}")
            
            # Return result to LLM
            await params.result_callback({
                "status": "transferring" if transfer_success else "failed",
                "to": phone_number
            })
        
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
                if self.twilio_client and self.call_sid:
                    try:
                        self.twilio_client.calls(self.call_sid).update(
                            twiml=f'<Response><Dial>{target}</Dial></Response>'
                        )
                        logger.info(f"Call transferred to {target}")
                    except Exception as e:
                        logger.error(f"Transfer failed: {e}")
                await params.llm.push_frame(EndFrame())
            
            elif result.get("action") == "end":
                end_msg = result.get("message", "Goodbye!")
                await params.llm.push_frame(TTSSpeakFrame(end_msg))
                await params.llm.push_frame(EndFrame())
            
            # Add current progress to result for LLM context
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
