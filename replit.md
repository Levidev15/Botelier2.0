# Botelier - Hotel Voice AI SaaS Platform

## Overview
Botelier is a multi-tenant SaaS platform designed to empower hotels with custom voice AI agents for guest services. It provides a hotel-focused interface for configuring conversational AI, abstracting away underlying framework complexities. The platform aims to streamline hotel operations, enhance guest experiences, and provide a robust, scalable solution for AI-powered guest interaction.

## Recent Changes (November 20, 2025)
**Rollback Recovery & Dependency Upgrade** - Fixed backend crash after rollback by upgrading Pipecat and dependencies:
- Upgraded Pipecat from 0.0.64 → 0.0.95 to match code structure
- Upgraded FastAPI 0.104.1 → 0.121.3 for Pipecat compatibility
- Upgraded Pydantic 2.5.2 → 2.12.4 (required by Pipecat >=2.10.6)
- Fixed import paths: `pipecat.transports.websocket.fastapi` (newer structure)
- All assistants, tools, and knowledge base entries successfully restored and visible
- Backend running successfully with proper module dependencies

**Previous Changes (November 19, 2025)**
**Twilio Call Transfer Implemented** - Full end-to-end call transfer functionality:
- CallHandler now passes `call_sid` to FunctionMapper during initialization
- Transfer handler uses Twilio REST API to update active call with new TwiML: `<Response><Dial>{phone_number}</Dial></Response>`
- Flow: Pre-transfer message → Twilio API call → EndFrame (terminates bot) → Structured result callback
- Error handling and logging for missing credentials or failed transfers
- Call continues with transferred party after bot session ends

**Codebase Cleanup** - Removed unused files and improved organization:
- Deleted unused abstraction layers: `orchestrator.py`, `session.py` (not referenced anywhere)
- Removed empty `auth/` directory (authentication planned for future)
- Updated `voice/__init__.py` to export only used classes: VoiceAgent, CallHandler
- Fixed LSP errors: None-safe OpenAI response handling, HTTP method validation

**Knowledge Base Architecture** - Current implementation uses "context stuffing" rather than vector RAG:
- Loads all active Q&A entries (up to 50k chars) from database
- Passes to separate OpenAI call (gpt-4o-mini) with RAG prompt
- Works well for <100 FAQ entries; would need vector embeddings (Pinecone/Qdrant) for larger scale

## User Preferences
- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend

## System Architecture
Botelier is built with a clean architectural separation, where the core SaaS application (`botelier/`) interacts with the Pipecat framework (`src/pipecat/`) as a hidden dependency.

### UI/UX Decisions
The frontend, built with Next.js, follows a Vapi.ai-style dark theme for consistency across different dashboard pages (Tools, Phone Numbers, Knowledge Bases). Key UI components include:
- **Assistant Configuration Pages:** Unified 4-tab layout (Info → Language Model → Voice → Transcriber) with auto-tab-switching on scroll via IntersectionObserver. Both create and edit pages share identical components for consistent UX.
- **Reusable Form Components:** FormField, ProviderSelector (with dynamic provider loading from API), FormSection, TabNavigation, and SaveBar with smart dirty form detection.
- **Sticky Headers:** Persistent header and tab navigation for easy access while scrolling through long forms.
- **Dual-view Systems:** Table/Grid views with sortable, searchable, and filterable data.
- **Bulk Selection:** Action capabilities for managing multiple entries simultaneously.

