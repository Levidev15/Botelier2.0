# Botelier - Voice AI SaaS Platform

## Overview
Botelier is a multi-tenant SaaS platform that provides businesses with custom voice AI agents. Its primary purpose is to offer a business-centric interface for configuring conversational AI, abstracting complex underlying frameworks. The platform aims to streamline operations, enhance customer experiences, and deliver a scalable solution for AI-powered voice interaction. Key capabilities include a visual flow editor for designing conversational AI, a robust versioning system for flow management, integration with various AI providers for STT, LLM, and TTS, and comprehensive role-based access control.

## User Preferences
- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend
- **Naming:** Use generic terms (Account, not Hotel) to support various business types

## System Architecture
Botelier is built with a clean architectural separation, where the core SaaS application interacts with the Pipecat framework as a hidden dependency. The frontend uses Next.js with a Vapi.ai-style dark theme.

### UI/UX Decisions
- **Toast Notification System:** Professional, dark-themed in-app notifications using the Sonner library, consistently positioned at the bottom-right.
- **Assistant Configuration Pages:** Unified 4-tab layout (Info → Language Model → Voice → Transcriber) with auto-tab-switching and shared components for consistent UX.
- **Reusable Form Components:** Includes `FormField`, `ProviderSelector`, `FormSection`, `TabNavigation`, and `SaveBar` with dirty form detection.
- **Sticky Headers:** Persistent header and tab navigation.
- **Dual-view Systems:** Table/Grid views with sortable, searchable, and filterable data.
- **Bulk Selection:** Capabilities for managing multiple entries simultaneously.
- **Flow Editor:** React Flow canvas with node types (Initial, Message, CollectSlot, APIRequest, Condition, Router, Transfer, End), MiniMap, Controls, and a Node Inspector for property editing.
- **Flow Simulator:** Integrated sidebar with real LLM conversations (using OpenAI gpt-4o-mini), node highlighting, and real-time slot tracking.

### Technical Implementations & Feature Specifications
- **Voice AI Engine:** A `VoiceAgent` interface wraps Pipecat, allowing configuration of STT, LLM, and TTS providers, system prompts, and behaviors.
- **Call Handling Infrastructure (Twilio Media Streams):** Twilio connects to the FastAPI backend via WebSockets. A `CallHandler` class orchestrates the Pipecat pipeline (STT → LLM → TTS).
- **Tools System (Function Calling):** PostgreSQL stores various tool types (Transfer Call, API Request, End Call, SMS, Email) with `hotel_id` scoping. FastAPI CRUD endpoints enforce multi-tenant isolation.
- **Phone Numbers System (Twilio Integration):** Database models for Hotels and Phone Numbers, with Twilio integration for sub-account management, number search, purchase, configuration, and release.
- **Knowledge Base System (Simplified Q&A with RAG):** A flat database structure stores `KnowledgeEntry` associated with hotels. FastAPI CRUD endpoints support CSV bulk import. A RAG query handler, integrated with Pipecat and using OpenAI LLM (gpt-4o-mini), fetches active Q&A entries.
- **Twilio Call Transfer System:** Comprehensive transfer implementation with proper call leg tracking:
  - **Transfer Flow:** AI speaks pre-transfer message → Stop media stream → Dial transfer target
  - **TwiML Construction:** Dynamically built with `<Stop><Stream>`, `<Say>`, and `<Dial>` verbs
  - **Sub-account Support:** Uses hotel's `twilio_sub_account_sid` and `twilio_sub_auth_token` for API calls
  - **CallerId Handling:** Uses the hotel's phone number (the `to` number) as callerId for outbound transfer
  - **Status Callbacks:** Transfer-status endpoint receives initiated, ringing, answered, completed events
  - **Leg Tracking:** Transfer leg linked to child call_sid, with accurate timestamps and duration
