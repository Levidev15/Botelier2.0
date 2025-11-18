# Botelier - Hotel Voice AI SaaS Platform

## Overview
Botelier is a multi-tenant SaaS platform designed to empower hotels with custom voice AI agents for guest services. It provides a hotel-focused interface for configuring conversational AI, abstracting away underlying framework complexities. The platform aims to streamline hotel operations, enhance guest experiences, and provide a robust, scalable solution for AI-powered guest interaction.

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
    - HTTP webhook endpoint (`/api/calls/incoming`) returns TwiML with `<Connect><Stream>` pointing to WebSocket URL with phone numbers as query params
    - WebSocket endpoint (`/ws/call`) uses hybrid Pipecat integration:
        - Extracts phone numbers from URL query params to look up assistant BEFORE accepting WebSocket
        - Manually accepts WebSocket and receives Twilio's 'start' event to extract `stream_sid` and `call_sid` (required by TwilioFrameSerializer constructor)
        - Creates Pipecat pipeline with TwilioFrameSerializer initialized with stream_sid/call_sid
        - Delegates ALL subsequent WebSocket messages (media, stop, etc.) to Pipecat's FastAPIWebsocketTransport
        - **Design rationale**: Pipecat's TwilioFrameSerializer requires stream_sid upfront, but we implement the WebSocket endpoint that receives it, necessitating manual bootstrap of the first event
    - CallHandler class orchestrates full Pipecat pipeline: STT → LLM → TTS with real-time bidirectional audio
    - Phone number purchase automatically configures voice_url webhook to incoming call endpoint
    - Lazy provider imports prevent startup failures from missing optional dependencies (Anthropic, Cartesia, ElevenLabs, VAD)
    - Active call sessions tracked with concurrent WebSocket handling per call
- **Tools System (Function Calling):**
    - PostgreSQL schema for various tool types (Transfer Call, API Request, End Call, SMS, Email) with JSON configuration.
    - FastAPI CRUD endpoints for managing tools.
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