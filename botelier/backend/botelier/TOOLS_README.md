# Botelier Tools System

## Overview

The **Tools System** enables hotel managers to configure custom functions their AI voice assistants can perform during conversations—without writing code. Tools are stored in the database and automatically converted to Pipecat function calls at runtime.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Hotel Manager (UI)                          │
│  "Create a tool to transfer calls to front desk: +1-555-0123"  │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Frontend Tools Page  │
                    │  (Next.js + React)    │
                    └───────────┬───────────┘
                                │ HTTP POST /api/tools
                                ▼
                    ┌───────────────────────┐
                    │  FastAPI Backend API  │
                    │  (tools.py)           │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  PostgreSQL Database  │
                    │  tools table          │
                    └───────────┬───────────┘
                                │
                                │ On voice call start
                                ▼
                    ┌───────────────────────┐
                    │  Function Mapper      │
                    │  (function_mapper.py) │
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │  Pipecat Voice Agent  │
                    │  (LLM + Function Call)│
                    └───────────────────────┘
                                │
                                │ During conversation
                                ▼
                            [AI uses tool]
```

## Component Breakdown

### 1. Frontend (`botelier/frontend/app/(dashboard)/dashboard/tools/`)

**Files:**
- `page.tsx` - Main Tools page with list view
- `components/ToolCard.tsx` - Individual tool display cards
- `components/ToolDrawer.tsx` - Slide-out creation panel
- `components/ToolTypeSelector.tsx` - Tool type menu (Vapi-style)
- `components/tool-types/TransferCallForm.tsx` - Form for transfer call configuration

**Key Features:**
- Vapi.ai-style dark theme (`#0a0a0a` background)
- Real-time tool list from backend
- Validation and error handling
- Create, view, and delete tools

### 2. Backend API (`botelier/backend/botelier/api/tools.py`)

**Endpoints:**
```python
GET    /api/tools              # List all tools (with filtering)
GET    /api/tools/{tool_id}    # Get specific tool
POST   /api/tools              # Create new tool
PUT    /api/tools/{tool_id}    # Update tool
DELETE /api/tools/{tool_id}    # Delete tool
```

**Example Request:**
```json
POST /api/tools
{
  "name": "transfer_to_front_desk",
  "description": "Transfer call to hotel front desk when guest needs human assistance",
  "tool_type": "transfer_call",
  "config": {
    "phone_number": "+1-555-0123",
    "pre_transfer_message": "Let me connect you with our front desk team..."
  },
  "is_active": true
}
```

### 3. Database Schema (`botelier/backend/botelier/models/tool.py`)

**Tool Model:**
```python
class Tool(Base):
    id: str                    # UUID
    name: str                  # Function name (e.g., "transfer_to_front_desk")
    description: str           # What it does (helps LLM decide when to use)
    tool_type: ToolType        # transfer_call, api_request, end_call, etc.
    config: JSON               # Tool-specific configuration
    assistant_id: str          # Which assistant owns this tool
    is_active: bool            # Enabled/disabled
    created_at: DateTime
    updated_at: DateTime
```

**Tool Types:**
- `transfer_call` - Transfer to phone number
- `api_request` - Call external APIs
- `end_call` - End conversation gracefully
- `send_sms` - Send text message (future)
- `send_email` - Send email (future)

### 4. Pipecat Integration (`botelier/backend/botelier/voice/function_mapper.py`)

**FunctionMapper Class:**
Converts database tools → Pipecat function schemas + handlers

**Example: Transfer Call Tool**

Database Config:
```json
{
  "name": "transfer_to_front_desk",
  "description": "Transfer call when guest needs human help",
  "config": {
    "phone_number": "+1-555-0123",
    "pre_transfer_message": "Let me connect you..."
  }
}
```

Converted to Pipecat Function:
```python
# Function Schema (tells LLM when to call)
{
  "name": "transfer_to_front_desk",
  "description": "Transfer call when guest needs human help",
  "parameters": {}  # No parameters needed
}

# Handler Function (executes the action)
async def handler():
    1. Say pre-transfer message
    2. Update Twilio call with transfer TwiML
    3. End bot session
```

