---
name: Deep-link mount effects vs. account-context hydration
description: Why one-shot deep-link effects in the dashboard must gate on accountId before consuming their guard
---

# Deep-link mount effects must wait for `accountId`

`useAccountContext()` hydrates `accountId` from storage inside a mount
`useEffect`, so on the first render commit `accountId` is `""` (falsy).
Data fetchers that are account-scoped (e.g. `fetchConversation` in
`useSMSData`, keyed by `useCallback([accountId, ...])`) early-return `if
(!accountId) return;` on that first pass.

**Rule:** any URL-param deep-link that runs once on mount (e.g.
`?conversation=<id>`, `?call=<id>`) and uses a one-shot `useRef` guard MUST
early-return until `accountId` is truthy, and include `accountId` in the
effect deps. Otherwise the guard is "burned" on the initial no-op call and
the deep link silently never fires.

**Why:** a prior deep-link set `deepLinkedRef.current = true` before calling
the fetcher; the fetcher no-op'd (accountId still ""), then when accountId
resolved and the fetcher's identity changed the effect re-ran but the guard
already blocked it — dead link in every navigation path.

**How to apply:** mirror the call-logs pattern —
`if (!accountId || deepLinkedRef.current || typeof window === "undefined") return;`
with deps `[accountId, fetcher]`.

**Related:** account-scoped fetchers reached only via deep links must also
check `res.ok`; a stale/foreign id returns a 404 JSON body that, if set as
state (e.g. `selectedConv`), crashes the renderer (`.messages.map`). The
server still enforces isolation (account_id + membership → 404), so this is
a robustness, not a leakage, issue.
