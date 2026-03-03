# Botelier - Voice AI SaaS Platform

## Overview
Botelier is a multi-tenant SaaS platform designed to provide businesses with custom voice AI agents. It offers a business-centric interface for configuring conversational AI, abstracting complex underlying frameworks. The platform aims to streamline operations, enhance customer experiences, and deliver a scalable solution for AI-powered voice interaction. Key capabilities include a visual flow editor, robust versioning, integration with various AI providers (STT, LLM, TTS), and comprehensive role-based access control. The business vision is to provide a scalable, user-friendly solution for AI-powered voice interactions.

## User Preferences
- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend
- **Naming:** Use generic terms (Account, not Hotel) to support various business types

## System Architecture
Botelier is built with a clean architectural separation, where the core SaaS application interacts with the Pipecat framework as a hidden dependency. The frontend uses Next.js with a Vapi.ai-style dark theme, prioritizing a professional user experience.

### UI/UX Decisions
The UI/UX includes a Sonner-based toast notification system, a unified 4-tab layout for assistant configuration with auto-tab-switching, reusable form components, sticky headers, dual-view systems (table/grid) with sorting and filtering, and bulk selection capabilities. The Flow Editor is a React Flow canvas with various node types (Initial, Message, CollectSlot, APIRequest, Condition, Router, Transfer, End) including a MiniMap, Controls, and a Node Inspector. A Flow Simulator is integrated for real-time testing.

### Technical Implementations & Feature Specifications
The core of the system is a `VoiceAgent` interface wrapping Pipecat, configurable for STT, LLM, and TTS providers. Call handling is managed via Twilio Media Streams, with a FastAPI backend and a `CallHandler` orchestrating the Pipecat pipeline. A robust tools system (Function Calling) is implemented with PostgreSQL and multi-tenant FastAPI endpoints. Phone number management is integrated with Twilio, supporting sub-accounts and number lifecycle.

**Named Collections Architecture:** Knowledge and tools are organized into named collections (KnowledgeBase, ToolSet) that can be shared across assistants, updated independently, and provide clear organizational boundaries. The Knowledge Base uses direct system prompt injection for immediate access and improved answer quality.

Advanced features include a comprehensive Twilio Call Transfer system, a Flow Versioning System with draft/publish workflow, version history, and revert functionality. The Flow Editor includes unsaved changes warnings. A `FlowExecutor` class converts visual flows into Pipecat function schemas. A Global Prompt System allows flow-level instructions to be injected into the LLM system prompt. A Delivery Mode system for Message and Confirmation nodes allows for "Guided" (AI phrasing) or "Static" (exact verbatim) outputs. Flows can also be exposed as tools for LLM intent activation.

The Call Logs system provides comprehensive multi-tenant logging with `CallLog` and `CallLeg` models, a modern UI with search, filters, transcript popups, and CSV export. The system also includes a Call Dispositions System allowing custom call outcome categorization per assistant, with a dedicated UI for configuration and AI auto-selection. AI Summary Generation, using OpenAI's gpt-4o-mini, provides on-demand call transcript analysis.

