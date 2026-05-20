---
id: creating-an-assistant
title: Creating an Assistant
sidebar_label: Creating an Assistant
---

# Creating an Assistant

An **Assistant** is the core entity in Botelier — it encapsulates everything the AI agent needs to handle a call or SMS conversation: speech providers, the language model, a knowledge base, tools, and conversation flow.

## Prerequisites

- Account Admin or Staff role
- At least one Knowledge Base (optional but recommended)
- Twilio sub-account provisioned by your platform admin
- API keys for your chosen STT, LLM, and TTS providers configured in platform settings

---

## Basic Settings

Navigate to **Assistants** → **New Assistant** and fill in:

| Field | Description |
|---|---|
| **Name** | Internal label — not read aloud |
| **Description** | Optional notes for your team |
| **System Prompt** | Instructions sent to the LLM before every conversation. Defines persona, behavior, and constraints. |
| **First Message** | The greeting the assistant speaks immediately when a caller connects. Cached as audio for low-latency delivery (see [Greeting Cache](./greeting-cache)). |
| **Language** | Primary language code, e.g. `en`, `es`, `fr` |

:::tip System Prompt Best Practices
- State the assistant's role in the first sentence ("You are a support agent for Acme Corp…")
- List what the assistant should **not** do (transfer only for billing questions, never discuss competitors)
- Keep it under 1,000 tokens for best performance
:::

---

## Voice Provider Configuration

### Speech-to-Text (STT)

| Provider | Available Models |
|---|---|
| **Deepgram** | nova-3-general, nova-3-medical, enhanced, base |

**Key STT settings:**
- `stt_model` — choose the model matching your use case
- `stt_config.smart_format` — automatically formats numbers, punctuation
- `stt_config.punctuate` — add punctuation to transcripts

### Language Model (LLM)

| Provider | Recommended Models |
|---|---|
| **OpenAI** | gpt-4o-mini (default), gpt-4o, gpt-4-turbo |

**Key LLM settings:**
- `llm_model` — controls cost, speed, and quality
- `temperature` — 0.0–1.0; lower values produce more consistent responses
- `max_tokens` — cap response length (leave blank for provider default)

### Text-to-Speech (TTS)

| Provider | Notes |
|---|---|
| **Cartesia** | Low-latency, natural-sounding voices; recommended for most deployments |
| **Deepgram** | Supports greeting audio caching for sub-100ms first-word latency |

**Key TTS settings:**
- `tts_voice` — provider-specific voice ID
- `tts_model` — model/version (provider-dependent)

### Voice Activity Detection (VAD)

VAD detects when the caller has stopped speaking. Enable it for better turn-taking.

| Setting | Description |
|---|---|
| **VAD Enabled** | Toggle to enable Silero VAD |
| **VAD Provider** | `silero` (default, runs locally) |
| `start_secs` | Seconds of speech before VAD fires "speech started" (default 0.2) |
| `stop_secs` | Seconds of silence before VAD fires "speech stopped" (default 0.8) |

**SmartTurn** (enabled by default when VAD is on) uses a local ML model to more accurately detect end-of-turn in conversational speech, reducing interruptions.

---

## Linking a Knowledge Base

Under **Knowledge Base**, select one KB from the dropdown. The assistant will use it to answer caller questions via semantic retrieval.

You can only link one KB per assistant. To combine content from multiple sources, add all entries to a single KB.

---

## Linking a Tool Set

Under **Tool Set**, select an existing tool set. Tools in the set will be available for the assistant to invoke during conversations. See [Tools Overview](../tools/tools-overview) for how to create tools.

---

## Linking an Integration (MCP)

Under **MCP Connection**, select a connected MCP server. The **Enabled Tools** list shows discovered tools from that server — select which ones the assistant may use.

---

## Assigning a Phone Number

1. Save the assistant first.
2. Navigate to **Phone Numbers**.
3. Click a number's **Edit** button.
4. Set **Assign To** → your assistant.
5. Click **Save**. Botelier auto-updates the Twilio webhook URLs.

---

## Go-Live Checklist

Before routing live traffic to an assistant:

- [ ] System prompt reviewed and tested in the Flow Simulator
- [ ] First message recorded / cached (click **Cache Greeting** on the assistant page)
- [ ] Knowledge base has at least 10 entries covering common questions
- [ ] Phone number assigned and Twilio webhook URLs confirmed
- [ ] ACW configured if QA scoring is required
- [ ] Call recording enabled or disabled per your compliance requirements
- [ ] Test call placed and transcript reviewed in Call Logs
- [ ] Twilio credentials present (no blocked-call errors in Admin → Security Log)
