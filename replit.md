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
The core of the system is a `VoiceAgent` interface wrapping Pipecat, configurable for STT, LLM, and TTS providers. Call handling is managed via Twilio Media Streams, with a FastAPI backend and a `CallHandler` orchestrating the Pipecat pipeline. A robust tools system (Function Calling) is implemented with PostgreSQL and multi-tenant FastAPI endpoints. Phone number management is integrated with Twilio, supporting sub-accounts and number lifecycle. A simplified Knowledge Base system uses a flat database structure with RAG capabilities.

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