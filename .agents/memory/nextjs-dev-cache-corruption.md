---
name: Next.js dev cache self-corruption
description: Recurring unstyled pages / _next static 404s were a Next.js 14.2.0 bug, not a routing or cache problem
---

**Rule:** When pages return 200 but every `/_next/static/css|chunks/*` request 404s in dev (fast ~20ms 404s), plus `Cannot find module './NNNN.js'` in `.next/server/webpack-runtime.js` after HMR recompiles, the cause is Next.js 14.2.0's webpack-runtime dev bug — the dev server corrupts its own incremental cache. Fix by upgrading next to a later 14.2.x patch (done: 14.2.35) AND clearing `.next`; a cache clear alone recurs within minutes.

**Why:** A `rm -rf .next` looked like a fix (pages styled again) but the corruption returned on the next HMR cycle, breaking the home/login pages again for the user.

**How to apply:** If unstyled pages / static 404s reappear in the dashboard frontend, check the next version first before suspecting the custom server.js routing (which correctly delegates all non-/api paths to Next's handle) or PostCSS config.
