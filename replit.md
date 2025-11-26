# Botelier - Hotel Voice AI SaaS Platform

## Overview
Botelier is a multi-tenant SaaS platform providing hotels with custom voice AI agents for guest services. It offers a hotel-centric interface for configuring conversational AI, abstracting complex underlying frameworks. The platform aims to streamline hotel operations, enhance guest experiences, and deliver a scalable solution for AI-powered guest interaction. The business vision is to become the leading provider of voice AI for the hospitality industry, offering a robust and intuitive platform that significantly improves operational efficiency and guest satisfaction.

## Recent Changes (November 26, 2025)

**Flow Simulator** - Test flows without making phone calls:
- **Simulation API** (`botelier/backend/botelier/api/simulation.py`): Endpoints for `/api/simulate/start`, `/api/simulate/message`, `/api/simulate/session/{id}`, `/api/simulate/test-api`
- **FlowSimulator Modal** (`components/flow-simulator/`): Chat-based testing interface with real-time slot tracking
- **Test Button on Tools Page**: Flows show an enabled "Test" button when nodes are configured
- **Function Picker**: Click to execute functions like slot collection, end call
- **Slot Tracker Panel**: Real-time display of collected variables and progress
- **API Tester**: Test API endpoints with variable substitution preview

**Flow Execution Runtime** - Backend system to execute flows during Pipecat calls:
- **FlowExecutor Class** (`botelier/backend/botelier/flow_executor.py`): Converts visual flows to Pipecat function schemas
- **Variable Substitution**: `{{variable_name}}` syntax replaced with collected slot values
- **Slot Collection Functions**: Each flow variable generates a `collect_*` function the LLM can call
- **Flow State Management**: Tracks current node, collected slots, flow completion status
- **FunctionMapper Integration**: FLOW tools now generate multiple function schemas per variable

**Enhanced Node Types** - Complete node system for hotel workflows:
- **Initial Node**: Greeting and system prompt configuration
- **Message Node**: Speak messages with variable substitution ({{variable}})
- **CollectSlot Node**: Gather guest information with validation and retry logic
- **APIRequest Node**: Call external APIs with templated URLs and response mapping
- **Condition Node**: Branch flow based on variable values (equals, greater_than, is_empty, etc.)
- **Transfer Node**: Escalate to human agent with pre-transfer message
- **End Node**: Graceful call termination with closing message

**Hotel-Specific Templates** - Pre-built conversation flows:
- **Room Booking**: Full reservation flow (name, dates, guest count, phone, confirmation)
- **Concierge Services**: Help with dining, spa, transportation, activities
- **Room Service**: Food orders with room number, items, dietary requirements

**Flow Editor Components**:
- `FlowEditor.tsx`: React Flow canvas with node types, MiniMap, and Controls
- `store.ts`: Zustand store with templates, flow loading/saving, variable management
- `FlowToolbar.tsx`: Add Node dropdown, Templates dropdown, Save Flow button
- `NodeInspector.tsx`: Type-specific property editors for each node type
- Custom nodes in `nodes/`: InitialNode, MessageNode, CollectSlotNode, APIRequestNode, ConditionNode, TransferNode, EndNode

**Flows as Tools Architecture**:
- **FLOW Tool Type**: New type in Tools system alongside TRANSFER_CALL, API_REQUEST, etc.
- **Intent-Based Activation**: LLM detects guest intent and triggers appropriate flow tool
- **Multi-Function Generation**: Each FLOW generates multiple Pipecat functions
- **API Endpoints**: `GET/PUT /api/tools/{tool_id}/flow` for flow configurations

**Previous Changes (November 25, 2025)**
- Visual Flow Editor initial implementation
- Assistant Card Actions with Copy, Play/Pause, More menu, Delete
- Toast Notification System using Sonner library

## User Preferences
- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend

## System Architecture
Botelier is built with a clean architectural separation, where the core SaaS application interacts with the Pipecat framework as a hidden dependency. The frontend uses Next.js with a Vapi.ai-style dark theme for consistency.

