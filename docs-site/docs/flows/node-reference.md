---
id: node-reference
title: Node Reference
sidebar_label: Node Reference
---

# Node Reference

Complete reference for every node type in the Botelier Flow Editor.

---

## Start Node

The entry point of every flow. There is exactly one per flow.

**Fields:**
- **Initial Message** — optional greeting to speak when the flow begins (overrides the assistant's `first_message`)
- **Variables** — initial variable values to seed the conversation context

**Example:** Greeting a caller by channel:
```
Initial Message: "Thank you for calling Acme Support. How can I help you today?"
```

---

## Message Node

Speaks a static text to the caller without expecting a response.

**Fields:**

| Field | Description |
|---|---|
| **Text** | The text to speak. Supports `{{variable_name}}` interpolation. |
| **Output** | Single connection to the next node |

**Example:**
```
Text: "Your reservation number is {{reservation_id}}. Is there anything else I can help you with?"
```

---

## Collect Slot Node

Asks a question and waits for the caller to respond. Captures the response into a named variable.

**Fields:**

| Field | Description |
|---|---|
| **Question** | Text to speak to the caller |
| **Variable Name** | Where to store the captured value (e.g. `caller_name`) |
| **Variable Type** | `text`, `number`, `date`, `boolean`, `phone_number` |
| **Max Retries** | Number of times to re-ask if the caller's answer doesn't match the type (default: 2) |
| **Retry Message** | Text to speak on failed attempts |
| **No Input Timeout** | Seconds to wait before treating silence as no-input (default: 5) |

**Output handles:**
- **Collected** — the variable was successfully captured
- **Failed** — retries exhausted without a valid answer

**Example:**
```
Question:       "Can I get your last name, please?"
Variable Name:  caller_last_name
Variable Type:  text
Max Retries:    2
Retry Message:  "I'm sorry, I didn't catch that. Could you repeat your last name?"
```

---

## API Request Node

Makes an outbound HTTP request to an external API and maps response fields to variables.

**Fields:**

| Field | Description |
|---|---|
| **URL** | Full URL. Supports `{{variable}}` interpolation. |
| **Method** | GET, POST, PUT, PATCH, DELETE |
| **Headers** | Key-value pairs. Use `{{secret.MY_API_KEY}}` to reference Account Secrets. |
| **Body Template** | JSON body as a template string. Supports `{{variable}}` interpolation. |
| **Response Mapping** | Map JSON response fields to variables using dot-notation paths (e.g. `data.reservation.id → reservation_id`) |
| **Timeout** | Request timeout in seconds (default: 10) |

**Output handles:**
- **Success** (2xx response) — proceed with mapped variables
- **Error** (non-2xx or timeout) — branch to error handling

**Example — look up a booking:**
```
URL:     https://api.example.com/reservations/{{confirmation_number}}
Method:  GET
Headers: Authorization: Bearer {{secret.HOTEL_API_KEY}}
Response Mapping:
  data.guest_name     → guest_name
  data.check_in_date  → check_in_date
  data.room_type      → room_type
```

---

## Router Node

Branches the flow based on the value of a variable. Like a switch/case statement.

**Fields:**

| Field | Description |
|---|---|
| **Variable** | The variable to branch on |
| **Routes** | Ordered list of (value, label) pairs — one output handle per route |
| **Default** | Catch-all output when no route matches |

**Example — route by department:**
```
Variable: department
Routes:
  "billing"      → Billing Branch
  "technical"    → Tech Support Branch
  "reservations" → Reservations Branch
Default → General Inquiry Branch
```

---

## Condition Node

A simple true/false branch on a boolean expression.

**Fields:**

| Field | Description |
|---|---|
| **Expression** | A condition using variables: `{{amount}} > 100`, `{{status}} == "confirmed"` |

**Output handles:**
- **True** — expression evaluated to true
- **False** — expression evaluated to false

**Example:**
```
Expression: {{reservation_found}} == true
True  → Confirm Reservation node
False → No Reservation Found node
```

---

## Transfer Node

Transfers the active call to a phone number or SIP URI.

**Fields:**

| Field | Description |
|---|---|
| **Transfer Type** | `cold` (blind transfer) or `warm` (announce caller first) |
| **Destination Type** | `pstn` (E.164 phone number) or `sip` (SIP URI) |
| **Destination** | Phone number (e.g. `+15551234567`) or SIP URI (e.g. `sip:agent@pbx.example.com`) |
| **Caller ID** | Outbound caller ID to present (defaults to the inbound number) |
| **Hold Music** | URL to audio file played during warm transfer |
| **Announcement** | Message spoken to the receiving agent before connection (warm transfers only) |

**Cold transfer example:**
```
Transfer Type:    cold
Destination Type: pstn
Destination:      +15559998888
```

**Warm transfer example:**
```
Transfer Type:    warm
Destination Type: pstn
Destination:      +15559998888
Announcement:     "Connecting you with a caller who needs billing support."
Hold Music:       https://cdn.example.com/hold.mp3
```

---

## End Node

Terminates the flow. The assistant speaks a closing message and the call continues in free-form mode (or ends if configured).

**Fields:**
- **Closing Message** — optional text spoken before ending

---

## Variable Interpolation

All text fields support `{{variable_name}}` interpolation at runtime. Variable names are case-sensitive.

**Special prefixes:**

| Prefix | Example | Description |
|---|---|---|
| `secret.` | `{{secret.API_KEY}}` | Reads from Account Secrets (encrypted) |
| *(none)* | `{{caller_name}}` | Reads a flow variable |
