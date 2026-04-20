# `components/flow-simulator/` — In-browser flow simulator

## Purpose

Lets a hotel test a conversation flow without placing a real call. Steps through nodes, displays slot state, simulates user replies.

## Main files

| File | Role |
|---|---|
| `FlowSimulatorSidebar.tsx` | Right-rail panel hosting the simulator UI. |
| `ChatMessage.tsx` | Single chat-bubble renderer (user / assistant). |
| `SlotTracker.tsx` | Live view of collected slots and their values. |
| `index.ts` | Public surface. |

## How it connects

- Reads the flow from the same Zustand store as `components/flow-editor/`.
- Backed by `api/simulation.py` for any LLM/runtime steps that need server state.

## Conventions

- Renders inside the flow editor page; not a standalone route.
- Treat the simulator as read-only against the editor store — it should not mutate the flow being designed.

## Setup

No standalone setup.

## Gotchas

- Simulator behaviour can drift from real call behaviour if the runtime in `voice/flows/engine.py` is changed without updating the simulator's expectations.
