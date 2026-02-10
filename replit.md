# Botelier - Voice AI SaaS Platform

## Overview
Botelier is a multi-tenant SaaS platform that provides businesses with custom voice AI agents. Its primary purpose is to offer a business-centric interface for configuring conversational AI, abstracting complex underlying frameworks. The platform aims to streamline operations, enhance customer experiences, and deliver a scalable solution for AI-powered voice interaction. Key capabilities include a visual flow editor, robust versioning, integration with various AI providers (STT, LLM, TTS), and comprehensive role-based access control. The business vision is to provide a scalable, user-friendly solution for AI-powered voice interactions.

## User Preferences
- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend
- **Naming:** Use generic terms (Account, not Hotel) to support various business types

## System Architecture
Botelier is built with a clean architectural separation, where the core SaaS application interacts with the Pipecat framework as a hidden dependency. The frontend uses Next.js with a Vapi.ai-style dark theme.

### UI/UX Decisions
The UI/UX prioritizes a professional, dark-themed experience. Key components include a Sonner-based toast notification system, a unified 4-tab layout for assistant configuration with auto-tab-switching, reusable form components, sticky headers, dual-view systems (table/grid) with sorting and filtering, and bulk selection capabilities. The Flow Editor is a React Flow canvas with various node types (Initial, Message, CollectSlot, APIRequest, Condition, Router, Transfer, End) including a MiniMap, Controls, and a Node Inspector. A Flow Simulator is integrated for real-time testing with LLM conversations and slot tracking.

### Technical Implementations & Feature Specifications
The core of the system is a `VoiceAgent` interface wrapping Pipecat, configurable for STT, LLM, and TTS providers. Call handling is managed via Twilio Media Streams, with a FastAPI backend and a `CallHandler` orchestrating the Pipecat pipeline. A robust tools system (Function Calling) is implemented with PostgreSQL and multi-tenant FastAPI endpoints. Phone number management is integrated with Twilio, supporting sub-accounts and number lifecycle.

**Named Collections Architecture:** Knowledge and tools are organized into named collections that can be shared across assistants:
- **KnowledgeBase Model:** Named collection of Q&A entries (id, name, description, account_id). Assistants reference via `knowledge_base_id`.
- **ToolSet Model:** Named collection of action tools (id, name, description, account_id). Assistants reference via `tool_set_id`.
- **Benefits:** Collections can be shared across multiple assistants, updated independently, and provide clear organizational boundaries.

**Knowledge Base System:** Uses direct system prompt injection. At call start, KB content is loaded via `load_knowledge_for_prompt(knowledge_base_id)` and injected into the LLM's system prompt. This approach provides: (1) immediate access without tool-call latency, (2) prompt caching on subsequent turns, (3) better answer quality since LLM has full context. System prompt includes clear instructions to answer from KB first and only transfer when the caller explicitly requests it or the KB doesn't have the needed information.

