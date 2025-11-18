"""
Botelier Voice AI Provider Configurations

This module defines all available STT, LLM, and TTS providers
that hotels can choose from when configuring their voice agents.
"""

from enum import Enum
from typing import Dict, List, Any
from pydantic import BaseModel, Field


class STTProvider(str, Enum):
    """Speech-to-Text providers available in Botelier"""
    DEEPGRAM = "deepgram"
    OPENAI_WHISPER = "openai_whisper"
    AZURE = "azure"
    ASSEMBLYAI = "assemblyai"
    GOOGLE = "google"
    GROQ = "groq"
    AWS_TRANSCRIBE = "aws_transcribe"
    GLADIA = "gladia"
    ELEVENLABS = "elevenlabs"
    RIVA = "riva"
    SONIOX = "soniox"
    SPEECHMATICS = "speechmatics"
    CARTESIA = "cartesia"
    SARVAM = "sarvam"


class LLMProvider(str, Enum):
    """Large Language Model providers available in Botelier"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE_GEMINI = "google_gemini"
    AZURE_OPENAI = "azure_openai"
    AWS_BEDROCK = "aws_bedrock"
    GROQ = "groq"
    MISTRAL = "mistral"
    TOGETHER = "together"
    DEEPSEEK = "deepseek"
    PERPLEXITY = "perplexity"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    FIREWORKS = "fireworks"
    CEREBRAS = "cerebras"


class TTSProvider(str, Enum):
    """Text-to-Speech providers available in Botelier"""
    CARTESIA = "cartesia"
    ELEVENLABS = "elevenlabs"
    OPENAI = "openai"
    AZURE = "azure"
    GOOGLE = "google"
    AWS_POLLY = "aws_polly"
    DEEPGRAM = "deepgram"
    PLAYHT = "playht"
    LMNT = "lmnt"
    RIME = "rime"
    PIPER = "piper"
    NEUPHONIC = "neuphonic"
    SPEECHMATICS = "speechmatics"
    RIVA = "riva"
    SARVAM = "sarvam"


class ProviderConfig(BaseModel):
    """Base configuration for any AI provider"""
    provider_type: str
    display_name: str
    description: str
    requires_api_key: bool = True
    supported_languages: List[str] = Field(default_factory=list)
    default_model: str = ""
    available_models: List[str] = Field(default_factory=list)


class STTConfig(ProviderConfig):
    """STT-specific configuration"""
    supports_vad: bool = False
    supports_diarization: bool = False
    supports_interim_results: bool = True


class LLMConfig(ProviderConfig):
    """LLM-specific configuration"""
    supports_function_calling: bool = False
    supports_streaming: bool = True
    max_context_tokens: int = 4096
    supports_vision: bool = False


class TTSConfig(ProviderConfig):
    """TTS-specific configuration"""
    available_voices: List[Dict[str, str]] = Field(default_factory=list)
    supports_emotion: bool = False
    supports_speed_control: bool = True
    supports_pitch_control: bool = False


STT_PROVIDERS: Dict[STTProvider, STTConfig] = {
    STTProvider.DEEPGRAM: STTConfig(
        provider_type="stt",
        display_name="Deepgram",
        description="High-accuracy speech recognition with low latency",
        requires_api_key=True,
        supported_languages=["en", "es", "fr", "de", "pt", "ja", "ko", "zh"],
        default_model="nova-3-general",
        available_models=[
            "nova-3-general",
            "nova-3-meeting",
            "nova-3-phonecall",
            "nova-3-voicemail",
            "nova-3-finance",
            "nova-3-medical",
            "nova-2-general",
            "nova-2-meeting",
            "nova-2-phonecall",
            "nova-2-voicemail",
            "flux-general-en",  # Advanced turn detection for conversational AI
        ],
        supports_vad=True,
        supports_diarization=True,
        supports_interim_results=True,
    ),
    STTProvider.OPENAI_WHISPER: STTConfig(
        provider_type="stt",
        display_name="OpenAI Whisper",
        description="OpenAI's speech recognition model",
        requires_api_key=True,
        supported_languages=["en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"],
        default_model="whisper-1",
        available_models=["whisper-1"],
        supports_vad=False,
        supports_diarization=False,
        supports_interim_results=False,
    ),
    STTProvider.ASSEMBLYAI: STTConfig(
        provider_type="stt",
        display_name="AssemblyAI",
        description="Real-time speech recognition with advanced features",
        requires_api_key=True,
        supported_languages=["en"],
        default_model="universal-streaming-english",
        available_models=["universal-streaming-english", "universal-streaming-multilingual"],
        supports_vad=True,
        supports_diarization=True,
        supports_interim_results=True,
    ),
}

LLM_PROVIDERS: Dict[LLMProvider, LLMConfig] = {
    LLMProvider.OPENAI: LLMConfig(
        provider_type="llm",
        display_name="OpenAI",
        description="GPT-4 and GPT-3.5 models for conversational AI",
        requires_api_key=True,
        supported_languages=["en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"],
        default_model="gpt-4o-mini",
        available_models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        supports_function_calling=True,
        supports_streaming=True,
        max_context_tokens=128000,
        supports_vision=True,
    ),
    LLMProvider.ANTHROPIC: LLMConfig(
        provider_type="llm",
        display_name="Anthropic Claude",
        description="Claude models with long context and strong reasoning",
        requires_api_key=True,
        supported_languages=["en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"],
        default_model="claude-3-5-sonnet-20241022",
        available_models=["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"],
        supports_function_calling=True,
        supports_streaming=True,
        max_context_tokens=200000,
        supports_vision=True,
    ),
    LLMProvider.GOOGLE_GEMINI: LLMConfig(
        provider_type="llm",
        display_name="Google Gemini",
        description="Google's multimodal AI models",
        requires_api_key=True,
        supported_languages=["en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"],
        default_model="gemini-2.0-flash-exp",
        available_models=["gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash"],
        supports_function_calling=True,
        supports_streaming=True,
        max_context_tokens=1000000,
        supports_vision=True,
    ),
}

TTS_PROVIDERS: Dict[TTSProvider, TTSConfig] = {
    TTSProvider.DEEPGRAM: TTSConfig(
        provider_type="tts",
        display_name="Deepgram Aura",
        description="Fast, natural-sounding voice synthesis",
        requires_api_key=True,
        supported_languages=["en", "es"],
        default_model="aura-2",
        available_models=["aura-2", "aura-1"],
        available_voices=[
            # Aura-2 voices (latest, professional)
            {"id": "aura-2-helena-en", "name": "Helena (Professional)", "gender": "female"},
            {"id": "aura-2-asteria-en", "name": "Asteria (Friendly)", "gender": "female"},
            {"id": "aura-2-thalia-en", "name": "Thalia (Warm)", "gender": "female"},
            {"id": "aura-2-luna-en", "name": "Luna (Natural)", "gender": "female"},
            {"id": "aura-2-athena-en", "name": "Athena (Professional)", "gender": "female"},
            {"id": "aura-2-hera-en", "name": "Hera (Authoritative)", "gender": "female"},
            {"id": "aura-2-aurora-en", "name": "Aurora (Bright)", "gender": "female"},
            {"id": "aura-2-orpheus-en", "name": "Orpheus (Narrative)", "gender": "male"},
            {"id": "aura-2-orion-en", "name": "Orion (Strong)", "gender": "male"},
            {"id": "aura-2-apollo-en", "name": "Apollo (Clear)", "gender": "male"},
            {"id": "aura-2-zeus-en", "name": "Zeus (Deep)", "gender": "male"},
            {"id": "aura-2-hermes-en", "name": "Hermes (Friendly)", "gender": "male"},
            # Aura-1 voices (original)
            {"id": "aura-asteria-en", "name": "Asteria V1 (Friendly)", "gender": "female"},
            {"id": "aura-luna-en", "name": "Luna V1 (Natural)", "gender": "female"},
            {"id": "aura-athena-en", "name": "Athena V1 (Professional)", "gender": "female"},
            {"id": "aura-orpheus-en", "name": "Orpheus V1 (Narrative)", "gender": "male"},
            {"id": "aura-zeus-en", "name": "Zeus V1 (Deep)", "gender": "male"},
        ],
        supports_emotion=False,
        supports_speed_control=True,
        supports_pitch_control=False,
    ),
    TTSProvider.CARTESIA: TTSConfig(
        provider_type="tts",
        display_name="Cartesia",
        description="Ultra-low latency voice synthesis",
        requires_api_key=True,
        supported_languages=["en", "es", "fr", "de", "pt", "ja", "ko", "zh"],
        default_model="sonic-english",
        available_models=["sonic-english", "sonic-multilingual"],
        available_voices=[
            {"id": "71a7ad14-091c-4e8e-a314-022ece01c121", "name": "British Reading Lady", "gender": "female"},
            {"id": "79a125e8-cd45-4c13-8a67-188112f4dd22", "name": "British Narrator Lady", "gender": "female"},
            {"id": "a0e99841-438c-4a64-b679-ae501e7d6091", "name": "Friendly Reading Man", "gender": "male"},
            {"id": "95856005-0332-41b0-935f-352e296aa0df", "name": "Professional Man", "gender": "male"},
        ],
        supports_emotion=True,
        supports_speed_control=True,
        supports_pitch_control=False,
    ),
    TTSProvider.ELEVENLABS: TTSConfig(
        provider_type="tts",
        display_name="ElevenLabs",
        description="High-quality, expressive voice synthesis",
        requires_api_key=True,
        supported_languages=["en", "es", "fr", "de", "it", "pt", "pl", "hi", "ja", "ko", "zh"],
        default_model="eleven_flash_v2_5",
        available_models=["eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2"],
        available_voices=[
            {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "gender": "male"},
            {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "gender": "female"},
            {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "gender": "female"},
            {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "gender": "female"},
        ],
        supports_emotion=True,
        supports_speed_control=True,
        supports_pitch_control=False,
    ),
    TTSProvider.OPENAI: TTSConfig(
        provider_type="tts",
        display_name="OpenAI TTS",
        description="OpenAI's text-to-speech models",
        requires_api_key=True,
        supported_languages=["en", "es", "fr", "de", "it", "pt", "nl", "pl", "ru", "ja", "ko", "zh"],
        default_model="tts-1",
        available_models=["tts-1", "tts-1-hd"],
        available_voices=[
            {"id": "alloy", "name": "Alloy", "gender": "neutral"},
            {"id": "echo", "name": "Echo", "gender": "male"},
            {"id": "fable", "name": "Fable", "gender": "neutral"},
            {"id": "onyx", "name": "Onyx", "gender": "male"},
            {"id": "nova", "name": "Nova", "gender": "female"},
            {"id": "shimmer", "name": "Shimmer", "gender": "female"},
        ],
        supports_emotion=False,
        supports_speed_control=True,
        supports_pitch_control=False,
    ),
}


def get_provider_config(provider_type: str, provider_name: str) -> ProviderConfig:
    """Get configuration for a specific provider"""
    if provider_type == "stt":
        return STT_PROVIDERS.get(STTProvider(provider_name))
    elif provider_type == "llm":
        return LLM_PROVIDERS.get(LLMProvider(provider_name))
    elif provider_type == "tts":
        return TTS_PROVIDERS.get(TTSProvider(provider_name))
    raise ValueError(f"Unknown provider type: {provider_type}")


def is_flux_model(model: str) -> bool:
    """Check if a Deepgram model is Flux"""
    return model and model.startswith("flux-")


# Provider-specific parameter schemas (matching Pipecat's InputParams)
PROVIDER_PARAMS = {
    "stt": {
        "deepgram_standard": {
            "punctuate": {"type": "boolean", "default": True, "label": "Punctuate"},
            "profanity_filter": {"type": "boolean", "default": True, "label": "Profanity Filter"},
            "smart_format": {"type": "boolean", "default": True, "label": "Smart Format"},
            "vad_events": {"type": "boolean", "default": False, "label": "VAD Events"},
        },
        "deepgram_flux": {
            "eager_eot_threshold": {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.1,
                "default": None,
                "label": "Eager End-of-Turn Threshold",
                "description": "Lower = faster response, more LLM calls"
            },
            "eot_threshold": {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.1,
                "default": 0.7,
                "label": "End-of-Turn Threshold"
            },
            "eot_timeout_ms": {
                "type": "number",
                "min": 1000,
                "max": 10000,
                "step": 500,
                "default": 5000,
                "label": "End-of-Turn Timeout (ms)"
            },
        },
    },
    "llm": {
        "openai": {
            "frequency_penalty": {
                "type": "number",
                "min": -2.0,
                "max": 2.0,
                "step": 0.1,
                "default": 0.0,
                "label": "Frequency Penalty",
                "description": "Reduces token repetition based on frequency"
            },
            "presence_penalty": {
                "type": "number",
                "min": -2.0,
                "max": 2.0,
                "step": 0.1,
                "default": 0.0,
                "label": "Presence Penalty",
                "description": "Reduces repetition of any tokens"
            },
            "top_p": {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "default": 1.0,
                "label": "Top P"
            },
        },
        "anthropic": {
            "top_k": {
                "type": "number",
                "min": 0,
                "max": 500,
                "step": 10,
                "default": 0,
                "label": "Top K"
            },
            "top_p": {
                "type": "number",
                "min": 0.0,
                "max": 1.0,
                "step": 0.05,
                "default": 1.0,
                "label": "Top P"
            },
            "enable_prompt_caching": {
                "type": "boolean",
                "default": False,
                "label": "Enable Prompt Caching",
                "description": "Cache system prompts for 50% cost savings"
            },
        },
    },
}
