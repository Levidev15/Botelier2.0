# `schemas/` — Pydantic + tool schemas

## Purpose

Holds non-ORM type definitions: tool/JSON-schema descriptors used by the LLM function-calling layer and shared Pydantic helpers.

## Main files

| File | Role |
|---|---|
| `tool_schemas.py` | JSON-schema descriptors for tool inputs (consumed by `voice/function_mapper.py` and `api/tools.py`). |

## How it connects

- `voice/function_mapper.py` reads tool descriptors here when mapping LLM tool-call payloads to Python executors.
- `api/tools.py` and `api/api_tester.py` validate user-supplied tool definitions against shapes declared here.

## Conventions

- Pydantic v2.
- Per-route request/response models live next to the route in `api/*.py` when small; reusable shapes go here.

## Setup

No standalone setup — imported as `botelier.schemas.*`.

## Gotchas

- Tool schema changes ripple into the LLM prompt — bumping a tool description here can change LLM behaviour subtly. Verify against `voice/function_mapper.py` callers before merging.