### Technical Implementations & Feature Specifications
- **Voice AI Engine:** A wrapper around Pipecat provides a clean `VoiceAgent` interface, allowing hotels to configure STT, LLM, and TTS providers, system prompts, and behaviors without exposing Pipecat internals.
- **Call Handling Infrastructure (Twilio Media Streams):**
    - **Architecture:** Twilio connects DIRECTLY to FastAPI backend (port 3001), bypassing Next.js frontend entirely for calls
        - HTTP API calls (dashboard): Frontend (5000) → Next.js proxy → Backend (3001)
        - WebSocket calls (Twilio): Twilio → Backend (3001) DIRECTLY (no proxy)
    - HTTP webhook endpoint (`/api/calls/incoming`) returns TwiML with `<Connect><Stream>` pointing to backend WebSocket URL (port 3001)
    - WebSocket endpoint (`/api/ws/call`) uses standard Pipecat pattern:
        - Accepts WebSocket connection from Twilio
        - Receives Twilio's 'start' event to extract `stream_sid` and `call_sid` (required by TwilioFrameSerializer)
        - Looks up assistant by phone number from TwiML parameters
        - Creates Pipecat pipeline with TwilioFrameSerializer initialized with stream_sid/call_sid
        - Delegates ALL subsequent WebSocket messages (media, stop, etc.) to Pipecat's FastAPIWebsocketTransport
    - CallHandler class orchestrates full Pipecat pipeline: STT → LLM → TTS with real-time bidirectional audio
    - Phone number purchase automatically configures voice_url webhook to incoming call endpoint
    - Lazy provider imports prevent startup failures from missing optional dependencies (Anthropic, Cartesia, ElevenLabs, VAD)
    - **Why direct connection?** Bypassing Next.js proxy eliminates duplicate WebSocket connections and follows Pipecat's recommended pattern
- **Tools System (Function Calling):**
    - PostgreSQL schema with `hotel_id` scoping for various tool types (Transfer Call, API Request, End Call, SMS, Email) with JSON configuration.
    - FastAPI CRUD endpoints with hotel_id filtering for multi-tenant isolation (all read/write operations require hotel_id parameter).
    - Referential integrity validation: create endpoint validates hotel existence and assistant/hotel ownership before persistence.
    - Call handler queries tools by `hotel_id` and `is_active="true"` (string comparison matching database VARCHAR storage).
    - **Known limitation**: Without authentication, hotel_id comes from request parameters (trusted input). TODO: Derive from auth context once authentication is implemented.
    - Pipecat integration converts database tools into LLM function schemas and handles call transfers (via Twilio/Daily) and API requests.
- **Phone Numbers System (Twilio Integration):**
    - Database models for Hotels (with Twilio sub-account fields) and Phone Numbers (Twilio SID, capabilities).
    - Twilio integration layer for sub-account management, number search, purchase, configuration, and release.
    - FastAPI CRUD endpoints for phone number operations, including area code search and assignment to hotel sub-accounts.
    - Multi-tenant architecture with isolated Twilio sub-accounts per hotel for billing separation.
- **Knowledge Base System (Simplified Q&A with RAG):**
    - Flat database structure where `KnowledgeEntry` belongs directly to hotels, with fields for question, answer, category (free-text tags), and expiration date.
    - FastAPI CRUD endpoints for Q&A entries, supporting CSV bulk import and auto-filtering of expired entries.
    - RAG query handler integrated with Pipecat, using OpenAI LLM (gpt-4o-mini) to fetch active Q&A entries by `hotel_id` and format them for optimal RAG performance, with a 50k character safety limit.

### System Design Choices
- **Clean Branding:** The platform prioritizes "Botelier" branding, treating Pipecat as a backend dependency, similar to how a developer uses a framework like React or Django.
- **Provider Configuration:** A flexible configuration system allows hotels to choose from a wide range of AI providers (STT, LLM, TTS), specific models, voices, languages, and behavioral parameters (temperature, speed, emotions, prompts).
- **Multi-tenancy with Complete Isolation:** Every hotel resource is strictly isolated:
    - Database queries filter by `hotel_id` for assistants, phone numbers, tools, and knowledge entries
    - Phone number assignment endpoint validates that assistant.hotel_id matches phone_number.hotel_id (403 error on mismatch)
    - Tools and knowledge base RAG queries automatically scope to the calling assistant's hotel_id
    - Twilio sub-accounts provide billing and resource separation per hotel
    - **Security guarantee**: Hotel A cannot access, modify, or trigger Hotel B's resources under any circumstances

## External Dependencies

### AI Providers
- **Speech-to-Text (STT):** Deepgram, OpenAI Whisper, AssemblyAI, Azure, Google, Groq, AWS Transcribe, Gladia, ElevenLabs, Riva, Soniox, Speechmatics, Cartesia, Sarvam.
- **Language Models (LLM):** OpenAI (GPT-4o, GPT-4-turbo), Anthropic (Claude), Google Gemini, Azure OpenAI, AWS Bedrock, Groq, Mistral, Together, DeepSeek, Perplexity, OpenRouter, Ollama, Fireworks, Cerebras.
- **Text-to-Speech (TTS):** Cartesia, ElevenLabs, OpenAI, Azure, Google, AWS Polly, Deepgram, PlayHT, LMNT, Rime, Piper, Neuphonic, Speechmatics, Riva, Sarvam.

