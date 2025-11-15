# Botelier - Hotel Voice AI SaaS Platform

## Overview

**Botelier** is a multi-tenant SaaS platform that enables hotels to create and manage voice AI agents for guest services. Built on top of the Pipecat framework (hidden as an implementation detail), Botelier provides a clean, hotel-focused interface for configuring conversational AI without exposing framework internals.

## Project Structure

```
.
├── botelier/                    # Main SaaS Application
│   ├── frontend/               # Next.js hotel dashboard (to be built)
│   ├── backend/                # FastAPI Python server
│   │   └── botelier/          # Main application package
│   │       ├── api/           # REST API endpoints (to be built)
│   │       ├── models/        # Database models (to be built)
│   │       ├── voice/         # ✅ Voice AI engine (Pipecat wrapper)
│   │       ├── auth/          # Authentication (to be built)
│   │       ├── integrations/  # Hotel systems (to be built)
│   │       └── config/        # ✅ Provider configurations
│   └── database/              # Database schemas (to be built)
│
├── src/pipecat/               # Pipecat framework (dependency)
├── examples/quickstart/       # Original Pipecat examples
└── replit.md                  # This file

```

## Architecture Principles

### 1. Clean Branding
- **95% of code is "Botelier"** - Developers work with Botelier interfaces
- **Pipecat is a dependency** - Like using React or Django
- **No framework exposure** - Hotels never see Pipecat internals

### 2. Example: How Hotels Create Agents

**What developers see (Botelier API):**
```python
from botelier.voice import VoiceAgent, VoiceAgentConfig

agent = VoiceAgent(VoiceAgentConfig(
    name="Concierge",
    stt_provider="deepgram",
    llm_provider="openai",
    tts_provider="cartesia",
    system_prompt="You are a helpful hotel concierge.",
))
```

**What happens internally (hidden):**
```python
# botelier/backend/botelier/voice/engine.py
# This file uses Pipecat - hotels never see this
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
# ... implementation details hidden
```

## Current Status

### ✅ Completed (Task 1)

**Project Foundation:**
- Created `botelier/` directory structure
- Built voice AI engine wrapper (`botelier/backend/botelier/voice/`)
  - `agent.py` - Clean VoiceAgent interface
  - `engine.py` - Pipecat integration (hidden)
  - `orchestrator.py` - Multi-agent session management
  - `session.py` - Call session tracking
- Configured all AI providers (`config/providers.py`)
  - 14+ STT providers (Deepgram, OpenAI, Azure, etc.)
  - 14+ LLM providers (OpenAI, Anthropic, Gemini, etc.)
  - 15+ TTS providers (Cartesia, ElevenLabs, Google, etc.)
- Comprehensive provider metadata (models, voices, capabilities)

### 🚧 In Progress (Tasks 2-9)

**Next Steps:**
- Task 2: Next.js frontend with authentication
- Task 3: PostgreSQL multi-tenant database schema
- Task 4: FastAPI backend REST API
- Task 5: Hotel dashboard UI for agent configuration
- Task 6: Provider selection interface
- Task 7: Agent settings UI
- Task 8: API key management with encryption
- Task 9: Testing with sample agents

## AI Provider Support

### Speech-to-Text (STT)
Deepgram, OpenAI Whisper, AssemblyAI, Azure, Google, Groq, AWS Transcribe, Gladia, ElevenLabs, Riva, Soniox, Speechmatics, Cartesia, Sarvam

### Language Models (LLM)
OpenAI (GPT-4o, GPT-4-turbo), Anthropic (Claude), Google Gemini, Azure OpenAI, AWS Bedrock, Groq, Mistral, Together, DeepSeek, Perplexity, OpenRouter, Ollama, Fireworks, Cerebras

### Text-to-Speech (TTS)
Cartesia, ElevenLabs, OpenAI, Azure, Google, AWS Polly, Deepgram, PlayHT, LMNT, Rime, Piper, Neuphonic, Speechmatics, Riva, Sarvam

## Configurable Parameters

Hotels can customize:
- **Voice Providers:** Choose any STT/LLM/TTS combination
- **Models:** Select specific models per provider
- **Voices:** Pick from dozens of voice options
- **Languages:** Multi-language support
- **Behavior:** Temperature, speed, emotions, interruptions
- **Prompts:** System prompts and greetings
- **Functions:** Enable hotel system integrations (PMS, booking, concierge)

## Development Notes

### Pipecat Framework Location
- `src/pipecat/` contains the original Pipecat framework
- `examples/quickstart/` contains the original demo bot
- **Do not modify these** - they're the dependency

### Botelier Application Location
- `botelier/` contains YOUR SaaS application
- This is where all development happens
- Import Pipecat like any library: `from pipecat.services...`

### Adding New AI Providers

1. Add enum to `botelier/backend/botelier/config/providers.py`
2. Add configuration with models/voices
3. Implement factory in `botelier/backend/botelier/voice/engine.py`
4. Provider automatically appears in dashboard

### Updating Pipecat

```bash
pip install --upgrade pipecat-ai
# That's it! Wrapper isolates changes
```

## Original Pipecat Setup (Reference)

The quickstart bot is still configured if you need to reference it:

**API Keys Required (for quickstart example):**
- `DEEPGRAM_API_KEY`
- `OPENAI_API_KEY`
- `CARTESIA_API_KEY`

**Workflow:** `pipecat-bot` runs on port 5000

## Resources

- [Botelier Architecture](botelier/README.md)
- [Pipecat Documentation](https://docs.pipecat.ai)
- [Pipecat GitHub](https://github.com/pipecat-ai/pipecat)

## Recent Changes

- **2024-11-15:** Created Botelier SaaS architecture
  - Set up clean project structure separating SaaS from framework
  - Built voice AI engine wrapper hiding Pipecat as implementation detail
  - Configured 40+ AI providers with full metadata
  - Designed multi-tenant architecture for hotel dashboard

- **2024-11-14:** Initial Pipecat setup
  - Installed Pipecat framework and dependencies
  - Configured quickstart bot workflow

## User Preferences

- **Branding:** All customer-facing code should be branded as "Botelier"
- **Architecture:** Clean separation - Pipecat as hidden dependency
- **Code Quality:** Organized, maintainable, no duplication
- **Future-proof:** Easy to update and extend
