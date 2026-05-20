---
id: custom-api-via-flow
title: Custom API via Flow
sidebar_label: Custom API via Flow
---

# Custom API via Flow

You can call any external API from a Botelier flow without creating a formal integration record. This approach uses **Account Secrets** to securely store credentials and **API Request** nodes to make the calls.

## When to Use This Approach

- The API doesn't have a pre-built Botelier connector
- You need one-off API calls that don't justify a full integration setup
- You want to rapidly prototype before building a proper integration

## Step 1 — Store Your API Key in Account Secrets

Account Secrets are an encrypted key-value store per account. Values are never logged or exposed in the UI after being set.

1. Navigate to **Settings** → **Secrets**.
2. Click **+ Add Secret**.
3. Enter:
   - **Key** — a name you'll reference in flows (e.g. `WEATHER_API_KEY`)
   - **Value** — the actual API key or token
4. Click **Save**.

## Step 2 — Reference the Secret in a Flow Node

In any **API Request** node or tool, reference the secret in headers:

```json
{
  "headers": {
    "Authorization": "Bearer {{secret.WEATHER_API_KEY}}",
    "X-Api-Key": "{{secret.ANOTHER_KEY}}"
  }
}
```

The `{{secret.KEY_NAME}}` syntax is resolved server-side — the actual value is never sent to or stored by the LLM.

## Step 3 — Build the API Request Node

In the Flow Editor:

1. Add an **API Request** node.
2. Set the **URL** (supports `{{variable}}` interpolation):
   ```
   https://api.openweathermap.org/data/2.5/weather?q={{city}}&units=metric
   ```
3. Set headers including your secret.
4. Add **Response Mapping** to extract values:
   ```
   main.temp      → temperature
   weather[0].description → weather_description
   ```
5. Wire the **Success** output to the next node.
6. Wire the **Error** output to a fallback message node.

## Full Worked Example — Weather Lookup

**Goal:** Ask the caller for their city, look up the current weather, and report it.

```
[Start] → [Collect Slot: city] → [API Request: Weather] → [Message: "The weather in {{city}} is {{temperature}}°C and {{weather_description}}."] → [End]
```

**API Request node configuration:**
```
URL:     https://api.openweathermap.org/data/2.5/weather?q={{city}}&appid={{secret.OWM_API_KEY}}&units=metric
Method:  GET
Headers: (none beyond the appid in the URL)
Response Mapping:
  main.temp              → temperature
  weather[0].description → weather_description
```

**On Error node:** "I'm sorry, I couldn't look up the weather right now. Is there anything else I can help you with?"

## Security Best Practices

- Always use **Account Secrets** for API keys — never hardcode them in URL or body templates
- Use HTTPS endpoints only
- Scope API keys to read-only permissions when possible
- Rotate secrets regularly via **Settings** → **Secrets** → **Edit Secret**
