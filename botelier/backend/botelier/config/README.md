# `config/` — Static catalogs

## Purpose

Read-only catalogs that drive UI dropdowns and pipeline factories.

## Main files

| File | Role |
|---|---|
| `providers.py` | STT / LLM / TTS provider catalog: enums, models, voices, languages, capability flags. Consumed by `api/providers.py` for the dashboard and by `voice/engine.py` for pipeline construction. |
| `domain.py` | Domain constants (canonical email/domain handling, app URLs). |

## How it connects

- `api/providers.py` exposes this catalog read-only to the frontend.
- `voice/engine.py` factory branches off provider enums declared here.

## Conventions

- Adding a provider = enum entry + provider config (models, voices, languages, capabilities). The factory in `voice/engine.py` must learn how to construct the matching Pipecat service.

## Setup

Static — no setup.

## Gotchas

- Renaming an enum value will break every assistant currently configured with it. The startup migration in `main.py:117-133` is an example of how to handle a forced rename (Deepgram model fixup).
