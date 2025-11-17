"""
Function Mapper - Converts database tools to Pipecat function calls.

This module bridges the gap between hotel-configured tools in the database
and the actual Pipecat function calling system during voice conversations.
"""

import os
import httpx
from typing import Dict, Any, List, Callable
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from twilio.rest import Client as TwilioClient

from botelier.models.tool import Tool, ToolType


class FunctionMapper:
    """
    Maps database tool configurations to executable Pipecat functions.
    
    Usage:
        # At voice agent initialization
        tools = db.query(Tool).filter(Tool.is_active == "true").all()
        mapper = FunctionMapper()
        
        # Register all tools with LLM
        for tool in tools:
            function_schema, handler = mapper.map_tool_to_function(tool)
            llm.register_function(function_schema['name'], handler)
    """
    
    def __init__(self):
        """Initialize function mapper with necessary clients."""
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
        
        # Handler function
        async def transfer_handler(function_name, tool_call_id, arguments, llm, context_aggregator, result_callback):
            """
            Handler called when LLM decides to transfer call.
            
            Flow:
                1. AI says pre-transfer message
                2. Transfer call via Twilio/Daily
                3. End bot session
            """
            # Tell user what's happening
            await context_aggregator.push_frame(
                TTSSpeakFrame(pre_message)
            )
            
            # Transfer call
            # Option 1: Twilio REST API (update call with new TwiML)
            if self.twilio_client and hasattr(context_aggregator, 'call_sid'):
                try:
                    call_sid = context_aggregator.call_sid
                    self.twilio_client.calls(call_sid).update(
                        twiml=f'<Response><Dial>{phone_number}</Dial></Response>'
                    )
                except Exception as e:
                    print(f"Twilio transfer error: {e}")
            
            # Option 2: Daily SIP transfer (if using Daily transport)
            elif hasattr(context_aggregator, 'transport') and hasattr(context_aggregator.transport, 'sip_call_transfer'):
                try:
                    await context_aggregator.transport.sip_call_transfer({
                        "to": phone_number
                    })
                except Exception as e:
                    print(f"Daily SIP transfer error: {e}")
            
            # End bot's session
            await context_aggregator.push_frame(EndFrame())
            
            # Return success to LLM
            await result_callback({
                "status": "transferred",
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
        
        async def api_handler(function_name, tool_call_id, arguments, llm, context_aggregator, result_callback):
            """
            Handler that makes HTTP request to external API.
            
            The LLM extracts parameter values from conversation and passes them here.
            """
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
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    # Return result to LLM so it can continue conversation
                    await result_callback(data)
                    
                except httpx.HTTPError as e:
                    await result_callback({
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
        
        async def end_call_handler(function_name, tool_call_id, arguments, llm, context_aggregator, result_callback):
            """End the call gracefully."""
            # Say goodbye
            await context_aggregator.push_frame(
                TTSSpeakFrame(goodbye_message)
            )
            
            # End session
            await context_aggregator.push_frame(EndFrame())
            
            await result_callback({"status": "call_ended"})
        
        return function_schema, end_call_handler
    
    def _map_send_sms(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map send SMS tool to Pipecat function."""
        # Placeholder - implement when SMS integration is ready
        raise NotImplementedError("SMS sending not yet implemented")
    
    def _map_send_email(self, tool: Tool) -> tuple[Dict[str, Any], Callable]:
        """Map send email tool to Pipecat function."""
        # Placeholder - implement when email integration is ready
        raise NotImplementedError("Email sending not yet implemented")


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
