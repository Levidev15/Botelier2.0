# Botelier - Hotel Voice AI SaaS Platform

## Overview

**Botelier** is a multi-tenant SaaS platform that enables hotels to create and manage voice AI agents for guest services. Built on top of the Pipecat framework (hidden as an implementation detail), Botelier provides a clean, hotel-focused interface for configuring conversational AI without exposing framework internals.

## Project Structure

```
.
├── botelier/                    # Main SaaS Application
│   ├── frontend/               # Next.js hotel dashboard (to be built)
│   ├── backend/                # FastAPI Python server
│   │   └── botelier/          # Main application package
│   │       ├── api/           # REST API endpoints (to be built)
│   │       ├── models/        # Database models (to be built)
│   │       ├── voice/         # ✅ Voice AI engine (Pipecat wrapper)
│   │       ├── auth/          # Authentication (to be built)
│   │       ├── integrations/  # Hotel systems (to be built)
│   │       └── config/        # ✅ Provider configurations
│   └── database/              # Database schemas (to be built)
│
├── src/pipecat/               # Pipecat framework (dependency)
├── examples/quickstart/       # Original Pipecat examples
└── replit.md                  # This file

```

## Architecture Principles

### 1. Clean Branding
- **95% of code is "Botelier"** - Developers work with Botelier interfaces
- **Pipecat is a dependency** - Like using React or Django
- **No framework exposure** - Hotels never see Pipecat internals

### 2. Example: How Hotels Create Agents

**What developers see (Botelier API):**
```python
from botelier.voice import VoiceAgent, VoiceAgentConfig

agent = VoiceAgent(VoiceAgentConfig(
    name="Concierge",
    stt_provider="deepgram",
    llm_provider="openai",
    tts_provider="cartesia",
    system_prompt="You are a helpful hotel concierge.",
))
```

**What happens internally (hidden):**
```python
# botelier/backend/botelier/voice/engine.py
# This file uses Pipecat - hotels never see this
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
# ... implementation details hidden
```

## Current Status

### ✅ Completed

**Project Foundation:**
- Created `botelier/` directory structure
- Built voice AI engine wrapper (`botelier/backend/botelier/voice/`)
  - `agent.py` - Clean VoiceAgent interface
  - `engine.py` - Pipecat integration (hidden)
  - `orchestrator.py` - Multi-agent session management
  - `session.py` - Call session tracking
- Configured all AI providers (`config/providers.py`)
  - 14+ STT providers (Deepgram, OpenAI, Azure, etc.)
  - 14+ LLM providers (OpenAI, Anthropic, Gemini, etc.)
  - 15+ TTS providers (Cartesia, ElevenLabs, Google, etc.)
- Comprehensive provider metadata (models, voices, capabilities)

**Tools System (Function Calling):**
- PostgreSQL database schema for tools (`models/tool.py`)
  - Tool types: Transfer Call, API Request, End Call, SMS, Email
  - JSON config storage for tool-specific parameters
- FastAPI CRUD endpoints (`api/tools.py`)
  - Create, read, update, delete tools
  - Filter by assistant and tool type
- React frontend Tools page (`frontend/app/dashboard/tools/`)
  - Vapi.ai-style dark theme interface
  - Tool drawer with type selector
  - Transfer Call form with validation
  - Tool cards with edit/delete functionality
- Pipecat integration layer (`voice/function_mapper.py`)
  - Converts database tools → LLM function schemas
  - Handles call transfers via Twilio/Daily
  - Maps API requests to external systems
- Comprehensive documentation (`TOOLS_README.md`)

**Phone Numbers System (Twilio Integration):**
- Database models (`models/hotel.py`, `models/phone_number.py`)
  - Hotel model with Twilio sub-account fields
  - PhoneNumber model with Twilio SID, capabilities, assignment tracking
- Twilio integration layer (`integrations/twilio/`)
  - `client.py` - Twilio API wrapper with sub-account support
  - `sub_accounts.py` - Sub-account creation/management for multi-tenant isolation
  - `phone_numbers.py` - Search, purchase, configure, release phone numbers
- FastAPI CRUD endpoints (`api/phone_numbers.py`)
  - Search available numbers by area code
  - Purchase numbers and assign to hotel sub-accounts
  - List, assign to assistants, and release numbers
  - All endpoints include proper error handling and validation
- React frontend Phone Numbers page (`frontend/app/dashboard/phone-numbers/`)
  - Vapi.ai-style dark theme matching Tools page
  - Empty state with clear call-to-action
  - AddNumberDrawer with 3 tabs: Buy Botelier, Import Twilio, BYOT SIP
  - BuyBotelierForm with area code search functionality
  - PhoneNumberCard showing number details and assignment status
- Architecture: Each hotel gets isolated Twilio sub-account for billing separation

**Knowledge Bases System (RAG Integration):**
- Database models (`models/knowledge_base.py`, `models/knowledge_document.py`, `models/assistant_knowledge_base.py`)
  - KnowledgeBase model with name, description, document count
  - KnowledgeDocument model with filename, content, character count
  - AssistantKnowledgeBase junction table for future assignment feature