### Databases
- PostgreSQL

### Third-Party Integrations
- **Twilio:** For phone number management, call handling, and sub-account isolation.
- **Pipecat Framework:** Underlying framework for voice AI engine.
- **Daily:** For call transfers (via Pipecat integration).

### Potential Future Integrations
- Opera PMS
- Mews
- Cloudbeds

## Pipecat Features Available for Frontend Exposure

The following Pipecat built-in features are available and could be exposed in the Botelier dashboard for hotel configuration:

### 1. Interruption Handling
- **MinWordsInterruptionStrategy**: Allow interruptions only after user speaks X words (prevents accidental interruptions)
- **Allow/Disallow Interruptions**: Global flag to enable/disable user interruptions during bot speech
- **Use Case**: Hotels can configure whether guests can interrupt the AI or must wait for it to finish speaking

### 2. Voice Activity Detection (VAD) Configuration
- **VADParams**: 
  - `confidence` (0.0-1.0): Minimum confidence threshold for detecting speech (default: 0.7)
  - `start_secs`: Duration to wait before confirming voice start (default: 0.2s)
  - `stop_secs`: Duration to wait before confirming voice stop (default: 0.8s)
  - `min_volume` (0.0-1.0): Minimum audio volume threshold (default: 0.6)
- **VAD Analyzers**: Silero, AIC, WebRTC (different algorithms for speech detection)
- **Use Case**: Fine-tune sensitivity to prevent cutting off guests mid-sentence or being too slow to respond

### 3. Turn Detection & Conversation Flow
- **SmartTurnParams**: Analyzes when user has finished speaking (beyond basic VAD)
- **Turn-based Audio Events**: Capture user and bot turns separately for analytics
- **Use Case**: Better conversation flow, especially for guests who pause while thinking

### 4. STT Mute Strategies
Control when Speech-to-Text should be muted to prevent unwanted processing:
- **FIRST_SPEECH**: Mute STT until first bot speech (prevents pre-conversation noise)
- **MUTE_UNTIL_FIRST_BOT_COMPLETE**: Mute until bot finishes first complete response
- **FUNCTION_CALL**: Mute during function execution (prevents interrupting booking/transfer operations)
- **ALWAYS**: Always mute STT when bot is speaking (strict turn-taking)
- **CUSTOM**: Hotel-defined custom logic
- **Use Case**: Prevent guests from accidentally interrupting critical operations like payment processing or room booking

### 5. User Idle Detection & Timeout Handling
- **UserIdleProcessor**: Monitors inactivity and triggers callbacks after timeout
- **Configurable Parameters**:
  - `timeout`: Seconds before considering user idle
  - `callback`: Action to take (e.g., "Are you still there?", hang up, transfer to human)
  - Retry logic with count tracking
- **Use Case**: Detect silent guests and prompt them, or gracefully end inactive calls to save costs

### 6. LLM Context Management (Partially Implemented)
- **Message History**: Already exposed via conversation logs
- **Tool Choices**: `auto`, `required`, `none`, or specify exact tool
- **Context Updates**: Runtime updates to system prompts, tools, or instructions
- **Use Case**: Dynamic conversation context based on guest requests or PMS data

### 7. Audio Processing Configuration
- **Sample Rate**: Configurable audio quality (8kHz phone quality vs 16kHz/48kHz high quality)
- **Channels**: Mono vs stereo processing
- **Buffer Settings**: Latency vs reliability tradeoffs
- **Use Case**: Balance call quality with bandwidth/cost constraints

### Priority Features to Implement
Based on hotel use cases, these should be prioritized for frontend exposure:

**High Priority:**
1. **User Idle Timeout** - Critical for cost management and guest experience
2. **STT Mute During Function Calls** - Prevent interrupting bookings/payments
3. **VAD Sensitivity** - Fine-tune for different accents and speaking styles

**Medium Priority:**
4. **Interruption Strategy** - Hotel preference for conversation style (formal vs casual)
5. **Turn Detection Params** - Better handling of thoughtful pauses

**Low Priority (Advanced):**
6. **Audio Buffer Settings** - Most hotels won't need to adjust
7. **Custom VAD Analyzers** - Only for specialized requirements