## How It Works: End-to-End Flow

### Step 1: Hotel Manager Creates Tool (UI)

1. Navigate to `/dashboard/tools`
2. Click "Create Tool"
3. Select "Transfer Call" from sidebar
4. Fill in form:
   - Name: `transfer_to_front_desk`
   - Description: `Transfer call to hotel front desk when guest needs human assistance`
   - Phone: `+1-555-0123`
   - Message: `Let me connect you with our front desk team...`
5. Click "Create Tool"

### Step 2: Backend Stores Tool (API)

```
POST /api/tools
  ↓
Validate input (Pydantic)
  ↓
Save to PostgreSQL
  ↓
Return created tool with ID
```

### Step 3: Voice Agent Loads Tools (Runtime)

When a guest calls:
```python
# In voice agent initialization
from botelier.voice.function_mapper import load_tools_for_assistant

tools = load_tools_for_assistant("assistant-123", db)
mapper = FunctionMapper()

for tool in tools:
    schema, handler = mapper.map_tool_to_function(tool)
    llm.register_function(schema['name'], handler)
```

### Step 4: AI Uses Tool During Conversation

**Guest:** "I need to speak with someone about my reservation."

**LLM thinks:** *This matches "transfer to front desk" description*

**LLM calls:** `transfer_to_front_desk()`

**Handler executes:**
1. AI says: "Let me connect you with our front desk team..."
2. Twilio REST API updates call: `<Response><Dial>+1-555-0123</Dial></Response>`
3. Bot ends session
4. Guest connects to front desk

## Supported Tool Types

### 1. Transfer Call

**Purpose:** Route calls to human agents or other departments

**Configuration:**
```json
{
  "phone_number": "+1-555-0123",
  "pre_transfer_message": "Let me connect you..."
}
```

**When AI Uses It:**
- Guest explicitly asks for human
- AI can't answer question
- Complex situations requiring human judgment

### 2. API Request

**Purpose:** Call external hotel systems (PMS, booking, CRM, etc.)

**Configuration:**
```json
{
  "url": "https://api.opera.com/rsv/v1/hotels/{hotel_id}/availability",
  "method": "GET",
  "headers": {
    "Authorization": "Bearer {api_key}"
  },
  "parameters": {
    "check_in": {"type": "string", "required": true},
    "check_out": {"type": "string", "required": true}
  }
}
```

**When AI Uses It:**
- Guest asks about room availability
- Making/modifying reservations
- Checking guest profiles
- Any hotel system integration

### 3. End Call

**Purpose:** End conversation gracefully

**Configuration:**
```json
{
  "goodbye_message": "Thank you for calling. Have a great day!"
}
```

**When AI Uses It:**
- Conversation naturally concludes
- Guest says goodbye
- Task completed

## Integration with Pipecat

### Key Files

**Voice Engine:** `botelier/backend/botelier/voice/engine.py`
- Initializes Pipecat services (STT, LLM, TTS)
- Creates pipeline

**Function Mapper:** `botelier/backend/botelier/voice/function_mapper.py`
- Converts tools → functions
- Registers with LLM

**Agent:** `botelier/backend/botelier/voice/agent.py`
- Manages voice agent lifecycle
- Loads tools on startup

### Integration Pattern

```python
# In voice agent initialization
def create_voice_agent(assistant_id: str):
    # 1. Load AI providers
    stt = create_stt_service()
    llm = create_llm_service()
    tts = create_tts_service()
    
    # 2. Load tools from database
    tools = load_tools_for_assistant(assistant_id, db)
    mapper = FunctionMapper()
    
    # 3. Register tools with LLM
    for tool in tools:
        schema, handler = mapper.map_tool_to_function(tool)
        llm.register_function(schema['name'], handler)
    
    # 4. Create pipeline
    pipeline = create_pipeline(stt, llm, tts)
    
    return VoiceAgent(pipeline)
```

