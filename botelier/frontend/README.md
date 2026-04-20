# Frontend

Next.js 14 dashboard for the Botelier SaaS.

## Purpose

Tenant-facing UI for assistant configuration, conversation flow editing, knowledge bases, tools, MCP/integration setup, phone numbers, dispositions, analytics, team/account management, and SMS conversations. Also hosts the super-admin and standalone-embed surfaces.

## Main files

```
frontend/
├── server.js             Custom Next server: HTTP /api/* proxy + raw-TCP /api/ws/* relay
│                         (TCP_NODELAY on both sockets to avoid Nagle batching of
│                         160-byte μ-law audio frames in production)
├── package.json          dev: `node server.js` (binds $PORT, default 5000)
├── next.config.mjs       Next config (App Router enabled by default in 14)
├── tailwind.config.ts    Tailwind 3
├── postcss.config.mjs
├── tsconfig.json
├── app/                  Next 14 App Router — see app/README.md
│   ├── (auth)/                Login
│   ├── (public)/invite/       Public invitation accept
│   ├── (dashboard)/dashboard/ Main tenant UI
│   ├── (admin)/admin/         Super-admin
│   ├── (standalone)/dashboard/ Embedded views
│   ├── api/auth/              NextAuth handlers
│   ├── layout.tsx, page.tsx, globals.css
├── components/           Component library — see components/README.md
├── lib/                  auth/, hooks/, theme/, flow-utils, notifications
└── contexts/             AccountFeaturesContext
```

## How it connects

- `server.js` listens on `$PORT` (default `5000`), proxies all `/api/*` and `/uploads/*` HTTP traffic to `BACKEND_URL` (default `http://localhost:3001`), and relays WebSocket upgrades on `/api/ws/*` directly via raw TCP sockets with `setNoDelay(true)` (avoids audible audio choppiness in production).
- NextAuth routes (`/api/auth/session`, `/api/auth/providers`, …) are handled in-process by Next; explicit backend auth routes (`/api/auth/login`, `/register`, `/validate`, `/verify-invitation`) are forwarded to FastAPI — see `server.js:126-141`.
- All data calls go through `lib/auth/api-client.ts`.

## Conventions

- Server components by default. Mark `"use client"` only when needed (state, event handlers, browser APIs).
- API access via `lib/auth/api-client.ts` — no ad-hoc `fetch()` to the backend.
- Toast notifications via `lib/notifications.ts` (sonner wrapper).
- Editor state (flow editor) lives in Zustand stores; light page state stays local.

## Setup

Workflow `botelier-dashboard`:

```
cd botelier/frontend && npm run dev
```

`npm run dev` runs `node server.js`. `BACKEND_URL` defaults to `http://localhost:3001`.

## Gotchas

- **Stale `.next/` cache after dependency upgrades** can cause SSR crashes like `Cannot find module './vendor-chunks/<pkg>.js'` (Task #119 — sonner). Wipe `botelier/frontend/.next/` after `npm install` or any `package-lock.json` change, then restart the workflow.
- Port mismatch in some workflow comments: `server.js` actually binds `$PORT` (default `5000`). Trust `server.js:9`.
- WS proxying via `http-proxy-middleware` introduces audio jitter in prod due to internal Node stream buffering. Don't replace the raw-socket relay in `server.js:48-115` without re-validating audio quality on a real Twilio call.
