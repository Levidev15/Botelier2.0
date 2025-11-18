"""
Providers API - Returns available AI providers and their configurations.

This endpoint provides frontend with provider options, models, voices, and parameters.
"""

from typing import Optional
from fastapi import APIRouter, Query

from botelier.config.providers import (
    STT_PROVIDERS,
    LLM_PROVIDERS,
    TTS_PROVIDERS,
    PROVIDER_PARAMS,
    is_flux_model,
)


router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("/stt")
async def get_stt_providers():
    """
    Get all available STT providers with their models and parameters.
    
    Returns provider configurations that map to Pipecat's STTService implementations.
    """
    providers_data = {}
    
    for provider_enum, config in STT_PROVIDERS.items():
        provider_id = provider_enum.value
        provider_data = {
            "id": provider_id,
            "display_name": config.display_name,
            "description": config.description,
            "default_model": config.default_model,
            "models": [
                {
                    "value": model,
                    "label": model.replace("-", " ").title(),
                    "is_flux": is_flux_model(model),
                }
                for model in config.available_models
            ],
            "supported_languages": config.supported_languages,
        }
        
        # Only include Deepgram-specific params for Deepgram
        if provider_id == "deepgram":
            provider_data["standard_params"] = PROVIDER_PARAMS["stt"].get("deepgram_standard", {})
            provider_data["flux_params"] = PROVIDER_PARAMS["stt"].get("deepgram_flux", {})
        
        providers_data[provider_id] = provider_data
    
    return {"providers": providers_data}


@router.get("/llm")
async def get_llm_providers():
    """
    Get all available LLM providers with their models and parameters.
    
    Returns provider configurations that map to Pipecat's LLMService implementations.
    """
    providers_data = {}
    
    for provider_enum, config in LLM_PROVIDERS.items():
        provider_id = provider_enum.value
        providers_data[provider_id] = {
            "id": provider_id,
            "display_name": config.display_name,
            "description": config.description,
            "default_model": config.default_model,
            "models": [
                {"value": model, "label": model}
                for model in config.available_models
            ],
            "supported_languages": config.supported_languages,
            "max_context_tokens": config.max_context_tokens,
            "supports_function_calling": config.supports_function_calling,
            "supports_vision": config.supports_vision,
            "params": PROVIDER_PARAMS["llm"].get(provider_id, {}),
        }
    
    return {"providers": providers_data}


@router.get("/tts")
async def get_tts_providers(model: Optional[str] = Query(None, description="Filter voices by model")):
    """
    Get all available TTS providers with their models and voices.
    
    Returns provider configurations that map to Pipecat's TTSService implementations.
    For providers like Deepgram Aura where voices are model-specific, voices are grouped by model.
    """
    providers_data = {}
    
    for provider_enum, config in TTS_PROVIDERS.items():
        provider_id = provider_enum.value
        
        # Organize models
        models_list = [{"value": m, "label": m} for m in config.available_models]
        
        # Organize voices based on provider
        if provider_id == "deepgram":
            # Deepgram voices are model-specific (aura-2-helena-en belongs to aura-2)
            voices_by_model = {}
            for voice in config.available_voices:
                voice_id = voice["id"]
                # Determine which model this voice belongs to
                if voice_id.startswith("aura-2-"):
                    model_key = "aura-2"
                elif voice_id.startswith("aura-"):
                    model_key = "aura-1"
                else:
                    model_key = config.default_model
                
                if model_key not in voices_by_model:
                    voices_by_model[model_key] = []
                voices_by_model[model_key].append({
                    "value": voice_id,
                    "label": voice["name"],
                    "gender": voice.get("gender"),
                })
            
            providers_data[provider_id] = {
                "id": provider_id,
                "display_name": config.display_name,
                "description": config.description,
                "default_model": config.default_model,
                "models": models_list,
                "voices_by_model": voices_by_model,
                "supported_languages": config.supported_languages,
                "supports_emotion": config.supports_emotion,
                "supports_speed_control": config.supports_speed_control,
            }
        else:
            # Other providers: voices work with all models
            voices_list = [
                {
                    "value": voice["id"],
                    "label": voice["name"],
                    "gender": voice.get("gender"),
                }
                for voice in config.available_voices
            ]
            
            providers_data[provider_id] = {
                "id": provider_id,
                "display_name": config.display_name,
                "description": config.description,
                "default_model": config.default_model,
                "models": models_list,
                "voices": voices_list,  # All voices work with all models
                "supported_languages": config.supported_languages,
                "supports_emotion": config.supports_emotion,
                "supports_speed_control": config.supports_speed_control,
            }
    
    return {"providers": providers_data}


@router.get("/stt/{provider_id}")
async def get_stt_provider(provider_id: str):
    """Get detailed configuration for a specific STT provider."""
    provider_enum = None
    for p in STT_PROVIDERS.keys():
        if p.value == provider_id:
            provider_enum = p
            break
    
    if not provider_enum or provider_enum not in STT_PROVIDERS:
        return {"error": "Provider not found"}, 404
    
    config = STT_PROVIDERS[provider_enum]
    return {
        "id": provider_id,
        "display_name": config.display_name,
        "description": config.description,
        "default_model": config.default_model,
        "models": config.available_models,
        "supported_languages": config.supported_languages,
        "params": PROVIDER_PARAMS["stt"].get(f"{provider_id}_standard", {}),
    }


@router.get("/llm/{provider_id}")
async def get_llm_provider(provider_id: str):
    """Get detailed configuration for a specific LLM provider."""
    provider_enum = None
    for p in LLM_PROVIDERS.keys():
        if p.value == provider_id:
            provider_enum = p
            break
    
    if not provider_enum or provider_enum not in LLM_PROVIDERS:
        return {"error": "Provider not found"}, 404
    
    config = LLM_PROVIDERS[provider_enum]
    return {
        "id": provider_id,
        "display_name": config.display_name,
        "description": config.description,
        "default_model": config.default_model,
        "models": config.available_models,
        "params": PROVIDER_PARAMS["llm"].get(provider_id, {}),
    }


@router.get("/tts/{provider_id}")
async def get_tts_provider(provider_id: str):
    """Get detailed configuration for a specific TTS provider."""
    provider_enum = None
    for p in TTS_PROVIDERS.keys():
        if p.value == provider_id:
            provider_enum = p
            break
    
    if not provider_enum or provider_enum not in TTS_PROVIDERS:
        return {"error": "Provider not found"}, 404
    
    config = TTS_PROVIDERS[provider_enum]
    return {
        "id": provider_id,
        "display_name": config.display_name,
        "description": config.description,
        "voices": config.available_voices,
    }
