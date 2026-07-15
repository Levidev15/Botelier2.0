---
name: Designable PMS payment page
description: PMS-native review+pay page — how collect_payment routes to a combined PMS booking+charge vs Stripe link, card handling, and the per-property page designer.
---

# Designable PMS payment page

Operators text callers a secure single-use review+pay link showing the AI-collected
reservation (pre-filled, per-field-editable) plus card entry. On submit, ONE combined
PMS call (Opera `create_reservation_with_payment` / GuestCentric
`book_reservation_with_payment`) both creates/confirms the reservation AND attaches the
card so the hotel's own gateway charges it.

## Routing rule (the core decision)
`collect_payment` is service-backed. It routes **PMS-native when the property has exactly
one connected, payment-capable PMS connection, else Stripe link**.

- "Payment-capable" = a seed endpoint tagged `supports_card_capture: True`.
- These combined endpoints deliberately carry **NO `capability` tag**, so they never
  compete with plain `book_reservation` in the universal capability resolver.
- Selection reuses the same fail-closed, property-tiered, ambiguity→None logic as
  `CapabilityResolver.resolve` (property-bound preferred over account-global; >1 in the
  chosen tier → `None`). `None` here means **fall back to the Stripe link**, never guess.
- **Why:** routing a caller to the wrong property's PMS / gateway is worse than a link.

## Card = never stored or logged
- Card fields (`card_holder`/`card_number`/`card_expiry`/`card_cvv`) are captured on the
  review page, held only in the submit request, validated, and forwarded in-memory to the
  PMS's PCI-certified gateway. The `Payment.provider_refs` stores ONLY the server-side PMS
  endpoint binding (integration/endpoint/vendor) — never card data. Link is single-use +
  expiring; token is burned on successful submit.
- Adapters fail **loud** on incomplete card (`validate_card_capture`, base contract).
  GuestCentric additionally requires availability-derived ids (rate/policy/meal-plan) —
  a standalone submit lacking them errors, never silently books unpaid.
- **Why:** silently creating an unpaid/broken reservation is worse than a clear error.

## Submit outcomes: terminal vs. non-terminal (the subtle one)
On the public `POST /review/{token}/submit`, a "failed" outcome must burn the single-use
link, but a **double-submit in-progress reply must NOT**. Distinguish them by the
ActionExecutor result's `status_code`: the idempotency guard (already-in-progress /
ambiguous-replay / ledger-unavailable) returns `status_code == 0` (from `_error`), while a
real vendor decline carries a non-zero HTTP status.
- `status_code == 0` → non-terminal: return 409 "processing", leave the row PENDING and the
  token intact so the winning request can still CAPTURE.
- real decline / transport exception / incomplete card → terminal: mark FAILED + burn token.
- The FAILED transition is a **guarded UPDATE** (`WHERE status IN (pending, authorized)`), so
  a stale in-flight request can never overwrite a CAPTURED booking with FAILED.
- **Why:** treating "already in progress" as terminal lets a racing double-submit clobber a
  successful booking/charge as FAILED (or tell the guest it failed while the card was charged).

## The public page is a hostile-input surface (two sinks)
This page is public, unauthenticated, and collects a card — treat every input as
hostile even though the *design* is operator-authored.
- **Submit form is untrusted.** The submit merge must overlay onto the booking+charge
  payload ONLY keys the resolved design marks editable **and** visible, plus the card
  keys — a server-side allowlist. Otherwise a caller overlays a readonly/hidden field
  (`total_price`) or injects an extra vendor variable (a rate/policy id) into the PMS
  call. Non-allowed keys are dropped; the authoritative AI-collected value stands.
- **Branding is a CSS/URL injection sink.** `primary_color`/`accent_color` land raw in
  inline `:root` CSS; `logo_url`/`privacy_url`/`terms_url` land in `href`/`src`. Enforce
  strict-hex colors + http(s)-only URLs at API write (clear 400) AND coerce at the render
  sink (defense in depth for legacy/other write paths). html.escape alone does NOT stop a
  CSS breakout or a `javascript:` scheme.
- **Why:** on a PCI-adjacent card page, a CSS breakout / script-scheme URL is
  session-theft-grade, and silent payload tampering can change what gets booked/charged.

## Certified-only (same boundary as every IntegrationClient feature)
PMS-native collection covers certified integrations only (Opera, GuestCentric). Legacy
custom-HTTP tools + MCP bypass `IntegrationClient` → not payment-capable → always Stripe
link.

## Page designer
Per-property visual designer (dashboard **Payment Page** nav). Stored as one structured
`design` JSONB on `PaymentPageTemplate` (property_id NULL = account default). GET returns
`{design, is_custom}` and falls back to `default_page_design()` so designer + public
renderer always share a complete contract. Frontend gates on `integrations` perm (no
`properties` key exists in the frontend `UserPermissions` type) but the backend enforces
the real `properties.view`/`properties.manage`.
