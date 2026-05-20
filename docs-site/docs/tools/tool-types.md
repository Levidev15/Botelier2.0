---
id: tool-types
title: Tool Types
sidebar_label: Tool Types
---

# Tool Types

## Transfer Tool

Transfers the active call to a phone number (PSTN) or SIP URI.

**Configuration:**

| Field | Description |
|---|---|
| **Destination Type** | `pstn` or `sip` |
| **Destination** | E.164 phone number (e.g. `+15551234567`) or SIP URI (`sip:agent@pbx.example.com`) |
| **Transfer Mode** | `cold` (blind) or `warm` (announce first) |
| **Hold Music URL** | Audio file URL played during warm transfer |
| **Announcement** | Message spoken to the receiving agent before connecting (warm only) |

**Cold Transfer** immediately bridges the caller to the destination. The AI is disconnected.

**Warm Transfer** puts the caller on hold, connects to the destination, speaks the announcement, then bridges all three parties. If the destination doesn't answer, the caller is returned to the AI.

**Example tool configuration:**
```json
{
  "destination_type": "pstn",
  "destination": "+15559998888",
  "transfer_mode": "warm",
  "announcement": "You have a caller asking about a billing dispute.",
  "hold_music_url": "https://cdn.example.com/hold.mp3"
}
```

---

## API Request Tool

Makes an outbound HTTP request to an external API during the call. The response is returned to the LLM as a tool result.

**Configuration:**

| Field | Description |
|---|---|
| **URL** | Full URL; supports `{{variable}}` interpolation |
| **Method** | GET, POST, PUT, PATCH, DELETE |
| **Headers** | Key-value pairs; use `{{secret.KEY_NAME}}` for sensitive values |
| **Body Template** | JSON string with `{{variable}}` placeholders |
| **Response Mapping** | Map response fields to named variables using dot-notation |
| **Timeout** | Max seconds to wait for response (default: 10) |

**Example — look up a reservation:**
```json
{
  "url": "https://api.example.com/reservations/{{confirmation_number}}",
  "method": "GET",
  "headers": {
    "Authorization": "Bearer {{secret.RESERVATION_API_KEY}}",
    "Content-Type": "application/json"
  },
  "response_mapping": {
    "data.guest_name": "guest_name",
    "data.check_in": "check_in_date",
    "data.room_type": "room_type"
  }
}
```

After invoking, the LLM receives the mapped variable values (e.g. `guest_name = "Jane Smith"`) and can use them in its response.

**Storing credentials:** Use **Account Secrets** to store API keys. Reference them with `{{secret.KEY_NAME}}` — the value is never logged or exposed.

---

## Flow Tool

Executes a sub-flow defined in the Flow Editor. Use this to embed structured collection sequences (slot filling, branching logic) inside a tool call.

**Configuration:**
- The tool's **config** contains a full flow configuration JSON (same format as an assistant's `flow_config`).
- The flow editor is accessible from the tool's detail page — click **Open Flow Editor**.

**Use cases:**
- Collect a structured form (name, date, confirmation number) during an otherwise free-form conversation
- Run a multi-step lookup that requires conditional branching
- Reuse a flow segment across multiple assistants

:::note
Flow Tools have their own Flow Editor instance. See [Flow Editor Overview](../flows/flow-editor-overview) for how to build the flow. The flow runs as a sub-process within the call and returns control to the assistant when it reaches an End node.
:::

**Example:** A "Make Reservation" flow tool that collects arrival date, departure date, and room preference, then calls the reservation API.

---

## Linking Tools to the Flow Editor

In addition to being invoked by the LLM, Transfer and API Request tools can be directly called from **Flow Editor nodes**:

- **Transfer Node** — choose an existing Transfer tool or configure inline
- **API Request Node** — select an API Request tool to reuse its URL/headers/mapping

This prevents duplication between your flow-driven and LLM-driven tool configurations.