**TTS Text Normalizer:** A Pipecat FrameProcessor (`botelier/backend/botelier/voice/tts_normalizer.py`) sits in the pipeline between InterruptionTracker and TTS. It normalizes LLM output for natural speech: currency ($2.99 → "2 dollars and 99 cents"), percentages (15% → "15 percent"), times (3:00 PM → "3 P M"), room numbers (#302 → "number 302"), and dimensions (25 x 50 → "25 by 50"). Only processes downstream frames; passes all other frames through unchanged.

Advanced features include a comprehensive Twilio Call Transfer system with proper call leg tracking and dynamic TwiML construction, ensuring voice consistency and status callbacks. A Flow Versioning System provides a draft/publish workflow, version history, and revert functionality. The Flow Editor includes unsaved changes warnings. A `FlowExecutor` class converts visual flows into Pipecat function schemas, managing variables and state. A Global Prompt System allows flow-level instructions to be injected into the LLM system prompt. A Delivery Mode system for Message and Confirmation nodes allows for "Guided" (AI phrasing) or "Static" (exact verbatim) outputs. Smart Function Schemas prevent re-asking for collected slots. Enhanced node types include Confirmation and SetVariable. Flows can also be exposed as tools for LLM intent activation.

The Call Logs system provides comprehensive multi-tenant logging with `CallLog` and `CallLeg` models, a modern UI with search, filters, transcript popups, and CSV export. Twilio status callbacks automatically update logs. The system also includes a Call Dispositions System allowing custom call outcome categorization per assistant, with a dedicated UI for configuration and AI auto-selection. AI Summary Generation, using OpenAI's gpt-4o-mini, provides on-demand call transcript analysis and combines it with disposition auto-selection.

The Authentication & Authorization system features platform-owned email/password authentication with bcrypt hashing and JWT tokens, supporting `platform_admin` and `account_user` types. A robust Role-Based Access Control (RBAC) system uses role templates, granular permissions, and individual user overrides. A Platform Admin Panel provides comprehensive management for accounts, users, platform settings, and invitations. It includes integration health checks, a SaaS-compliant Support Session system for platform admins to securely access tenant accounts with audit trails, and one-click Twilio sub-account provisioning. An Invitation-Only Access System ensures controlled user onboarding with secure token-based invitations and no open sign-up.

### System Design Choices
The architecture emphasizes clean branding ("Botelier"), flexible provider configuration for AI services, and strict multi-tenancy with complete isolation by `account_id` across all resources and Twilio sub-accounts.

## External Dependencies

### AI Providers
- **Speech-to-Text (STT):** Deepgram, OpenAI Whisper, AssemblyAI, Azure, Google, Groq, AWS Transcribe, Gladia, ElevenLabs, Riva, Soniox, Speechmatics, Cartesia, Sarvam.
- **Language Models (LLM):** OpenAI, Anthropic, Google Gemini, Azure OpenAI, AWS Bedrock, Groq, Mistral, Together, DeepSeek, Perplexity, OpenRouter, Ollama, Fireworks, Cerebras.
- **Text-to-Speech (TTS):** Cartesia, ElevenLabs, OpenAI, Azure, Google, AWS Polly, Deepgram, PlayHT, LMNT, Rime, Piper, Neuphonic, Speechmatics, Riva, Sarvam.

### Databases
- PostgreSQL

### Third-Party Integrations
- **Twilio:** For phone number management, call handling, sub-account isolation, and call transfers.
- **Pipecat Framework:** Underlying framework for the voice AI engine.
- **Sonner:** For React toast notifications.

### Multi-Tenant Integration System
A platform-level integration registry allows accounts to connect their own third-party services. The system is designed to be universal — adding a new integration type is just a matter of creating a seed file with endpoints and auth config. Key features:
- **IntegrationType Model:** Platform seeds available integration types with auth configs, required credential fields, and pre-configured API endpoints.
- **AccountIntegration Model:** Per-account connections with encrypted credential storage using Fernet encryption.
- **Flow Editor Integration:** API Request nodes support both Custom URL and Integration sources. When Integration is selected, users can choose from connected integrations and select pre-configured endpoints.
- **Endpoints:** `/api/integrations/connections` returns account integrations with full integration type details including endpoints for flow editor dropdowns.
- **Universal Auth Support:** The IntegrationClient (`botelier/backend/botelier/services/integration_client.py`) supports three auth methods:
  - **OAuth 2.0** (`oauth2_client_credentials`): Client credentials grant with token refresh. Used by Opera Cloud.
  - **Basic Auth** (`basic_auth`): HTTP Basic Auth header with optional query parameters (apikey, hotelId). No token management needed.
  - **JWT** (`jwt`): Auto-login to get token, cache it, refresh on expiry. Token lifecycle managed automatically.
  - Integrations can support multiple auth methods (e.g., `basic_or_jwt`) — user selects their preferred method via a `select` field in required_fields.
- **Required Fields:** Support `text`, `password`, `url`, and `select` (with `options` array) field types. The frontend connect modal renders these dynamically.

**Seeded Integration Types:**
- **Oracle Opera Cloud (OHIP)** (`opera-cloud`): OAuth 2.0 auth, 10 endpoints (reservations, profiles, availability, configuration, front desk).
- **GuestCentric CRS** (`guestcentric-crs`): Basic Auth or JWT, 15 endpoints (search, hotels, reservations). Seed file: `botelier/backend/botelier/seeds/guestcentric_integration.py`.

**Adding New Integrations:** Create a new seed file following the pattern in `botelier/backend/botelier/seeds/opera_integration.py` or `guestcentric_integration.py`. Define slug, name, auth_type, auth_config, required_fields, and endpoints. Call the seed function in `main.py` startup. The frontend and backend handle the rest automatically.

**API Request Tools (ToolSet):** Full configuration for direct API calls with method, URL, headers, body templates ({{variable}} substitution), parameters, response mapping (dot notation extraction), response instructions (LLM guidance), and configurable timeout. API Tester tab for testing endpoints with SSRF protection. Backend function_mapper handles response shaping and instruction injection during live calls.

### MCP (Model Context Protocol) Integration System
The MCP integration enables assistants to connect to external MCP servers for dynamic, hotel-specific tools (like property management systems or booking engines). This follows the named collections architecture pattern.

**Data Model:**
- **MCPConnection Model:** Per-account MCP server connections (id, account_id, name, server_url, auth_type, encrypted_credentials, status, discovered_tools, is_active). Credentials encrypted with Fernet.
- **Assistant.mcp_connection_id:** Foreign key linking assistant to an MCP connection.
- **Assistant.mcp_enabled_tools:** JSONB array of tool names enabled for the assistant (per-assistant tool toggling).

**MCP Client Service (`botelier/backend/botelier/services/mcp_client.py`):**
- Uses official MCP Python SDK (v1.26.0) with SSE transport for connecting to remote MCP servers.
- `MCPClient` class: Handles connection, tool discovery, and tool execution.
- `MCPClientPool`: Singleton pool for efficient connection reuse across calls.
- `test_mcp_connection()`: Convenience function for testing connections and discovering tools.

**API Endpoints (`/api/mcp-connections`):**
- `GET /api/mcp-connections`: List connections for an account (optional `include_tools=true` for discovered tools).
- `POST /api/mcp-connections`: Create new connection.
- `GET /api/mcp-connections/{id}`: Get single connection details.
- `PUT /api/mcp-connections/{id}`: Update connection.
- `DELETE /api/mcp-connections/{id}`: Delete connection.
- `POST /api/mcp-connections/{id}/test`: Test connection and refresh discovered tools.
- `POST /api/mcp-connections/{id}/discover-tools`: Re-discover tools from the server.

**UI Integration:**
- MCP Connections section in Integrations tab with create/edit modal, connection testing, and tool display.
- MCP Connection dropdown in Assistant configuration form with per-tool enable/disable checkboxes.

**Call Handler Integration:**
- At call start, if assistant has `mcp_connection_id`, the MCP client is connected via the pool.
- Enabled MCP tools are converted to Pipecat FunctionSchema objects.
- MCP tool handlers execute via `client.execute_tool()` when the LLM invokes them.
- MCP client references cleaned up when call ends.