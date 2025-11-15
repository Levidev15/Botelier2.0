"""
Botelier Voice Engine Implementation

This module contains the actual implementation that uses Pipecat.
This is an internal module - hotel developers don't interact with this directly.
"""

import os
from typing import Optional, Dict, Any

from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

from .agent import VoiceAgentConfig


class VoiceEngineFactory:
    """
    Factory for creating voice AI pipelines
    
    This encapsulates all Pipecat-specific code.
    Hotels never see this - they only interact with VoiceAgent.
    """
    
    @staticmethod
    def create_stt_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create STT service based on provider configuration"""
        provider = config.stt_provider.lower()
        
        if provider == "deepgram":
            return DeepgramSTTService(
                api_key=api_keys.get("deepgram_api_key"),
                **config.stt_config
            )
        elif provider == "openai_whisper":
            from pipecat.services.openai.stt import OpenAISTTService
            return OpenAISTTService(
                api_key=api_keys.get("openai_api_key"),
                model=config.stt_model or "whisper-1",
                language=config.stt_language,
                **config.stt_config
            )
        elif provider == "assemblyai":
            from pipecat.services.assemblyai import AssemblyAISTTService
            return AssemblyAISTTService(
                api_key=api_keys.get("assemblyai_api_key"),
                **config.stt_config
            )
        else:
            raise ValueError(f"Unsupported STT provider: {provider}")
    
    @staticmethod
    def create_llm_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create LLM service based on provider configuration"""
        provider = config.llm_provider.lower()
        
        params = {
            "temperature": config.llm_temperature,
            "max_tokens": config.llm_max_tokens,
            **config.llm_config
        }
        
        if provider == "openai":
            return OpenAILLMService(
                api_key=api_keys.get("openai_api_key"),
                model=config.llm_model,
                **params
            )
        elif provider == "anthropic":
            return AnthropicLLMService(
                api_key=api_keys.get("anthropic_api_key"),
                model=config.llm_model,
                **params
            )
        elif provider == "google_gemini":
            from pipecat.services.google.llm import GoogleLLMService
            return GoogleLLMService(
                api_key=api_keys.get("google_api_key"),
                model=config.llm_model,
                **params
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    @staticmethod
    def create_tts_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create TTS service based on provider configuration"""
        provider = config.tts_provider.lower()
        
        if provider == "cartesia":
            return CartesiaTTSService(
                api_key=api_keys.get("cartesia_api_key"),
                voice_id=config.tts_voice_id,
                **config.tts_config
            )
        elif provider == "elevenlabs":
            return ElevenLabsTTSService(
                api_key=api_keys.get("elevenlabs_api_key"),
                voice_id=config.tts_voice_id,
                **config.tts_config
            )
        elif provider == "openai":
            return OpenAITTSService(
                api_key=api_keys.get("openai_api_key"),
                voice=config.tts_voice_id,
                **config.tts_config
            )
        else:
            raise ValueError(f"Unsupported TTS provider: {provider}")
    
    @staticmethod
    def create_pipeline(
        config: VoiceAgentConfig,
        api_keys: Dict[str, str],
        transport
    ) -> tuple[Pipeline, PipelineTask]:
        """
        Create complete voice pipeline from agent configuration
        
        This is where Pipecat is actually used, but it's completely hidden
        from the hotel-facing API.
        """
        
        stt = VoiceEngineFactory.create_stt_service(config, api_keys)
        llm = VoiceEngineFactory.create_llm_service(config, api_keys)
        tts = VoiceEngineFactory.create_tts_service(config, api_keys)
        
        messages = [
            {
                "role": "system",
                "content": config.system_prompt,
            },
        ]
        
        context = LLMContext(messages)
        context_aggregator = LLMContextAggregatorPair(context)
        
        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                tts,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )
        
        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
        )
        
        return pipeline, task
    
    @staticmethod
    def create_transport_params(config: VoiceAgentConfig):
        """Create transport parameters based on agent config"""
        from pipecat.transports.base_transport import TransportParams
        
        params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
        
        if config.enable_vad:
            params.vad_analyzer = SileroVADAnalyzer(
                params=VADParams(stop_secs=0.2)
            )
            params.turn_analyzer = LocalSmartTurnAnalyzerV3()
        
        return params
