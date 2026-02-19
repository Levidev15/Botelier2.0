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

**SMS AI Channel:** Assistants can handle SMS conversations alongside voice calls, sharing the same system prompt, knowledge base, and tools. SMS config is stored as JSONB on the Assistant model (`sms_config`), supporting model override, max response length, session timeout, welcome message, and SMS-specific prompt additions. The `SMSService` processes incoming messages via Twilio webhook (`/api/sms/webhook`), builds LLM context with KB injection and conversation history, executes tool calls (API Request tools), and sends replies via Twilio REST API. Separate `SMSConversation` and `SMSMessage` models provide clean data separation from call logs. Phone numbers can be individually toggled for SMS with optional SMS-specific assistant assignment. The Messages inbox provides a split-panel UI for viewing and managing SMS conversations with AI summary generation. TCPA compliance is built in with STOP/START opt-out/opt-in handling.

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
- **Zoom Contact Center Reports Integration:** Automated queue performance reporting from Zoom Contact Center, fetching and storing hourly snapshots for analysis and display on a dedicated dashboard.