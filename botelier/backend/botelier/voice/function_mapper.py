"""
Function Mapper - Converts database tools to Pipecat function calls.

This module bridges the gap between hotel-configured tools in the database
and the actual Pipecat function calling system during voice conversations.
"""

import os
import httpx
from typing import Dict, Any, List, Callable
from loguru import logger
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.services.llm_service import FunctionCallParams
from twilio.rest import Client as TwilioClient

from botelier.models.tool import Tool, ToolType
from botelier.flow_executor import FlowExecutor, parse_flow_config


class FunctionMapper:
    """
    Maps database tool configurations to executable Pipecat functions.
    
    Usage:
        # At voice agent initialization
        tools = db.query(Tool).filter(Tool.is_active == "true").all()
        mapper = FunctionMapper(call_sid="CA1234...")
        
        # Register all tools with LLM
        for tool in tools:
            function_schema, handler = mapper.map_tool_to_function(tool)
            llm.register_function(function_schema['name'], handler)
    """
    
    def __init__(self, call_sid: str = None):
        """
        Initialize function mapper with necessary clients.
        
        Args:
            call_sid: Twilio call SID (required for call transfers)
        """
        self.call_sid = call_sid
        
        # Store flow executors by tool name for state persistence across turns
        self._flow_executors: Dict[str, FlowExecutor] = {}
        
        # Twilio client for call transfers
        self.twilio_client = None
        if os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN"):
            self.twilio_client = TwilioClient(
                os.environ.get("TWILIO_ACCOUNT_SID"),
                os.environ.get("TWILIO_AUTH_TOKEN")
            )
    
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
            
            Flow:
                1. AI says pre-transfer message
                2. Transfer call via Twilio REST API
                3. End bot session
            """
            # Tell user what's happening
            await params.llm.push_frame(
                TTSSpeakFrame(pre_message)
            )
            
            # Perform Twilio call transfer
            transfer_success = False
            if self.twilio_client and self.call_sid:
                try:
                    # Use Twilio REST API to update the call with new TwiML that dials the transfer number
                    self.twilio_client.calls(self.call_sid).update(
                        twiml=f'<Response><Dial>{phone_number}</Dial></Response>'
                    )
                    transfer_success = True
                    logger.info(f"✅ Call {self.call_sid} transferred to {phone_number}")
                except Exception as e:
                    logger.error(f"❌ Twilio transfer failed for call {self.call_sid}: {e}")
            else:
                logger.warning(f"⚠️ Cannot transfer call: Twilio client or call_sid missing")
            
            # End bot's session (call will continue with transferred party)
            await params.llm.push_frame(EndFrame())
            
            # Return result to LLM
            await params.result_callback({
                "status": "transferred" if transfer_success else "failed",
                "to": phone_number
            })
        
        return function_schema, transfer_handler
    
    def _map_api_request(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """
        Map API request tool to Pipecat function.
        
        This allows AI to call external APIs during conversations.
        Parameters are extracted from the API config.
        """
        url = tool.config.get("url")
        method = tool.config.get("method", "GET")
        headers = tool.config.get("headers", {})
        parameters = tool.config.get("parameters", {})
        body = tool.config.get("body")
        
        # Build function schema with parameters from config
        function_schema = {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": parameters,
                "required": [k for k, v in parameters.items() if v.get("required", False)]
            }
        }
        
        async def api_handler(params: FunctionCallParams):
            """
            Handler that makes HTTP request to external API.
            
            The LLM extracts parameter values from conversation and passes them here.
            """
            arguments = params.arguments
            
            # Substitute argument values into URL/body
            formatted_url = url.format(**arguments)
            formatted_headers = {k: v.format(**arguments) for k, v in headers.items()}
            
            # Make API request
            async with httpx.AsyncClient() as client:
                try:
                    if method == "GET":
                        response = await client.get(formatted_url, headers=formatted_headers)
                    elif method == "POST":
                        response = await client.post(formatted_url, headers=formatted_headers, json=body)
                    elif method == "PUT":
                        response = await client.put(formatted_url, headers=formatted_headers, json=body)
                    elif method == "DELETE":
                        response = await client.delete(formatted_url, headers=formatted_headers)
                    else:
                        # Unsupported HTTP method
                        await params.result_callback({
                            "error": f"Unsupported HTTP method: {method}",
                            "status": "failed"
                        })
                        return
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    # Return result to LLM so it can continue conversation
                    await params.result_callback(data)
                    
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
        
        # Create flow executor
        executor = FlowExecutor(flow_config)
        
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
            # Parse and create new executor
            flow_config = parse_flow_config(dict(flow_config_dict))
            executor = FlowExecutor(flow_config)
            self._flow_executors[tool_name] = executor
            logger.info(f"Created new FlowExecutor for {tool_name}")
        
        # Get all function schemas from the executor
        function_schemas = executor.get_function_schemas()
        
        # Create handlers for each function - handlers reference the stored executor
        handlers = {}
        for schema in function_schemas:
            func_name = schema["function"]["name"]
            # Create handler that uses the stored executor (closure captures tool_name)
            handlers[func_name] = self._create_flow_function_handler(tool_name, func_name)
        
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
                await params.llm.push_frame(TTSSpeakFrame(result.get("message", "Goodbye!")))
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
