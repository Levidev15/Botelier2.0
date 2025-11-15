# Botelier - Hotel Voice AI Platform

**Multi-tenant SaaS platform for hotel voice AI agents**

## Architecture Overview

Botelier is structured as a clean, professional SaaS application that uses modern voice AI infrastructure under the hood. The codebase is organized to ensure:

- **95% Botelier-branded code** - Developers work with Botelier interfaces
- **Voice AI framework as dependency** - Hidden implementation detail
- **Clean separation of concerns** - SaaS logic separate from voice engine
- **Easy maintenance** - Clear boundaries for future updates

## Project Structure

```
botelier/
├── frontend/              # Next.js hotel dashboard
│   ├── app/              # Next.js 14 App Router
│   ├── components/       # React components
│   └── lib/              # Utilities and hooks
│
├── backend/              # FastAPI Python server
│   └── botelier/         # Main application package
│       ├── api/          # REST API endpoints
│       ├── models/       # Database models
│       ├── voice/        # Voice AI engine (Pipecat wrapper)
│       ├── auth/         # Authentication
│       ├── integrations/ # Hotel system integrations
│       └── config/       # Configuration
│
└── database/             # Database migrations & schemas
```

## Voice Engine Architecture

### Hotel-Facing API (What developers see)

```python
from botelier.voice import VoiceAgent, VoiceAgentConfig

# Clean, Botelier-branded interface
agent = VoiceAgent(VoiceAgentConfig(
    agent_id="concierge-1",
    hotel_id="hotel-123",
    name="Concierge Agent",
    stt_provider="deepgram",
    llm_provider="openai",
    llm_model="gpt-4o-mini",
    tts_provider="cartesia",
    system_prompt="You are a hotel concierge...",
))
```

### Implementation Layer (Hidden from developers)

The `botelier/backend/botelier/voice/` module wraps Pipecat as an implementation detail:

- `agent.py` - Clean VoiceAgent interface (what hotels use)
- `engine.py` - Pipecat integration (internal implementation)
- `orchestrator.py` - Multi-agent session management
- `session.py` - Call session tracking

## Configuration System

All AI provider configurations are defined in `botelier/backend/botelier/config/providers.py`:

### Supported Providers

**STT (Speech-to-Text):**
- Deepgram, OpenAI Whisper, AssemblyAI, Azure, Google, Groq, AWS Transcribe, and more

**LLM (Language Models):**
- OpenAI, Anthropic Claude, Google Gemini, Azure OpenAI, AWS Bedrock, Groq, Mistral, and more

**TTS (Text-to-Speech):**
- Cartesia, ElevenLabs, OpenAI, Azure, Google, AWS Polly, Deepgram, PlayHT, and more

Each provider includes:
- Display name and description
- Available models and voices
- Supported languages
- Feature capabilities (VAD, function calling, emotions, etc.)

## Benefits of This Architecture

### 1. **Clean Separation**
- SaaS business logic stays in `botelier/`
- Voice AI framework stays in `src/pipecat/`
- Clear boundaries, no mixing

### 2. **Maintainability**
- Update Pipecat framework without touching hotel-facing code
- Hotels upgrade by updating dependency, not rewriting code
- Bug fixes in one place

### 3. **Developer Experience**
- Developers see "Botelier" brand throughout
- Simple, consistent API
- No framework internals exposed

### 4. **Future-Proof**
- Can swap underlying implementations if needed
- Business logic independent of voice engine
- Easy to add new providers

## Development Workflow

### Adding a New AI Provider

1. Add provider enum to `config/providers.py`
2. Add provider config with models/voices
3. Implement factory method in `voice/engine.py`
4. Provider automatically available in dashboard

### Updating Pipecat Framework

```bash
# Update dependency
pip install --upgrade pipecat-ai

# No other changes needed - wrapper isolates changes
```

## Next Steps

1. **Database Schema** - Multi-tenant PostgreSQL with RLS
2. **FastAPI Backend** - REST API for agent management
3. **Next.js Frontend** - Hotel dashboard for configuration
4. **Authentication** - NextAuth.js with RBAC
5. **Deployment** - Production-ready setup

## License

Proprietary - Botelier Platform
