# Pipecat - Voice & Multimodal AI Framework

## Overview

**Pipecat** is an open-source Python framework for building real-time voice and multimodal conversational AI agents. This Replit environment is configured to run the Pipecat quickstart bot, which demonstrates building a voice AI assistant that can interact with users through their browser.

## Project Structure

- `src/pipecat/` - Core Pipecat framework source code
- `examples/quickstart/` - Quickstart bot example (currently running)
- `examples/foundational/` - Educational examples building on each other
- `docs/` - API documentation
- `scripts/` - Utility scripts

## Current State

The quickstart bot is configured and ready to run. The workflow automatically starts the bot server on port 5000 when you start the Repl.

### What's Running

- **Bot:** Quickstart voice AI assistant
- **Port:** 5000 (webview accessible)
- **Transport:** WebRTC (browser-based)
- **Services Required:**
  - Deepgram (Speech-to-Text)
  - OpenAI (LLM)
  - Cartesia (Text-to-Speech)

## Setup Instructions

### 1. Configure API Keys

Before the bot can work, you need to add API keys for the AI services. Copy the example environment file and add your keys:

```bash
cp .env.example examples/quickstart/.env
```

Then edit `examples/quickstart/.env` and add your API keys:

```ini
DEEPGRAM_API_KEY=your_deepgram_api_key
OPENAI_API_KEY=your_openai_api_key
CARTESIA_API_KEY=your_cartesia_api_key
```

**Getting API Keys:**
- [Deepgram](https://console.deepgram.com/signup) - Free tier available
- [OpenAI](https://platform.openai.com/signup) - Free credits for new users
- [Cartesia](https://play.cartesia.ai/sign-up) - Free tier available

### 2. Restart the Workflow

After adding your API keys, restart the workflow to apply the changes:
- Click the "Restart" button in the workflow panel, or
- Run: `cd examples/quickstart && python bot.py --host 0.0.0.0 --port 5000`

### 3. Access the Bot

Once the workflow is running with valid API keys:
1. Open the webview preview in Replit
2. Allow microphone access when prompted
3. Click "Connect" to start talking with your bot

## Architecture

### Services Used

- **STT (Speech-to-Text):** Deepgram - converts user speech to text
- **LLM (Language Model):** OpenAI GPT - generates intelligent responses
- **TTS (Text-to-Speech):** Cartesia - converts bot responses to natural speech
- **VAD (Voice Activity Detection):** Silero - detects when user is speaking
- **Turn Detection:** Local Smart Turn Analyzer V3 - manages conversation flow

### Pipeline Flow

```
User Speech → STT (Deepgram) → LLM (OpenAI) → TTS (Cartesia) → Audio Output
```

## Customization

### Modify the Bot Personality

Edit `examples/quickstart/bot.py` around line 74-78 to change the system prompt:

```python
messages = [
    {
        "role": "system",
        "content": "Your custom personality here...",
    },
]
```

### Change Voice

Edit line 69 in `bot.py` to use a different Cartesia voice:

```python
tts = CartesiaTTSService(
    api_key=os.getenv("CARTESIA_API_KEY"),
    voice_id="your_voice_id_here",
)
```

Browse available voices at [Cartesia Voice Library](https://docs.cartesia.ai/reference/voices)

### Switch AI Services

Pipecat supports many different AI services. Check the documentation to swap:
- LLM: Anthropic, Google Gemini, Groq, etc.
- TTS: ElevenLabs, PlayHT, Azure, etc.
- STT: AssemblyAI, Google, Azure, etc.

## Development

### Installing New Dependencies

If you need to add Pipecat features or services:

```bash
pip install "pipecat-ai[service-name]"
```

Available services: anthropic, assemblyai, azure, elevenlabs, google, groq, and many more.

### Running Examples

To run other examples from the foundational folder:

```bash
cd examples/foundational
python example-name.py
```

Note: Most foundational examples use different ports or transports, so you may need to adjust the workflow.

## Troubleshooting

### Bot Not Responding

1. Check that all API keys are set in `examples/quickstart/.env`
2. Restart the workflow
3. Check the logs for error messages
4. Verify microphone permissions in browser

### Audio Issues

1. Ensure microphone is not muted
2. Check browser permissions for microphone access
3. Try a different browser (Chrome/Edge recommended)

### Connection Issues

1. Verify the workflow is running (check status in Replit)
2. Make sure you're accessing the correct webview URL
3. Check that port 5000 is responding

## Resources

- [Official Documentation](https://docs.pipecat.ai)
- [GitHub Repository](https://github.com/pipecat-ai/pipecat)
- [Discord Community](https://discord.gg/pipecat)
- [Example Projects](https://github.com/pipecat-ai/pipecat-examples)

## Recent Changes

- **2024-11-14:** Initial Replit setup
  - Installed Python 3.12 and all dependencies
  - Configured workflow to run on port 5000
  - Set up quickstart bot for WebRTC transport
  - Added environment configuration templates

## User Preferences

None set yet - add your coding preferences and workflow preferences here as you work on the project.
