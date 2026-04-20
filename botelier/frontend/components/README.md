# `components/` — React component library

## Purpose

Reusable building blocks grouped by domain. Pages in `app/` compose these.

## Main files

```
components/
├── flow-editor/      Visual conversation flow builder (React Flow + Zustand)
├── flow-simulator/   In-browser simulator for a flow
├── analytics/        Stat cards, drilldown modal, customizable widget layout
├── forms/            Form primitives + assistant config form
├── tabs/             TabNavigation
├── providers/        SessionProvider (NextAuth)
└── ui/               PermissionGate, SaveBar
```

## How it connects

- Imported by pages under `app/`.
- `lib/auth/api-client.ts` is the only path to the backend.
- Editor-style components own their state in Zustand stores (e.g. `flow-editor/store.ts`); simpler components use local React state.

## Conventions

- One concern per directory. Don't put generic primitives (button, card) in domain folders.
- File names are PascalCase matching the default export.
- Permission gating is done with `<PermissionGate>` from `ui/`, never inline `if (user.role === ...)`.

## Setup

No standalone setup.

## Gotchas

- See per-folder READMEs for domain-specific gotchas (flow-editor node/inspector pairing, analytics widget layout persistence, etc.).
