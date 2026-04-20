# `components/flow-editor/` — Visual conversation flow builder

## Purpose

React Flow–based editor where hotels build conversation flows for an assistant. Persists via the backend `api/flow_versions.py` (versioned, draft / published).

## Main files

```
flow-editor/
├── FlowEditor.tsx              Main canvas, wires React Flow + store + toolbar
├── FlowToolbar.tsx             Top toolbar (save, publish, simulate, undo, …)
├── FlowSchemaPanel.tsx         Side panel listing the flow schema
├── NodeInspector.tsx           Right-rail dispatcher: picks the matching <…NodePanel> by selected node type
├── UnsavedChangesModal.tsx     Confirmation modal for navigation away with dirty state
├── useUnsavedChangesWarning.ts Hook driving the modal + browser beforeunload guard
├── store.ts                    Zustand store: nodes, edges, selection, dirty flag, undo/redo
├── index.ts                    Public surface re-exports
├── nodes/                      Node renderers (one per node type)
│   ├── InitialNode, MessageNode, CollectSlotNode, CollectFormNode,
│   │ ConditionNode, RouterNode, APIRequestNode, SetVariableNode,
│   │ ConfirmationNode, TransferNode, EndNode
│   └── index.ts                Registry consumed by React Flow
└── inspectors/                 Right-rail config panels (one per node type)
    ├── InitialNodePanel, MessageNodePanel, CollectSlotNodePanel,
    │ CollectFormNodePanel, ConditionNodePanel, RouterNodePanel,
    │ APIRequestNodePanel (+ APIRequestHeadersSection),
    │ SetVariableNodePanel, ConfirmationNodePanel, TransferNodePanel,
    │ EndNodePanel
    ├── VariablesPanel.tsx      Shared flow variables editor
    └── shared.ts               Inspector primitives shared across panels
```

## How it connects

- Mounted by `app/(dashboard)/dashboard/tools/[id]/flow/page.tsx`.
- Persists through `lib/auth/api-client.ts` against `api/flow_versions.py`.
- Runtime counterpart lives in `botelier/backend/botelier/voice/flows/` — node types here MUST match runtime handlers there or the flow is a no-op in production.
- `flow-simulator/` consumes the same store shape to step through flows in-browser.

## Conventions

- **Node ↔ Inspector pairing.** Every node type has both a `<Type>Node.tsx` (canvas renderer) and a `<Type>NodePanel.tsx` (right-rail editor). Adding a node type means adding both files, registering in `nodes/index.ts`, AND adding the runtime handler under `voice/flows/`.
- Inspector panels share primitives via `inspectors/shared.ts` to keep look-and-feel consistent.
- All editor state mutations go through the Zustand store in `store.ts` so undo/redo + dirty tracking stay correct.
- `useUnsavedChangesWarning` is the only sanctioned way to gate navigation away from a dirty editor.

## Setup

No standalone setup; rendered by the flow editor page.

## Gotchas

- A new node type without a runtime handler in `voice/flows/engine.py` will save and look fine in the editor but no-op at call time.
- React Flow controlled mode means: never mutate `nodes` / `edges` outside the store — direct setState on the React Flow component bypasses undo/redo.
- The sonner vendor-chunk SSR crash (Task #119) historically surfaced on this page after dependency upgrades; if it returns, wipe `frontend/.next/` and restart.
