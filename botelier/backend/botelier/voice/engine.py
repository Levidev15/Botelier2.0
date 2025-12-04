"""
Botelier Voice Engine Implementation

This module contains the actual implementation that uses Pipecat.
This is an internal module - hotel developers don't interact with this directly.

Key Design Principle:
- Uses Pipecat's proper InputParams classes for type safety
- Maps database configuration to Pipecat's expected parameters
- Supports provider-specific features (Flux STT, prompt caching, etc.)
"""

import os
from typing import Optional, Dict, Any
from loguru import logger

# Lazy imports for provider services to avoid startup issues with optional dependencies
# Services will be imported only when actually used
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.transcriptions.language import Language

from .agent import VoiceAgentConfig
from ..config.providers import is_flux_model

try:
    from deepgram import LiveOptions
except ImportError:
    LiveOptions = None


class VoiceEngineFactory:
    """
    Factory for creating voice AI pipelines
    
    This encapsulates all Pipecat-specific code.
    Hotels never see this - they only interact with VoiceAgent.
    """
    
    @staticmethod
    def create_stt_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create STT service using Pipecat's proper configuration classes"""
        provider = config.stt_provider.lower()
        model = config.stt_model or "nova-3-general"
        
        if provider == "deepgram":
            from pipecat.services.deepgram.stt import DeepgramSTTService
            from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
            
            # Check if using Flux model (advanced turn detection)
            if is_flux_model(model):
                # Use Deepgram Flux with proper InputParams
                params = DeepgramFluxSTTService.InputParams(
                    eager_eot_threshold=config.stt_config.get("eager_eot_threshold"),
                    eot_threshold=config.stt_config.get("eot_threshold", 0.7),
                    eot_timeout_ms=config.stt_config.get("eot_timeout_ms", 5000),
                    keyterm=config.stt_config.get("keyterm", []),
                    tag=config.stt_config.get("tag", []),
                )
                return DeepgramFluxSTTService(
                    api_key=api_keys.get("deepgram_api_key"),
                    model=model,
                    params=params,
                )
            else:
                # Use standard Deepgram with LiveOptions
                live_options = LiveOptions(
                    model=model,
                    language=config.stt_language,
                    punctuate=config.stt_config.get("punctuate", True),
                    smart_format=config.stt_config.get("smart_format", True),
                    profanity_filter=config.stt_config.get("profanity_filter", True),
                    vad_events=config.stt_config.get("vad_events", False),
                    interim_results=True,
                )
                return DeepgramSTTService(
                    api_key=api_keys.get("deepgram_api_key"),
                    live_options=live_options,
                )
        elif provider == "openai_whisper":
            from pipecat.services.openai.stt import OpenAISTTService
            return OpenAISTTService(
                api_key=api_keys.get("openai_api_key"),
                model=model or "whisper-1",
                language=config.stt_language,
            )
        elif provider == "assemblyai":
            from pipecat.services.assemblyai import AssemblyAISTTService
            return AssemblyAISTTService(
                api_key=api_keys.get("assemblyai_api_key"),
            )
        else:
            raise ValueError(f"Unsupported STT provider: {provider}")
    
    @staticmethod
    def create_llm_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create LLM service using Pipecat's proper InputParams classes"""
        provider = config.llm_provider.lower()
        
        if provider == "openai":
            from pipecat.services.openai.llm import OpenAILLMService
            from pipecat.services.openai.base_llm import BaseOpenAILLMService
            # Use OpenAI's InputParams with provider-specific parameters
            params = BaseOpenAILLMService.InputParams(
                temperature=config.llm_temperature,
                max_completion_tokens=config.llm_max_tokens,
                frequency_penalty=config.llm_config.get("frequency_penalty", 0.0),
                presence_penalty=config.llm_config.get("presence_penalty", 0.0),
                top_p=config.llm_config.get("top_p", 1.0),
            )
            return OpenAILLMService(
                api_key=api_keys.get("openai_api_key"),
                model=config.llm_model,
                params=params,
            )
        elif provider == "anthropic":
            # TODO: Anthropic support temporarily disabled due to SDK installation issues
            # Will be re-enabled once anthropic package is properly installed in Replit environment
            raise ValueError(
                "Anthropic LLM provider is temporarily unavailable. "
                "Please use OpenAI or Google Gemini instead."
            )
        elif provider == "google_gemini":
            from pipecat.services.google.llm import GoogleLLMService
            return GoogleLLMService(
                api_key=api_keys.get("google_api_key"),
                model=config.llm_model,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    @staticmethod
    def create_tts_service(config: VoiceAgentConfig, api_keys: Dict[str, str]):
        """Create TTS service using Pipecat's configuration"""
        provider = config.tts_provider.lower()
        
        if provider == "deepgram":
            from pipecat.services.deepgram.tts import DeepgramTTSService
            return DeepgramTTSService(
                api_key=api_keys.get("deepgram_api_key"),
                voice=config.tts_voice_id or "aura-2-helena-en",
                encoding=config.tts_config.get("encoding", "linear16"),
            )
        elif provider == "cartesia":
            from pipecat.services.cartesia.tts import CartesiaTTSService
            return CartesiaTTSService(
                api_key=api_keys.get("cartesia_api_key"),
                voice_id=config.tts_voice_id,
            )
        elif provider == "elevenlabs":
            from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
            return ElevenLabsTTSService(
                api_key=api_keys.get("elevenlabs_api_key"),
                voice_id=config.tts_voice_id,
            )
        elif provider == "openai":
            from pipecat.services.openai.tts import OpenAITTSService
            return OpenAITTSService(
                api_key=api_keys.get("openai_api_key"),
                voice=config.tts_voice_id or "alloy",
            )
        else:
            raise ValueError(f"Unsupported TTS provider: {provider}")
    
    @staticmethod
    def create_pipeline(
        config: VoiceAgentConfig,
        api_keys: Dict[str, str],
        transport,
        function_schemas: Optional[list] = None,
        function_handlers: Optional[Dict[str, Any]] = None,
    ) -> tuple[Pipeline, PipelineTask, Any, Any, Any]:
        """
        Create complete voice pipeline from agent configuration
        
        This is where Pipecat is actually used, but it's completely hidden
        from the hotel-facing API.
        
        Args:
            config: Voice agent configuration
            api_keys: API keys for external services
            transport: WebSocket transport
            function_schemas: Optional list of FunctionSchema objects for function calling
            function_handlers: Optional dict mapping function names to async handlers
            
        Returns:
            Tuple of (pipeline, task, llm, context_aggregator, context) for external access
            The context is returned separately for transcript extraction
        """
        from pipecat.adapters.schemas.tools_schema import ToolsSchema
        
        stt = VoiceEngineFactory.create_stt_service(config, api_keys)
        llm = VoiceEngineFactory.create_llm_service(config, api_keys)
        tts = VoiceEngineFactory.create_tts_service(config, api_keys)
        
        messages = [
            {
                "role": "system",
                "content": config.system_prompt,
            },
        ]
        
        # Create context with tools if schemas provided
        if function_schemas:
            tools = ToolsSchema(standard_tools=function_schemas)
            context = LLMContext(messages, tools=tools)
        else:
            context = LLMContext(messages)
        
        context_aggregator = LLMContextAggregatorPair(context)
        
        # Register function handlers with LLM
        if function_handlers:
            for function_name, handler in function_handlers.items():
                llm.register_function(function_name, handler)
        
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
        
        return pipeline, task, llm, context_aggregator, context
    
    @staticmethod
    def create_transport_params(config: VoiceAgentConfig):
        """Create transport parameters based on agent config"""
        from pipecat.transports.base_transport import TransportParams
        from pipecat.audio.vad.vad_analyzer import VADParams
        
        params = TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
        
        if config.enable_vad and config.vad_provider:
            vad_config = config.vad_config or {}
            
            try:
                if config.vad_provider == "silero":
                    from pipecat.audio.vad.silero import SileroVADAnalyzer
                    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
                    
                    vad_params = VADParams(
                        confidence=vad_config.get("confidence", 0.5),
                        start_secs=vad_config.get("start_secs", 0.0),
                        stop_secs=vad_config.get("stop_secs", 0.2),
                        min_volume=vad_config.get("min_volume", 0.0)
                    )
                    params.vad_analyzer = SileroVADAnalyzer(params=vad_params)
                    params.turn_analyzer = LocalSmartTurnAnalyzerV3()
                    logger.info(f"Silero VAD enabled with params: {vad_params}")
                    
                elif config.vad_provider == "webrtc":
                    from pipecat.transports.daily.transport import WebRTCVADAnalyzer
                    
                    vad_params = VADParams(
                        confidence=vad_config.get("confidence", 0.5),
                        start_secs=vad_config.get("start_secs", 0.0),
                        stop_secs=vad_config.get("stop_secs", 0.2),
                        min_volume=vad_config.get("min_volume", 0.0)
                    )
                    params.vad_analyzer = WebRTCVADAnalyzer(params=vad_params)
                    logger.info(f"WebRTC VAD enabled with params: {vad_params}")
                    
                elif config.vad_provider == "aic":
                    from pipecat.audio.vad.aic_vad import AICVADAnalyzer
                    
                    lookback_buffer_size = vad_config.get("lookback_buffer_size")
                    sensitivity = vad_config.get("sensitivity")
                    params.vad_analyzer = AICVADAnalyzer(
                        lookback_buffer_size=lookback_buffer_size,
                        sensitivity=sensitivity
                    )
                    logger.info(f"AIC VAD enabled with lookback={lookback_buffer_size}, sensitivity={sensitivity}")
                    
                else:
                    logger.warning(f"Unknown VAD provider '{config.vad_provider}', VAD disabled")
                    
            except ImportError as e:
                logger.warning(f"VAD provider '{config.vad_provider}' not available (missing dependencies): {e}")
                logger.info("Continuing without VAD. Install dependencies or disable VAD in assistant settings.")
        
        return params
