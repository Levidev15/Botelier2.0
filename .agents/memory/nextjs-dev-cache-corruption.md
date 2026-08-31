---
name: Next.js dev cache self-corruption
description: vendor-chunks/@babel.js missing in dev server on complex pages (1000+ modules) — fixed via webpack externals, not a version upgrade
---

**Rule:** Two distinct Next.js 14.2.x dev bugs have appeared; treat them separately.

### Bug 1 — Static 404s / ChunkLoadError (client-side)
Pages return 200 but every `/_next/static/*` request 404s in ~20ms, and the browser console shows a `ChunkLoadError`. Caused by Next.js 14.2.0's dev webpack-runtime generating `/_next/undefined` URLs when cross-origin chunk requests are blocked. Fix: add `allowedDevOrigins: ["*.riker.replit.dev", "*.replit.dev", "127.0.0.1"]` to `next.config.mjs`.

### Bug 2 — vendor-chunks/@babel.js missing (server-side, 1000+ module pages)
Complex pages (flow editor, 1200–1500 modules) compile successfully (`✓ Compiled`) but then the server throws `Cannot find module './vendor-chunks/@babel.js'` from `webpack-runtime.js`, returning a 500. The `@babel.js` vendor chunk file is simply never written to disk by the compiler.

**This is NOT fixed by upgrading within 14.2.x.** 14.2.35 is the last patch in that line and still affected.

**Fix:** Add `@babel/runtime` to webpack server externals in `next.config.mjs`:
```js
webpack: (config, { isServer }) => {
  if (isServer) {
    const prev = config.externals ?? [];
    config.externals = [
      ...(Array.isArray(prev) ? prev : [prev]),
      function babelRuntimeExternal({ request }, callback) {
        if (request && request.startsWith("@babel/runtime")) {
          return callback(null, "commonjs " + request);
        }
        callback();
      },
    ];
  }
  return config;
},
```
This makes webpack emit `require('@babel/runtime/...')` directly (resolved from node_modules at runtime) instead of writing a vendor chunk file. No file needed, no 500.

**Why:** `@babel/runtime` provides transpiler helpers (`_asyncToGenerator`, `_objectSpread2`, etc.) used by many modules. On complex pages webpack tries to deduplicate them into a single vendor chunk, but 14.2.35's dev server has a race where the chunk reference is written to the runtime before the file is flushed to disk. Marking it as a Node external bypasses the vendor-chunk mechanism entirely.

**How to apply:** If the flow editor (or any other large page) 500s with `Cannot find module './vendor-chunks/@babel.js'`, check that the webpack externals config is present in `next.config.mjs`. If other `vendor-chunks/@X.js` files go missing, extend the condition to cover them too.
