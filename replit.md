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
- Tabbed navigation for agent configuration.
- Reusable form components (FormField, ProviderSelector).
- Sticky headers and smart dirty form detection.
- Dual-view systems (Table/Grid) with sortable, searchable, and filterable data.
- Bulk selection and action capabilities for managing entries.

### Technical Implementations & Feature Specifications
- **Voice AI Engine:** A wrapper around Pipecat provides a clean `VoiceAgent` interface, allowing hotels to configure STT, LLM, and TTS providers, system prompts, and behaviors without exposing Pipecat internals.
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
- **Multi-tenancy:** Core systems like Twilio integration are designed with multi-tenancy in mind, ensuring isolation and proper billing for each hotel.

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