---
id: sms-ai-config
title: SMS AI Configuration
sidebar_label: SMS AI Config
---

# SMS AI Configuration

Each assistant can be enabled for SMS in addition to (or instead of) voice calls. The SMS AI responds to inbound messages using the same LLM, knowledge base, and tools as the voice assistant.

## Enabling SMS on an Assistant

1. Open the assistant.
2. Click the **SMS** tab.
3. Toggle **Enable SMS AI** on.
4. Configure the options below.
5. Assign an SMS-capable phone number to this assistant.

## SMS AI Configuration Options

| Setting | Description |
|---|---|
| **Response Mode** | `ai_only` — AI handles all messages; `human_only` — all messages route to inbox; `ai_with_escalation` — AI handles first, agent can take over |
| **AI Response Delay** | Seconds to wait before sending the AI's response (0–30). A small delay (2–3s) makes responses feel more natural. |
| **Max AI Turns** | Maximum AI replies per conversation before automatic escalation (0 = unlimited) |
| **Escalation Message** | Message sent to the customer when handing off to a human agent |
| **System Prompt Override** | Optional SMS-specific system prompt. If blank, uses the assistant's main system prompt. |

## Opt-Out Keywords

Botelier and Twilio both enforce opt-out keywords automatically. The following keywords trigger an immediate opt-out:

`STOP`, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT`

You cannot configure custom opt-out keywords — these are enforced at the carrier level.

**Re-subscribe keywords:** `START`, `UNSTOP`, `YES`

## SMS vs. Voice Behavior

| Feature | Voice | SMS |
|---|---|---|
| Real-time streaming | ✅ | ❌ (message-based) |
| Knowledge base | ✅ | ✅ |
| Tools (Transfer) | ✅ | ❌ (no call to transfer) |
| Tools (API Request) | ✅ | ✅ |
| Flow execution | ✅ | ✅ (sequential) |
| ACW / QA | ✅ | ❌ (not yet) |
| Conversation history | Per-call | Per-conversation |

## Assigning an SMS-Capable Number

The phone number assigned to the assistant must have SMS capability. Check **Phone Numbers** for the SMS capability indicator before assigning.

Multiple assistants cannot share the same phone number. Each number routes to exactly one assistant.
