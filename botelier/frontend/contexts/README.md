# `contexts/` — React contexts

## Purpose

Top-level React contexts whose lifetime spans the whole authenticated app.

## Main files

| File | Role |
|---|---|
| `AccountFeaturesContext.tsx` | Provides current-account feature flags + plan gating. Consumed via `lib/hooks/useAccountFeatures.ts`. |

## How it connects

- Mounted by the dashboard layout (`app/(dashboard)/layout.tsx`).
- Reads feature flags from `api/account.py`, which evaluates them via `botelier/auth/features.py`.

## Conventions

- One context per file.
- Read via the matching hook in `lib/hooks/`, never via raw `useContext` at call sites.

## Setup

No standalone setup.

## Gotchas

- Feature-flag values change when the account plan changes — components should re-render, not memoize on first read.