## Testing

### Test Backend API

```bash
# Create a transfer call tool
curl -X POST http://localhost:8000/api/tools \
  -H "Content-Type: application/json" \
  -d '{
    "name": "transfer_to_front_desk",
    "description": "Transfer call to hotel front desk",
    "tool_type": "transfer_call",
    "config": {
      "phone_number": "+1-555-0123",
      "pre_transfer_message": "Let me connect you..."
    },
    "is_active": true
  }'

# List all tools
curl http://localhost:8000/api/tools | python -m json.tool

# Delete a tool
curl -X DELETE http://localhost:8000/api/tools/{tool_id}
```

### Test Frontend

1. Navigate to `http://localhost:5000/dashboard/tools`
2. Click "Create Tool"
3. Select "Transfer Call"
4. Fill in form
5. Verify tool appears in list
6. Test delete functionality

### Test Pipecat Integration

```python
# In test environment
from botelier.voice.function_mapper import FunctionMapper
from botelier.models.tool import Tool, ToolType

# Create test tool
tool = Tool(
    id="test-123",
    name="test_transfer",
    description="Test transfer function",
    tool_type=ToolType.TRANSFER_CALL,
    config={"phone_number": "+1-555-0123"}
)

# Map to Pipecat function
mapper = FunctionMapper()
schema, handler = mapper.map_tool_to_function(tool)

# Verify schema
assert schema['name'] == 'test_transfer'
assert schema['description'] == 'Test transfer function'
```

## Future Enhancements

### Phase 2: Integration-Based Tools

Instead of manual API configuration, provide pre-built templates:

```
Tool Type Selector:
├─ Transfer Call
├─ API Request (Manual)
├─ Opera PMS Request     ← Auto-configured
├─ Mews PMS Request      ← Auto-configured
├─ Cloudbeds Request     ← Auto-configured
└─ End Call
```

**Benefits:**
- Hotel manager picks "Opera PMS Request" → "Check Availability"
- Pre-fills endpoint, parameters, auth
- No manual URL/header configuration

### Phase 3: Advanced Features

- **Conditional Logic:** "Transfer only if after 5pm"
- **Multi-step Workflows:** "Check room → If available → Book → Send confirmation"
- **Tool Testing:** Sandbox mode to test tools without real calls
- **Analytics:** Track which tools are used most frequently
- **A/B Testing:** Test different tool configurations

## Security Considerations

### API Key Management

- **Current:** Stored in tool config JSON (encrypted in database)
- **Future:** Integrate with Replit Secrets for automatic encryption/rotation
- **Best Practice:** Never expose API keys in logs or error messages

### Authorization

- **Multi-tenancy:** Tools are scoped to `assistant_id`
- **User Access:** Only authorized hotel staff can create/modify tools
- **Rate Limiting:** Prevent abuse of external API calls

### Validation

- **Frontend:** Client-side validation (phone numbers, URLs)
- **Backend:** Pydantic schemas enforce strict validation
- **Runtime:** Error handling prevents crashes from malformed configs

## Troubleshooting

### Tool Not Appearing in UI

1. Check backend logs: `tail -f /tmp/logs/botelier-backend_*.log`
2. Verify database connection: `curl http://localhost:8000/api/health`
3. Check tool creation response for errors

### AI Not Using Tool

1. Verify tool is active: `is_active: true`
2. Check description is clear (LLM uses this to decide)
3. Review conversation logs to see LLM's reasoning

### Transfer Not Working

1. Verify Twilio credentials are set
2. Check phone number format (E.164: +1-555-0123)
3. Ensure `call_sid` is available in context

## Contact & Support

For questions or issues:
- Documentation: `/docs/tools`
- Backend API Docs: `http://localhost:8000/api/docs`
- GitHub Issues: [link]

---

**Built with:** FastAPI, PostgreSQL, Pipecat, Next.js
**Version:** 0.1.0
**Last Updated:** November 2025