- FastAPI CRUD endpoints (`api/knowledge_bases.py`)
  - Create, read, update, delete knowledge bases
  - Upload, list, delete documents within knowledge bases
  - 50k character limit per document for safety
  - Proper error handling and validation
- RAG query handler (`voice/knowledge_handler.py`)
  - Integrates with Pipecat's function calling pattern
  - Uses OpenAI LLM (gpt-4o-mini) for RAG queries
  - Loads all hotel knowledge bases into context
  - 50k character safety limit on concatenated content
  - Truncation with warnings if content exceeds limit
- React frontend Knowledge Bases page (`frontend/app/dashboard/knowledge-bases/`)
  - Vapi.ai-style dark theme matching existing pages
  - Empty state with clear call-to-action
  - AddKnowledgeBaseDrawer with two tabs: Basic Info and Documents
  - Document upload with filename and text content
  - Document list with character counts and delete functionality
  - Knowledge base cards showing document counts
- Architecture: Each hotel can create multiple knowledge bases with text documents for RAG

### 🚧 Next Steps

**Complete Phone Numbers Integration:**
- Set up Replit Twilio connector for main account credentials
- Create test hotel with Twilio sub-account
- Test area code search → purchase → assign flow
- Build Twilio webhook handler for incoming calls
- Implement WebSocket endpoint with TwilioFrameSerializer

**Voice Agent Integration:**
- Add tool registration to voice agent startup
- Test end-to-end: UI → Database → Pipecat → Live call
- Build API Request and End Call tool types
- Add integration-based tools (Opera PMS, Mews, Cloudbeds)

## AI Provider Support

### Speech-to-Text (STT)
Deepgram, OpenAI Whisper, AssemblyAI, Azure, Google, Groq, AWS Transcribe, Gladia, ElevenLabs, Riva, Soniox, Speechmatics, Cartesia, Sarvam

### Language Models (LLM)
OpenAI (GPT-4o, GPT-4-turbo), Anthropic (Claude), Google Gemini, Azure OpenAI, AWS Bedrock, Groq, Mistral, Together, DeepSeek, Perplexity, OpenRouter, Ollama, Fireworks, Cerebras

### Text-to-Speech (TTS)
Cartesia, ElevenLabs, OpenAI, Azure, Google, AWS Polly, Deepgram, PlayHT, LMNT, Rime, Piper, Neuphonic, Speechmatics, Riva, Sarvam

## Configurable Parameters

Hotels can customize:
- **Voice Providers:** Choose any STT/LLM/TTS combination
- **Models:** Select specific models per provider
- **Voices:** Pick from dozens of voice options
- **Languages:** Multi-language support
- **Behavior:** Temperature, speed, emotions, interruptions
- **Prompts:** System prompts and greetings
- **Functions:** Enable hotel system integrations (PMS, booking, concierge)

## Development Notes

### Pipecat Framework Location
- `src/pipecat/` contains the original Pipecat framework
- `examples/quickstart/` contains the original demo bot
- **Do not modify these** - they're the dependency

### Botelier Application Location
- `botelier/` contains YOUR SaaS application
- This is where all development happens
- Import Pipecat like any library: `from pipecat.services...`

### Adding New AI Providers

1. Add enum to `botelier/backend/botelier/config/providers.py`
2. Add configuration with models/voices
3. Implement factory in `botelier/backend/botelier/voice/engine.py`
4. Provider automatically appears in dashboard

### Updating Pipecat

```bash
pip install --upgrade pipecat-ai
# That's it! Wrapper isolates changes
```

## Original Pipecat Setup (Reference)

The quickstart bot is still configured if you need to reference it:

**API Keys Required (for quickstart example):**
- `DEEPGRAM_API_KEY`
- `OPENAI_API_KEY`
- `CARTESIA_API_KEY`

**Workflow:** `pipecat-bot` runs on port 5000

## Resources

- [Botelier Architecture](botelier/README.md)
- [Pipecat Documentation](https://docs.pipecat.ai)
- [Pipecat GitHub](https://github.com/pipecat-ai/pipecat)

## Recent Changes

- **2024-11-17:** Knowledge Bases System (RAG Integration)
  - Built complete RAG system for hotel knowledge bases
  - Created database models for knowledge bases and documents
  - Implemented API endpoints for CRUD operations
  - Built RAG query handler using Pipecat function calling + OpenAI
  - Created frontend UI with Vapi.ai dark theme
  - Added 50k character safety limits to prevent unbounded concatenation
  - Fixed critical API validation bug (hotel_id on updates)
  - Navigation link added to sidebar

- **2024-11-15:** Created Botelier SaaS architecture
  - Set up clean project structure separating SaaS from framework
  - Built voice AI engine wrapper hiding Pipecat as implementation detail
  - Configured 40+ AI providers with full metadata
  - Designed multi-tenant architecture for hotel dashboard

- **2024-11-14:** Initial Pipecat setup
  - Installed Pipecat framework and dependencies
  - Configured quickstart bot workflow

## User Preferences

- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend
