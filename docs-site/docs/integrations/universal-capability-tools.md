---
id: universal-capability-tools
title: Universal Capability Tools
sidebar_label: Universal Capability Tools
---

# Universal Capability Tools

Universal capability tools let your AI assistant call **abstract, vendor-neutral capabilities** — `search_availability`, `lookup_reservation`, `book_reservation`, `cancel_reservation` — instead of a specific vendor's endpoint. At runtime Botelier resolves the capability to the caller's property-scoped provider connection and translates the request into that vendor's shape.

The AI only ever knows the capability. It never sees which vendor (Oracle Opera Cloud, GuestCentric, …) ultimately serves the request. The **same** capability call behaves identically on voice, SMS, and in the flow simulator.

## Why capabilities?

Without capabilities, an assistant that should "look up a reservation" must be wired to a specific vendor endpoint. Move the account to a different PMS — or run two properties on two different systems — and every flow and prompt has to change.

A capability decouples the *promise* ("look up a reservation") from the *provider* that fulfils it:

- **One assistant config works across vendors.** Swap the underlying connection and nothing in the flow or prompt changes.
- **Multi-property, multi-vendor accounts just work.** Hotel A on Opera and Hotel B on GuestCentric can share one assistant; each call resolves to the right property's provider.
- **Reads come back canonical.** `search_availability` and `lookup_reservation` return the [canonical domain shape](./canonical-domain-schemas), so downstream logic is vendor-neutral too.

## The capabilities

| Capability | Kind | Canonical entity | Vendor-neutral parameters |
|---|---|---|---|
| `search_availability` | read | `availability` | `check_in_date`\*, `check_out_date`\*, `guest_count`, `children` |
| `lookup_reservation` | read | `reservation` | `confirmation_number`\* |
| `book_reservation` | write | — | `guest_first_name`\*, `guest_last_name`\*, `check_in_date`\*, `check_out_date`\*, `room_type`\*, `rate_code`\*, `guest_count`, `children` |
| `cancel_reservation` | write | — | `confirmation_number`\* |

\* required.

Write capabilities (`book_reservation`, `cancel_reservation`) return the vendor's raw + mapped response, not a canonical envelope — canonicalization is reads-only.

## How resolution works

When the LLM calls a capability, the resolver picks the single provider connection that should serve it, **failing closed** whenever the choice is not unambiguous:

1. **Candidates** = the account's `CONNECTED` integrations whose type has an endpoint tagged with that capability.
2. **Property gate** — candidates are filtered by the session's resolved `property_id` (dialed number → assistant → none). A property-A session can never use a property-B connection. This reuses the same fail-closed per-property isolation as certified integrations.
3. **Preference** — a connection bound to the session's property wins over an account-global (unbound) one.
4. **Ambiguity fails closed** — if more than one connection remains in the chosen tier, the resolver refuses to guess and the capability is reported unavailable. It never silently routes the caller to the wrong system.

If nothing resolves (no connected provider for this property, unknown capability, or an ambiguous tie), the AI is told the capability is unavailable rather than being handed the wrong vendor.

### Property-identity keys are never caller-controlled

Vendor property-identity keys (`hotel_id`, `property_id`, …) are deliberately **not** capability parameters. They are re-forced from the resolved connection's config, so a caller or the LLM can never redirect a request to another property by supplying its own identifier.

## Argument translation

Each vendor endpoint's seed declares a `capability_params` map from the vendor-neutral key to that vendor's variable key. For example, GuestCentric renames `check_in_date` → `checkin` and `guest_count` → `adults`; Opera keeps `check_in_date`. The resolver applies this map at call time. Keys the map doesn't mention pass through unchanged, so flow slots that already use a vendor's variable name still reach the request.

## Using capabilities

### As standalone tools

Add a **Capability** tool to a tool set and link the tool set to an assistant. The LLM can then call the capability at any point in the conversation (voice, SMS, or simulator), exactly like any other tool.

### In flows

An API Request node can target a capability instead of a specific integration endpoint. The node resolves the same way at execution time. Write capabilities are guarded against accidental non-idempotent replays the same way non-GET API requests are.

## Limitations (v1)

- **Booking is not perfectly vendor-neutral.** GuestCentric's booking endpoint needs rate / cancellation-policy / meal-plan identifiers that only exist after a prior availability lookup. Those are collected as flow slots and passed through untranslated; a standalone `book_reservation` against GuestCentric that lacks them fails explicitly with a missing-variable error rather than silently. Opera's booking is satisfiable from the parameters above.
- **Certified integrations only.** Capabilities resolve to certified connections (Opera, GuestCentric). Legacy custom-HTTP API requests and MCP tools are not capability-resolvable and are not property-checked — keep property-specific endpoints on certified connections.
- **Reads-only canonicalization.** Only `search_availability` and `lookup_reservation` return canonical envelopes.

## See also

- [Canonical Domain Schemas](./canonical-domain-schemas) — the vendor-neutral shapes reads come back in.
- [Adding a New Integration](./adding-a-new-integration) — how to tag a new vendor's endpoints with capabilities.
