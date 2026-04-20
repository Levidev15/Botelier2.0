# `components/forms/` — Form primitives + assistant config

## Purpose

Shared form building blocks plus the largest config form in the app (assistant configuration).

## Main files

| File | Role |
|---|---|
| `FormSection.tsx` | Collapsible labeled section wrapper for grouped fields. |
| `FormField.tsx` | Field primitive (label + input + help text + error). |
| `AssistantConfigForm.tsx` | Multi-section assistant editor (provider, voice, prompts, dispositions, post-call QA). |
| `ProviderSelector.tsx` | STT / LLM / TTS provider+model+voice picker; reads catalog from `api/providers.py`. |
| `DispositionsTab.tsx` | Disposition + resolution-option editor for an assistant. |
| `PostCallQATab.tsx` | After-call QA configuration. |
| `GreetingCacheButton.tsx` | Triggers a backend regenerate of the cached greeting PCM (`voice/greeting_cache.py`). |

## How it connects

- Consumed by `app/(dashboard)/dashboard/assistants/[id]/...`.
- `ProviderSelector` reads the catalog defined in `botelier/backend/botelier/config/providers.py` via `api/providers.py`.
- `GreetingCacheButton` invalidates the per-assistant greeting cache used by `voice/greeting_cache.py` at call time.

## Conventions

- Compose `FormSection` > `FormField`; don't reach for a different pattern.
- All save buttons use `components/ui/SaveBar.tsx` for consistent sticky-footer behaviour.

## Setup

No standalone setup.

## Gotchas

- Changing a provider/model/voice for an existing assistant doesn't auto-regenerate the cached greeting — the user has to click `GreetingCacheButton`. The first call afterwards would otherwise play a stale greeting.
