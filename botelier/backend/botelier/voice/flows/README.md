# `voice/flows/` — Conversation-flow runtime

## Purpose

Executes the visual conversation flows that hotels build in the dashboard's flow editor. Drives the LLM with a state machine of nodes (initial, message, collect-slot, condition, router, API request, transfer, end, …) instead of a single static system prompt.

## Main files

| File | Role |
|---|---|
| `engine.py` | Flow runtime: state machine, slot tracking, node transitions, condition evaluation. |
| `templates.py` | Built-in starter templates exposed via `api/flow_templates.py`. |
| `__init__.py` | Public surface for `flow_executor.py` and `voice/call_handler.py`. |

## How it connects

- Loaded by `flow_executor.py` (one level up) when an assistant has an active `FlowVersion`.
- Persisted via `models/flow_version.py`; CRUD through `api/flow_versions.py`.
- Frontend editor in `frontend/components/flow-editor/`. The node types and inspector panels there must stay in sync with the runtime's expected schema.

## Conventions

- One node = one transition decision. Side effects (API calls, variable sets) happen as part of the node, not in a wrapper.
- Slot collection is durable across LLM turns via the runtime's slot store.

## Setup

No standalone runner — invoked from the voice pipeline.

## Gotchas

- A frontend node type without a runtime handler will surface as a no-op node in production. Adding a node = code in BOTH this folder and `frontend/components/flow-editor/nodes/` + `inspectors/`.