**SMS Logs & Analytics Foundation:** The `sms_conversations` table includes `handler_mode` (VARCHAR, `ai`/`human`, indexed) for tracking AI-vs-human handling, and `first_response_at` (TIMESTAMP) for response-time analytics. `GET /api/sms/conversations` accepts `date_from`, `date_to`, `botelier_number`, `handler_mode`, `sort_by`, and `sort_order` parameters. `GET /api/sms/stats` returns a full aggregation (overview counts, volume by day, response time, by phone number, by assistant, dispositions, top customers). `GET /api/sms/export` streams a CSV of up to 10,000 conversations with all key fields. Pricing columns (`price`, `price_unit`) are intentionally deferred — see the docstring in `sms_conversation.py` for the one-liner migration when ready. Startup migrations in `database.py` use idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` — add new columns there following the existing pattern. Index `ix_sms_conv_started_at` was added for efficient date-range queries.

**SMS AI Channel:** Assistants can handle SMS conversations alongside voice calls, sharing the same system prompt, knowledge base, and tools. SMS config is stored as JSONB on the Assistant model (`sms_config`), supporting model override, max response length, session timeout, welcome message, and SMS-specific prompt additions. The `SMSService` processes incoming messages via Twilio webhook (`/api/sms/webhook`), builds LLM context with KB injection and conversation history, executes tool calls (API Request tools), and sends replies via Twilio REST API. Separate `SMSConversation` and `SMSMessage` models provide clean data separation from call logs. Phone numbers can be individually toggled for SMS with optional SMS-specific assistant assignment. The Messages inbox provides a split-panel UI for viewing and managing SMS conversations with AI summary generation. TCPA compliance is built in with STOP/START opt-out/opt-in handling.

**SMS AI Handoff System:** When the AI cannot resolve a customer request, it prefixes its response with `[HANDOFF]`. The backend strips the prefix, delivers the final message to the customer, flips `handler_mode` to `human` and `needs_attention` to `True` on the conversation, and broadcasts a `handoff_requested` SSE event. In `human` mode the AI stays silent — inbound messages are saved but not replied to. Agents can manually toggle via `POST /api/sms/conversations/{id}/take-over` (AI→human, sets needs_attention=True) and `POST /api/sms/conversations/{id}/return-to-ai` (human→AI, sets needs_attention=False); both broadcast a `handler_changed` SSE event. The Messages UI shows an indigo "AI" or amber "Agent" pill on each conversation card (based on `handler_mode`), and a "Take Over" or "Return to AI" button in the thread header. The `handoff_requested` event displays an amber warning toast to all connected agents. Real-time AI reply updates: the webhook handler now broadcasts `new_reply` after the AI message is committed, so the open thread refreshes automatically without manual reload. `GET /api/sms/pending-handoffs?hotel_id=xxx` returns `{count}` of conversations with `needs_attention=True`. The sidebar "Messages" nav item shows a red badge with this count, polled every 30 seconds from the layout component. **Two-field design:** `needs_attention` (urgency — amber styling, sidebar count) is separate from `handler_mode` (who's responding — AI/human badge). When an agent first replies to a needs-attention conversation, `needs_attention` is cleared (amber styling removed) and a `handler_changed` SSE is broadcast; `handler_mode` stays `human`. When a CLOSED conversation is reopened by a new inbound message, both `handler_mode` and `needs_attention` reset to AI defaults for the new session. The ESCALATION PROTOCOL system prompt section is injected last (highest recency weight) with explicit `[HANDOFF]` usage examples to ensure reliable AI compliance.

**SMS Enhanced Messaging Features:**
- **Unified Threading:** One conversation per customer_number + botelier_number + hotel_id. Session timeouts create `session_boundary` markers on messages instead of new conversations; closed conversations are reopened for new inbound messages.
- **Active Agent Indicator:** Ephemeral presence tracking via `active_agent_id`, `active_agent_name`, `agent_active_at` on SMSConversation. 15-second heartbeat with 30-second stale threshold. Shown as amber "AgentName is viewing" in thread header and conversation list.
- **Hotel-Side Attachments:** Agent replies support file attachments (images + PDF) via `POST /api/sms/upload` endpoint. Files stored in `backend/uploads/`, served via FastAPI StaticFiles mount. `media_urls` JSONB column on SMSMessage stores attachment URLs. Twilio MMS for delivery. 5MB per file limit, max 10 per message.
- **SMS Templates / Canned Responses:** `SMSTemplate` model with name, content (supports `{{variable}}` placeholders like `{{customer_number}}`, `{{date}}`, `{{time}}`, `{{guest_name}}`), category, and is_active fields. Full CRUD at `/api/sms/templates`. Templates popover in reply area for quick insertion with variable resolution. Settings panel for template management.
- **Message Notifications:** `SMSNotificationSettings` model per hotel with sound_enabled, visual_enabled, threshold, and sound_type (chime/bell/ding). `GET /api/sms/unread-count` endpoint for polling. Frontend polls every 30 seconds, plays Web Audio API tones when tab is hidden and unread count exceeds threshold. Slide-out Settings panel with Templates and Notifications tabs.

**SMS Compliance (A2P 10DLC):** Full SMS compliance management built into Botelier, allowing accounts to register brands and campaigns with Twilio without leaving the platform. Brand registration is account-level (one brand per business entity with EIN, address, authorized representative) while campaign registration is hotel-level (each hotel gets its own campaign with use case, message samples, opt-in/opt-out flows). The system uses Twilio's Trust Hub API for customer profiles and A2P profile bundles, and the Messaging API for brand/campaign registration. Features include: multi-step brand registration form, campaign creation with all TCR-required fields, real-time status tracking with refresh capability (draft/pending/in_review/approved/failed), phone number assignment to campaigns via Messaging Services, and failure reason display. Models: `SMSComplianceBrand` (account-level) and `SMSComplianceCampaign` (hotel-level). Service: `SMSComplianceService` wraps all Twilio Trust Hub + Messaging API calls.

The Authentication & Authorization system features platform-owned email/password authentication with bcrypt hashing and JWT tokens, supporting `platform_admin` and `account_user` types. A robust Role-Based Access Control (RBAC) system uses role templates, granular permissions, and individual user overrides. A Platform Admin Panel provides comprehensive management for accounts, users, platform settings, and invitations, including a SaaS-compliant Support Session system and one-click Twilio sub-account provisioning. An Invitation-Only Access System ensures controlled user onboarding.

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
- **Multi-Tenant Integration System:** A platform-level integration registry for connecting account-specific third-party services (e.g., Oracle Opera Cloud, GuestCentric CRS) with universal authentication support (OAuth 2.0, Basic Auth, JWT). API Request tools enable direct API calls with templating and response mapping.
- **MCP (Model Context Protocol) Integration System:** Enables assistants to connect to external MCP servers for dynamic, hotel-specific tools (e.g., property management systems), leveraging the official MCP Python SDK with SSE transport.