- **Flow Versioning System:** Implements a draft/publish workflow, version history, and revert capability for conversational flows. Includes database model (`FlowVersion`), API endpoints for managing drafts and published versions, and publish-time validation. Revert updates existing draft content (not version number) to avoid duplicate key errors.
- **Unsaved Changes Warning:** Flow editor tracks dirty state and prompts users with Save/Discard/Cancel modal when navigating away with unsaved changes. Uses `useUnsavedChangesWarning` hook with `beforeunload` event handling.
- **Flow Execution Runtime:** `FlowExecutor` class converts visual flows to Pipecat function schemas, handles variable substitution, slot collection, and manages flow state.
- **Global Prompt System:** Flow-level instructions that apply to the entire conversation:
  - **FlowConfig.global_prompt:** Optional field stored in flow configuration
  - **Settings Modal:** Accessible via toolbar button, allows users to set flow-wide AI instructions
  - **LLM Integration:** Global prompt is injected into system prompt as "FLOW-LEVEL INSTRUCTIONS" section
  - **Use Cases:** Style guidelines (formal language, spell out names), consistent behaviors across all nodes
- **Delivery Mode System:** Each Message and Confirmation node has a "Delivery Mode" toggle:
  - **Guided (default):** AI receives the configured text as guidance and can phrase naturally while keeping the meaning
  - **Static:** AI must speak the exact configured text verbatim, with `speak_exactly` field enforcing exact output
  - System prompt dynamically adapts instructions per node based on delivery mode
- **Smart Function Schemas:** Already-collected slot functions are filtered from schemas to prevent re-asking for the same information
- **Enhanced Node Types:** Includes Initial, Message (with auto-advance), CollectSlot, APIRequest, Condition, Router, Transfer, End, Confirmation (for pre-submission reviews), and SetVariable (for mid-flow data transformations).
- **Flows as Tools Architecture:** Introduces a "FLOW" tool type activated by LLM intent, generating multiple Pipecat functions, with API endpoints for flow configurations.
- **Call Logs System:** Comprehensive call logging with multi-tenant isolation:
  - **CallLog Model:** Tracks each incoming call with hotel_id, call_sid, phone_number_id, assistant_id, caller_number, status, outcome, timestamps, duration, transcript, and recording_url
  - **CallLeg Model:** Tracks transfer segments (AI conversation, external transfer, SIP transfer) with individual durations for accurate billing
  - **UI Features:** Modern table view with expandable rows for calls with transfers, filters (date range, status, assistant, timezone), search, transcript popup modal, CSV export
  - **Twilio Integration:** Status callbacks automatically create/update call logs and track parent-child call relationships for transfers

### Authentication & Authorization System (Updated - Dec 2024)
- **Email/Password Authentication:** Platform-owned authentication with bcrypt password hashing and JWT tokens
  - **Backend Auth API:** `/api/auth/login`, `/api/auth/register`, `/api/auth/validate` endpoints
  - **JWT Tokens:** HS256 signed tokens with python-jose library, 30-day expiration
  - **Password Security:** bcrypt hashing with salt, password strength validation on frontend
  - **Dual Auth Support:** Middleware handles both email/password JWT tokens and legacy NextAuth/Replit tokens
- **User Types:**
  - `platform_admin`: Full access to all accounts and platform settings
  - `account_user`: Belongs to specific accounts with assigned roles
- **Role-Based Access Control (RBAC):**
  - **Role Templates:** account_admin, staff, viewer (system roles with default permissions)
  - **Granular Permissions:** Feature-level permissions (assistants.create, call_logs.export, etc.)
  - **Permission Overrides:** Individual users can have permissions added/removed from their role
- **Database Models:**
  - `User`: Stores email, password_hash, auth_provider, first_name, last_name, user_type, and profile
  - `Account`: Generic multi-tenant support (replaces legacy Hotel model)
  - `Role`: Permission templates, can be system or custom
  - `AccountMembership`: Links users to accounts with specific roles
