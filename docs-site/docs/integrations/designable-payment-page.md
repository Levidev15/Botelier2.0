---
id: designable-payment-page
title: Designable PMS Payment Page
sidebar_label: Designable Payment Page
---

# Designable PMS Payment Page

The designable payment page lets your AI collect a reservation over voice or SMS and
then text the caller a secure, single-use **review &amp; pay** link. The caller reviews
the AI-collected reservation (pre-filled and, where you allow it, editable), enters
their card, and confirms. Botelier issues **one combined call** to the property's
PMS that both creates/confirms the reservation *and* attaches the card so the hotel's
own payment gateway charges it.

## How payment collection resolves

When a flow (or the AI) calls the `collect_payment` capability, Botelier picks the
collection method automatically:

1. **PMS-native (preferred).** If the caller's property has exactly one connected,
   payment-capable PMS connection — an Opera Cloud endpoint tagged
   `create_reservation_with_payment` or a GuestCentric endpoint tagged
   `book_reservation_with_payment` — the caller is sent to Botelier's own review &amp;
   pay page. On submit, the card is forwarded **in memory** to the PMS's
   PCI-certified gateway in a single booking+charge request.
2. **Stripe link (fallback).** If no unambiguous PMS-native provider is available for
   the property, `collect_payment` falls back to a Stripe hosted-checkout link.

Selection is **fail-closed and property-scoped**, exactly like the universal
capability resolver:

- A property-bound connection is preferred over an account-global one.
- **More than one candidate in the chosen tier is ambiguous** → Botelier refuses to
  guess and falls back to the Stripe link rather than route a caller to the wrong PMS.
- A property-A session never resolves to a property-B connection.

## Card handling &amp; PCI scope

Botelier **never stores or logs the card**. Card fields are captured on the review
page, held only in the submit request, validated, and forwarded straight to the PMS
gateway. The payment record's server-only `provider_refs` stores which PMS endpoint to
call (integration id, endpoint id, vendor slug) — **never** card data. The link is
single-use and expires; the token is burned on a successful submit.

Each vendor adapter fails **loudly** if a booking+charge is attempted with an
incomplete card. GuestCentric additionally requires the rate, cancellation-policy,
and meal-plan ids that only exist after an availability lookup — a standalone submit
lacking them fails explicitly rather than silently creating a broken/unpaid
reservation.

## Designing the page

Open **Payment Page** in the dashboard sidebar. Design is **per property** — pick a
property from the selector, or choose *Account default (all properties)* to edit the
fallback used by any property without its own design.

You can configure:

- **Branding** — logo, heading, subheading, primary and accent colors.
- **Sections &amp; fields** — reorder fields within each section and toggle which
  reservation fields the caller may edit. Card fields are always present and always
  secure; they cannot be made non-editable.
- **Footer** — Privacy Policy and Terms links, and the *Powered by Botelier* line.

A live preview mirrors what the caller will see. **Save design** stores a custom
design for the selected scope; **Reset to default** removes the custom design and
falls back to the platform default.

Managing designs requires the `properties.manage` permission; viewing requires
`properties.view`.

## Limitations (v1)

- PMS-native collection is **certified-integrations only** (Opera, GuestCentric).
  Legacy custom-HTTP tools and MCP connections are not payment-capable and always
  fall back to the Stripe link.
- Field keys in the designer map to the resolved vendor's variable keys, so a design
  is most predictable when a property uses a single PMS vendor.
