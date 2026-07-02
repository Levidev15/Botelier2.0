---
id: guestcentric-crs
title: GuestCentric CRS
sidebar_label: GuestCentric CRS
---

# GuestCentric CRS Integration

The GuestCentric integration connects Botelier to the GuestCentric Central Reservation System, allowing your AI assistant to search hotels, check room availability and rates, look up policies, and manage reservations during calls.

## Prerequisites

- A GuestCentric account with API access enabled
- A **Username** and **Password** issued by GuestCentric — required for both auth methods (sent directly in the HTTP Basic Authorization header for Basic Auth, or exchanged for a token via GuestCentric's `/authentication/login` endpoint for JWT)
- An **API key** issued by GuestCentric's integrations team (required for every request)
- For **Basic Auth** only: a **Hotel ID** provided by GuestCentric, sent alongside the API key as a query parameter (scopes every request to a single property — JWT auth can span multiple hotels and doesn't need it)

## Setup in Botelier

1. Navigate to **Integrations** → **Connect Integration**.
2. Select **GuestCentric CRS**.
3. Fill in:

| Field | Description |
|---|---|
| **Connection Name** | Internal label (e.g. "GuestCentric - Property A") |
| **Auth Method** | `basic_auth` or `jwt` |
| **Username** | Your GuestCentric API username (required for both auth methods) |
| **Password** | Your GuestCentric API password (required for both auth methods) |
| **API Key** | API key provided by GuestCentric's integrations team (always required) |
| **Hotel ID** | Your GuestCentric hotel ID (required for Basic Auth only; not shown for JWT) |

4. Click **Connect**. Botelier validates the credentials and stores them encrypted. For Basic Auth, your username and password are sent directly in the HTTP Basic Authorization header on every request. For JWT auth, Botelier exchanges the username/password for an access token immediately and on every subsequent refresh — no raw token needs to be entered manually.

## Available Actions

After connecting, these endpoints are available, grouped by category:

| Category | Action | Description |
|---|---|---|
| Search | **Search Locations** | Look up countries, cities, or hotel names matching free text |
| Hotels | **List Hotels** | List all hotels associated with the account |
| Hotels | **Search Hotels** | Search hotels by check-in/check-out dates, adults, and location filters |
| Hotels | **Hotel Rooms & Rates** | Get available rooms, rates, promotions, and room-rate combinations for a hotel |
| Hotels | **Cancellation Policies** | Get cancellation policies for one or more hotels |
| Hotels | **Guarantee Policies** | Get guarantee policies for one or more hotels |
| Hotels | **Hotel Currencies** | List available currencies for pricing |
| Hotels | **Hotel Addons** | Get available reservation addons for a hotel |
| Reservations | **Book Reservation** | Create a new reservation |
| Reservations | **List Reservations** | List reservations with search/filter options |
| Reservations | **View Reservation** | Look up a reservation by its CRS reservation code |
| Reservations | **Update Reservation** | Update dates or guest counts on an existing reservation |
| Reservations | **Modify Reservation (Price Quote)** | Request a re-priced quote for a change; must be confirmed with a follow-up Update Reservation call |
| Reservations | **Cancel Reservation** | Cancel a reservation |
| Reservations | **Resend Confirmation Email** | Re-send the confirmation email to the guest and/or hotel |

## Linking to an Assistant

1. Open your assistant's Flow Editor.
2. Add an **API Request** node.
3. Toggle **Use Integration** → select **GuestCentric CRS**.
4. Choose the action (endpoint) and configure parameters.
5. Map response fields to flow variables (each endpoint includes labeled response fields to make mapping straightforward).

You can also start from the **GuestCentric CRS Booking** flow template (Flow Editor → **New from Template**), which includes a pre-wired availability check and booking flow using this integration.

## Testing the Connection

Use the **API Tester** to verify the integration is working:

1. Go to **Tools** → **API Tester**.
2. Select your GuestCentric connection.
3. Test **Hotel Rooms & Rates** with known dates.
4. Confirm the response includes room and rate data.

## Refreshing Credentials

For JWT auth, tokens expire after a few hours. Botelier automatically refreshes the token in the background before it expires (and re-authenticates if a call fails due to an expired token), so no manual action is needed for normal token renewal.

You only need to update the connection manually if your GuestCentric username or password changes:

1. Open the integration.
2. Click **Edit**.
3. Enter the new username and/or password.
4. Click **Save**.
