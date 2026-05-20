---
id: guestcentric-crs
title: GuestCentric CRS
sidebar_label: GuestCentric CRS
---

# GuestCentric CRS Integration

The GuestCentric integration connects Botelier to the GuestCentric Central Reservation System, allowing your AI assistant to check availability, look up reservations, and manage bookings during calls.

## Prerequisites

- A GuestCentric account with API access enabled
- API credentials:
  - **Username** and **Password** (for Basic Auth), or
  - **JWT credentials** (for JWT auth)
- GuestCentric API base URL provided by your GuestCentric account manager

## Setup in Botelier

1. Navigate to **Integrations** → **Connect Integration**.
2. Select **GuestCentric CRS**.
3. Fill in:

| Field | Description |
|---|---|
| **Connection Name** | Internal label (e.g. "GuestCentric - Property A") |
| **Auth Method** | `basic_auth` or `jwt` |
| **Username** | Your GuestCentric API username (basic auth) |
| **Password** | Your GuestCentric API password (basic auth) |
| **JWT Token** | Pre-issued JWT token (jwt auth) |
| **API Base URL** | GuestCentric API endpoint URL |

4. Click **Connect**. Botelier validates the credentials and stores them encrypted.

## Available Actions

After connecting, these endpoint categories are available:

| Action | Description |
|---|---|
| **Availability Check** | Check room availability for date range |
| **Rate Lookup** | Get rates for room types |
| **Reservation Lookup** | Find a reservation by confirmation number or guest name |
| **Create Reservation** | Book a room |
| **Modify Reservation** | Update dates, room type, or guest details |
| **Cancel Reservation** | Cancel a booking |

## Linking to an Assistant

1. Open your assistant's Flow Editor.
2. Add an **API Request** node.
3. Toggle **Use Integration** → select **GuestCentric CRS**.
4. Choose the action (endpoint) and configure parameters.
5. Map response fields to flow variables.

## Testing the Connection

Use the **API Tester** to verify the integration is working:

1. Go to **Tools** → **API Tester**.
2. Select your GuestCentric connection.
3. Test an availability check with known dates.
4. Confirm the response includes room and rate data.

## Refreshing Credentials

For JWT auth, tokens have an expiration time. Botelier stores the token as-is — it does not automatically refresh JWT tokens. When a token expires, update the connection:

1. Open the integration.
2. Click **Edit**.
3. Enter the new JWT token.
4. Click **Save**.