- **Platform Admin Panel (Dec 2024):**
  - **Dashboard Routes:** `/admin` for main dashboard, `/admin/accounts` for account management, `/admin/users` for user management, `/admin/settings` for platform settings, `/admin/invitations` for invitation management
  - **Account Management:** Create, view, edit, suspend, and cancel accounts with full CRUD operations
  - **Integration Health Checks:** Real-time status verification for Twilio, OpenAI, and PostgreSQL via `/api/admin/integrations/health` endpoint
  - **Support Session System (SaaS-Compliant Account Access):**
    - Time-bound access tokens (1 hour expiry) for Platform Admins to access tenant accounts
    - Requires documented reason for audit trail compliance
    - Session tokens stored in `SupportSession` database model for validation
    - "Enter Account" button in account detail page with purpose modal → creates session → redirects to tenant dashboard
    - Frontend: `accountContext.ts` stores session in localStorage, `useAuthToken.ts` sends `X-Support-Session` and `X-Account-Id` headers with all API calls
    - Backend: Middleware validates session tokens via `validate_support_session()` helper
    - Dashboard shows purple admin banner with account name and "Exit Account" button when viewing tenant
  - **Audit Logging:** Console logging of privileged actions with `/api/admin/audit-log` endpoint ready for production implementation
  - **Twilio Sub-Account Provisioning:** One-click provisioning for tenant Twilio sub-accounts via `/api/admin/accounts/{id}/provision-twilio`
- **Invitation-Only Access System (Dec 2024):**
  - **AccountInvitation Model:** Secure token-based invitations with expiration (7 days default), status lifecycle (pending/accepted/revoked/expired)
  - **Platform Admin Endpoints:** Create, list, resend, and revoke invitations with RBAC protection
  - **Invitation Acceptance Flow:** Public `/invite/[token]` page with full registration form (first name, last name, password)
  - **No Open Sign-Up:** Users can only access the platform through Platform Admin invitations
  - **UI:** Platform Admin invitations management page with create modal, status filters, copy invite link, resend/revoke actions
- **Environment Variables:**
  - `NEXTAUTH_SECRET`: JWT signing secret (shared between frontend and backend)
  - `NEXTAUTH_URL`: Base URL for auth callbacks

### System Design Choices
- **Clean Branding:** "Botelier" branding is prioritized, with Pipecat treated as a hidden backend dependency.
- **Provider Configuration:** Flexible system for choosing AI providers (STT, LLM, TTS), models, voices, languages, and behavioral parameters.
- **Multi-tenancy with Complete Isolation:** All account resources are strictly isolated by `account_id` in database queries, API operations, and Twilio sub-accounts.
- **Dual Model Support:** Both `Hotel` (legacy) and `Account` (new) models exist during transition

## External Dependencies

### AI Providers
- **Speech-to-Text (STT):** Deepgram, OpenAI Whisper, AssemblyAI, Azure, Google, Groq, AWS Transcribe, Gladia, ElevenLabs, Riva, Soniox, Speechmatics, Cartesia, Sarvam.
- **Language Models (LLM):** OpenAI (GPT-4o, GPT-4-turbo), Anthropic (Claude), Google Gemini, Azure OpenAI, AWS Bedrock, Groq, Mistral, Together, DeepSeek, Perplexity, OpenRouter, Ollama, Fireworks, Cerebras.
- **Text-to-Speech (TTS):** Cartesia, ElevenLabs, OpenAI, Azure, Google, AWS Polly, Deepgram, PlayHT, LMNT, Rime, Piper, Neuphonic, Speechmatics, Riva, Sarvam.

### Databases
- PostgreSQL

### Third-Party Integrations
- **Twilio:** For phone number management, call handling, sub-account isolation, and call transfers via REST API.
- **Pipecat Framework:** Underlying framework for the voice AI engine.
- **Sonner:** For React toast notifications.