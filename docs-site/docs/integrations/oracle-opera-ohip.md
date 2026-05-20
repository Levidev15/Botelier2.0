---
id: oracle-opera-ohip
title: Oracle Opera Cloud (OHIP)
sidebar_label: Oracle Opera Cloud
---

# Oracle Opera Cloud (OHIP) Integration

The Oracle Opera Cloud (OHIP) integration connects Botelier to your Oracle Hospitality property management system via the Opera Cloud REST API.

## Prerequisites

- An active Oracle Opera Cloud subscription
- OAuth2 API credentials from your Oracle Cloud account:
  - `client_id`
  - `client_secret`
  - `gateway_url` (your Oracle Cloud REST API gateway URL, must end in `.oraclecloud.com` or `.oracle.com`)
  - `app_key` (if required by your Opera instance)
- The OHIP APIs enabled on your Opera subscription (check with your Oracle account manager)

## Setup in Botelier

1. Navigate to **Integrations** → **Connect Integration**.
2. Select **Oracle Opera Cloud (OHIP)**.
3. Fill in:

| Field | Description |
|---|---|
| **Connection Name** | Internal label (e.g. "Opera Cloud - Main Property") |
| **Gateway URL** | Your Oracle Cloud API gateway URL (HTTPS, must be `*.oraclecloud.com` or `*.oracle.com`) |
| **Client ID** | OAuth2 client ID from Oracle Cloud Console |
| **Client Secret** | OAuth2 client secret |
| **App Key** | Opera application key (if required) |

4. Click **Connect**. Botelier will:
   - Obtain an OAuth2 access token from Oracle
   - Store it encrypted in the database
   - Auto-refresh the token before expiry

5. If the connection status shows **Connected**, the integration is ready.

## Available Endpoints

After connecting, the following OHIP endpoint categories are available for use in flows and tools:

| Category | Examples |
|---|---|
| **Reservations** | Look up reservation by confirmation number, create/modify reservation |
| **Guest Profiles** | Look up guest by name, email, loyalty number |
| **Room Inventory** | Check availability, room types |
| **Folios** | View folio charges, post charges |
| **Check-In / Check-Out** | Initiate check-in, check-out |

The exact endpoints depend on the APIs enabled on your Opera subscription.

## Using the API Tester

To verify the connection and test individual endpoints:

1. Go to **Tools** → **API Tester**.
2. Select your Opera Cloud integration.
3. Choose an endpoint category and endpoint.
4. Fill in required parameters (e.g. `hotelId`, `reservationId`).
5. Click **Send**.
6. Inspect the response to confirm it returns the expected data.

## Linking to an Assistant

After connecting:
1. Open your assistant.
2. In the **Flow Editor**, add an **API Request** node.
3. Toggle **Use Integration** → select **Oracle Opera Cloud**.
4. Select the endpoint and configure parameters.

The assistant can now look up reservations, guest profiles, or room availability in real time during calls.

## Security Note

The Opera gateway URL is validated on every save — only `*.oraclecloud.com` and `*.oracle.com` hostnames are accepted. This prevents SSRF attacks via attacker-controlled gateway URLs.
