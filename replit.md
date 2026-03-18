# Botelier - Voice AI SaaS Platform

## Overview
Botelier is a multi-tenant SaaS platform that empowers businesses with custom voice AI agents. It provides a business-centric interface to configure conversational AI, abstracting complex underlying frameworks. The platform aims to streamline operations, enhance customer experiences, and offer a scalable solution for AI-powered voice interaction. Key capabilities include a visual flow editor, robust versioning, integration with various AI providers (STT, LLM, TTS), and comprehensive role-based access control. The business vision is to provide a scalable, user-friendly solution for AI-powered voice interactions.

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

**Named Collections Architecture:** Knowledge and tools are organized into named collections (KnowledgeBase, ToolSet) that can be shared across assistants and updated independently. The Knowledge Base uses direct system prompt injection.

Advanced features include a comprehensive Twilio Call Transfer system with warm/cold transfer mode toggle. A Flow Versioning System with draft/publish workflow, version history, and revert functionality. The Flow Editor includes unsaved changes warnings. A `FlowExecutor` class converts visual flows into Pipecat function schemas. A Global Prompt System allows flow-level instructions to be injected into the LLM system prompt. A Delivery Mode system for Message and Confirmation nodes allows for "Guided" (AI phrasing) or "Static" (exact verbatim) outputs. Flows can also be exposed as tools for LLM intent activation.

The Call Logs system provides comprehensive multi-tenant logging with `CallLog` and `CallLeg` models, a modern UI with search, filters, transcript popups, and CSV export. The system also includes a Call Dispositions System allowing custom call outcome categorization per assistant, with a dedicated UI for configuration and AI auto-selection. AI Summary Generation, using OpenAI's gpt-4o-mini, provides on-demand call transcript analysis.

**Friendly Reference IDs:** Both `call_logs` and `sms_conversations` have a `reference_id VARCHAR(8)` column — an 8-char uppercase hex identifier (e.g. `A3F7B2C1`) auto-generated on creation via `_generate_reference_id()` (uses `uuid4().hex[:8].upper()`). Existing rows were backfilled at migration time using PostgreSQL's `gen_random_uuid()`. Unique per hotel (hotel_id + reference_id index). Reference IDs are shown as monospace chips in the call logs table rows and transcript modal header, and as small chips in the SMS conversation list. Search in both call logs (`GET /api/call-logs`) and SMS conversations (`GET /api/sms/conversations`) accepts reference IDs via the `search` parameter.

**SMS Webhook Signature Validation:** `_validate_twilio_signature` in `sms_pkg/webhook.py` reconstructs the canonical public URL using `_build_webhook_url()` which calls `get_public_base_url()` from `config/domain.py`. This always returns the correct external-facing URL (never the internal `http://0.0.0.0:3001/...` URL that FastAPI sees), so Twilio's `X-Twilio-Signature` check passes. The validator returns `(is_valid, url_used)` so failures include the validated URL in the log for easy debugging. The sub-account auth token is used if available (Twilio signs with the sub-account token when the phone number belongs to a sub-account), falling back to the platform-level token.

**SMS Backend Architecture:** The SMS API is organized as a sub-package with modules for webhooks, conversations, analytics, and settings. The `SMSService` OpenAI client is a module-level singleton.
**SMS Frontend Architecture:** `messages/page.tsx` mounts three components: `hooks/useSMSData.ts` for state, data fetching, and SSE logic; `components/ConversationList.tsx` for the left panel; and `components/MessageThread.tsx` for the right panel. `components/SMSSettingsPanel.tsx` handles settings.
**SMS Logs & Analytics Foundation:** The `sms_conversations` table includes `handler_mode` and `first_response_at` for tracking and analytics. API endpoints provide conversation lists, statistics, and CSV export.
**SMS AI Channel:** Assistants can handle SMS conversations alongside voice calls, sharing the same system prompt, knowledge base, and tools. SMS configuration is stored on the Assistant model (`sms_config`). The `SMSService` processes incoming messages, builds LLM context, executes tool calls, and sends replies via Twilio. Separate `SMSConversation` and `SMSMessage` models are used. Phone numbers can be toggled for SMS with optional assistant assignment. The Messages inbox provides a split-panel UI with AI summary generation. TCPA compliance is built in with STOP/START opt-out/opt-in handling.
**SMS AI Handoff System:** The AI initiates handoff by prefixing responses with `[HANDOFF]`. The backend processes this, flips `handler_mode` to `human` and `needs_attention` to `True`, and broadcasts an SSE event. Agents can manually take over or return to AI. Real-time AI reply updates are broadcast. A `pending-handoffs` endpoint provides counts for UI badges.
**SMS Enhanced Messaging Features:** Includes unified threading with session timeouts, active agent indicators, agent replies with file attachments via Twilio MMS, SMS templates/canned responses with variable placeholders, and message notifications with configurable sounds and thresholds.
**SMS Compliance (A2P 10DLC):** Full SMS compliance management, allowing accounts to register brands and campaigns with Twilio without leaving the platform. Uses Twilio's Trust Hub API and Messaging API for brand/campaign registration, status tracking, and phone number assignment.

