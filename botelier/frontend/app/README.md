# `app/` — Next.js 14 App Router

## Purpose

Defines all routes, layouts, and the in-process API handlers for NextAuth.

## Main files

```
app/
├── layout.tsx              Root layout (fonts, providers, global styles)
├── page.tsx                Root index (currently a redirect/landing)
├── globals.css             Tailwind base + global tokens
├── (auth)/                 → URL: /login   — public sign-in flow
│   ├── layout.tsx
│   └── login/
├── (public)/
│   └── invite/[token]/     → URL: /invite/<token>   — public invitation accept
├── (dashboard)/
│   ├── layout.tsx          Authenticated dashboard chrome
│   └── dashboard/          → URL: /dashboard/*
│       ├── analytics/      Analytics dashboards (uses components/analytics/)
│       ├── assistants/     Assistant CRUD + config
│       ├── api-keys/       Account API key management
│       ├── call-logs/      Call history + drilldown
│       ├── integrations/   Third-party integration setup
│       ├── knowledge-bases/  KB CRUD
│       ├── messages/       SMS conversations
│       ├── phone-numbers/  Twilio number provisioning
│       ├── settings/       Account settings
│       ├── sms-compliance/ A2P 10DLC compliance
│       ├── team/           Team management
│       ├── tools/          Tool definitions + flow editor
│       └── page.tsx
├── (admin)/
│   ├── layout.tsx          Super-admin chrome
│   └── admin/              → URL: /admin/*
│       ├── accounts/       Tenant management
│       ├── invitations/, settings/, users/
│       └── page.tsx
├── (standalone)/
│   ├── layout.tsx          Stripped-down chrome for embedded views
│   └── dashboard/
│       └── analytics/      Embeddable analytics page
└── api/
    └── auth/               NextAuth route handlers
```

## How it connects

- Each route group's `layout.tsx` provides chrome (header / sidebar / providers); route groups in parens (`(auth)`, `(dashboard)`, …) do NOT appear in the URL.
- Pages call the backend through `lib/auth/api-client.ts`.
- `(dashboard)/dashboard/tools/[id]/flow` mounts `components/flow-editor/` for the visual flow builder.
- The custom `server.js` (one level up) decides whether `/api/*` is handled in-process by NextAuth or forwarded to FastAPI.

## Conventions

- Server components by default; client components live in `components/` and are imported into pages.
- Long-form forms compose `components/forms/FormSection.tsx` + `FormField.tsx`.
- Use the route-group layout pattern for cross-cutting chrome instead of duplicating headers per page.

## Setup

Auto-loaded by Next 14. No setup beyond running the workflow.

## Gotchas

- A page placed at `app/dashboard/...` instead of `app/(dashboard)/dashboard/...` will skip the dashboard chrome layout.
- NextAuth callback routes must remain under `app/api/auth/`; backend auth routes (`/login`, `/register`, …) are handled by `server.js` proxy — don't add them as Next route handlers.