### UI/UX Decisions
- **Toast Notification System:** Professional in-app notifications using the Sonner library, matching the dark theme, with consistent bottom-right positioning.
- **Assistant Configuration Pages:** Unified 4-tab layout (Info → Language Model → Voice → Transcriber) with auto-tab-switching and shared components for consistent UX.
- **Reusable Form Components:** Includes `FormField`, `ProviderSelector`, `FormSection`, `TabNavigation`, and `SaveBar` with dirty form detection.
- **Sticky Headers:** Persistent header and tab navigation for improved usability.
- **Dual-view Systems:** Table/Grid views with sortable, searchable, and filterable data.
- **Bulk Selection:** Capabilities for managing multiple entries simultaneously.

### Technical Implementations & Feature Specifications
- **Voice AI Engine:** A `VoiceAgent` interface wraps Pipecat, allowing hotels to configure STT, LLM, and TTS providers, system prompts, and behaviors without direct Pipecat exposure.
- **Call Handling Infrastructure (Twilio Media Streams):** Twilio connects directly to the FastAPI backend (port 3001) via WebSockets. An HTTP webhook endpoint returns TwiML with `<Connect><Stream>` to establish the WebSocket connection. The `CallHandler` class orchestrates the Pipecat pipeline (STT → LLM → TTS) for real-time bidirectional audio. Phone number purchase automatically configures the Twilio webhook.
- **Tools System (Function Calling):** PostgreSQL stores various tool types (Transfer Call, API Request, End Call, SMS, Email) with `hotel_id` scoping. FastAPI CRUD endpoints enforce multi-tenant isolation. Pipecat integrates these tools by converting them into LLM function schemas.
- **Phone Numbers System (Twilio Integration):** Database models for Hotels and Phone Numbers, with a Twilio integration layer for sub-account management, number search, purchase, configuration, and release. FastAPI CRUD endpoints manage phone numbers with multi-tenancy via isolated Twilio sub-accounts.
- **Knowledge Base System (Simplified Q&A with RAG):** A flat database structure stores `KnowledgeEntry` associated with hotels. FastAPI CRUD endpoints support CSV bulk import. A RAG query handler, integrated with Pipecat and using OpenAI LLM (gpt-4o-mini), fetches active Q&A entries scoped by `hotel_id` and formats them for RAG, with a 50k character safety limit.
- **Twilio Call Transfer:** Implemented via Twilio REST API to update active calls with new TwiML for transfer.

### System Design Choices
- **Clean Branding:** "Botelier" branding is prioritized, with Pipecat treated as a hidden backend dependency.
- **Provider Configuration:** Flexible system for choosing AI providers (STT, LLM, TTS), models, voices, languages, and behavioral parameters.
- **Multi-tenancy with Complete Isolation:** All hotel resources are strictly isolated by `hotel_id` in database queries, API operations, and Twilio sub-accounts, ensuring no cross-hotel access.

## External Dependencies

### AI Providers
- **Speech-to-Text (STT):** Deepgram, OpenAI Whisper, AssemblyAI, Azure, Google, Groq, AWS Transcribe, Gladia, ElevenLabs, Riva, Soniox, Speechmatics, Cartesia, Sarvam.
- **Language Models (LLM):** OpenAI (GPT-4o, GPT-4-turbo), Anthropic (Claude), Google Gemini, Azure OpenAI, AWS Bedrock, Groq, Mistral, Together, DeepSeek, Perplexity, OpenRouter, Ollama, Fireworks, Cerebras.
- **Text-to-Speech (TTS):** Cartesia, ElevenLabs, OpenAI, Azure, Google, AWS Polly, Deepgram, PlayHT, LMNT, Rime, Piper, Neuphonic, Speechmatics, Riva, Sarvam.

### Databases
- PostgreSQL

### Third-Party Integrations
- **Twilio:** For phone number management, call handling, and sub-account isolation.
- **Pipecat Framework:** Underlying framework for the voice AI engine.
- **Daily:** For call transfers (via Pipecat integration).
- **Sonner:** For React toast notifications.