**Post Call QA / After-Call Work (ACW) System:** A per-assistant configurable system that analyzes call transcripts after completion. Three analysis sections: Dispositions (configurable call outcomes with name/description/color), Resolution Status (configurable resolution options with name/description, model: `AssistantResolutionOption`), and AI Quality Score (0-100 based on a configurable rubric). A separate Summary section with toggle and configurable prompt. Configuration is stored in `assistants.acw_config` JSONB column. Results are stored on `call_logs`: `disposition_id` (FK), `acw_resolution` (String), `acw_quality_score` (Integer), `acw_completed_at` (DateTime). `AcwService` (`botelier/services/acw_service.py`) runs a single `gpt-4o-mini` call returning structured JSON for all enabled sections — only requests what is enabled to minimize token usage. Auto-trigger via FastAPI `BackgroundTasks` in `calls.py` when `acw_config.auto_run=True`; otherwise manual via the `generate-summary` endpoint. The background task includes retry logic for transcript availability.

**Analytics Dashboards:** Two dedicated customizable analytics pages — Call Analytics (`/dashboard/analytics/calls`) and SMS Analytics (`/dashboard/analytics/sms`). Each page features a widget-based layout with stat cards, line charts, bar charts, and donut charts powered by Recharts. Users can toggle widgets on/off via a "Customize" slide-over panel (preferences saved to localStorage per page). A time-range picker (7d / 30d / 90d) drives all widgets. Call Analytics covers: total calls, completion/transfer rates, avg duration, volume over time, calls by hour, status/disposition breakdowns, by-assistant, and Post Call QA metrics (quality score distribution, resolution status). SMS Analytics covers: conversations, escalation rate, AI handle rate, response time, volume over time, handler mode split, message volume, by assistant, and top phone numbers. Backend endpoint: `GET /api/analytics/calls` in `botelier/api/analytics.py`. SMS reuses existing `GET /api/sms/stats`. Shared components live in `components/analytics/` (StatCard, DashboardWidget, TimeRangePicker, CustomizePanel, useWidgetLayout hook).

The Authentication & Authorization system features platform-owned email/password authentication with bcrypt hashing and JWT tokens, supporting `platform_admin` and `account_user` types. A robust Role-Based Access Control (RBAC) system uses role templates, granular permissions, and individual user overrides. A Platform Admin Panel provides comprehensive management for accounts, users, platform settings, and invitations, including a SaaS-compliant Support Session system and one-click Twilio sub-account provisioning. An Invitation-Only Access System ensures controlled user onboarding.

**End-to-End RBAC Permission Enforcement (Task #11):** All API endpoints are protected with `check_account_permission(user, account_id, "resource.action", db)` calls via the `botelier/auth/middleware.py` helper. Protected resources: `assistants`, `call_logs`, `knowledge_bases`, `tools` & `tool_sets`, `flow_versions`, `phone_numbers`, `dispositions`, `resolution_options`, `analytics`. Platform admins bypass all permission checks. The frontend `usePermissions` hook (`lib/auth/usePermissions.ts`) fetches resolved permissions from `GET /api/admin/me/permissions?account_id=...` with 60s caching. A `PermissionGate` component and `usePagePermission` hook gate key dashboard pages (assistants, call-logs, knowledge-bases, tools, phone-numbers) with `AccessDeniedPage` fallback for unauthorized users. Permission keys follow the schema defined in `botelier/auth/permissions.py` (e.g., `phone_numbers.configure`, `phone_numbers.release`, `call_logs.view` for analytics).

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
- **Multi-Tenant Integration System:** A platform-level integration registry for connecting account-specific third-party services (e.g., Oracle Opera Cloud, GuestCentric CRS) with universal authentication support.
- **MCP (Model Context Protocol) Integration System:** Enables assistants to connect to external MCP servers for dynamic, hotel-specific tools, leveraging the official MCP Python SDK.