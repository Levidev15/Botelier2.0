---
id: platform-overview
title: Platform Overview
sidebar_label: Platform Overview
---

# Platform Overview

Botelier is a multi-tenant, multichannel AI platform that lets businesses deploy configurable AI agents to handle voice calls and SMS conversations — with web chat on the near-term roadmap.

## Key Concepts

| Concept | Description |
|---|---|
| **Account** | A business tenant. All data, phone numbers, assistants, and users are isolated per account. |
| **Assistant** | A configured AI agent combining a language model, speech providers, and a knowledge base. |
| **Channel** | How a customer reaches the assistant — voice call, SMS, or (soon) web chat. |
| **Flow** | A visual conversation script built in the drag-and-drop Flow Editor that guides the assistant through structured dialogues. |
| **Knowledge Base** | A collection of Q&A entries the assistant uses to answer caller questions. |
| **Tool** | An action the assistant can take — transfer to a phone number, call an external API, or execute a sub-flow. |
| **Integration** | A pre-built connection to a third-party system (Oracle Opera, GuestCentric, MCP server, or any custom API). |
| **Disposition** | A label applied after a call to classify its outcome (e.g. "Reservation Made", "Transferred to Agent"). |
| **ACW** | After-Call Work — automated QA analysis that runs on call transcripts and scores the AI's performance. |

## How They Relate

An **Account** owns everything. Within an account you create one or more **Assistants**. Each assistant is wired to a **Knowledge Base** for factual answers, a **Tool Set** for actions, and optionally a **Flow** for structured interactions. **Phone numbers** (provisioned from Twilio) are assigned to assistants so that incoming calls and SMS messages are routed to the right agent.

## Runtime Call Path

```
Caller dials → Twilio (PSTN/SIP)
                  │
                  ▼
           Botelier WebSocket
                  │
         ┌────────┴────────┐
         │                 │
    STT (Deepgram)    VAD / SmartTurn
         │
         ▼
    LLM (OpenAI / other)
         │
    ┌────┴────────┐
    │             │
  Flow        Knowledge Base
  Executor    (Q&A lookup)
    │
    ├── Tool call? → API / Transfer / Sub-flow
    │
    ▼
  TTS (Deepgram / Cartesia)
         │
         ▼
    Audio → Twilio → Caller
```

## Runtime SMS Path

```
Inbound SMS → Twilio webhook → Botelier /api/sms/webhook
                                        │
                               AI or human routing
                                        │
                              ┌─────────┴──────────┐
                              │                    │
                         AI response          Human inbox
                         (assistant)          (agent picks up)
                              │
                         Twilio → Outbound SMS → Customer
```

## What's in the Docs

| Section | Who it's for |
|---|---|
| [Quick Start](./quick-start) | First-time operators getting to their first live call |
| [Assistants](../assistants/creating-an-assistant) | Anyone configuring AI agents |
| [Flows](../flows/flow-editor-overview) | Building structured conversation logic |
| [Knowledge Bases](../knowledge-bases/managing-knowledge-bases) | Managing Q&A content |
| [Tools](../tools/tools-overview) | Connecting to external systems |
| [SMS](../sms/messaging-inbox) | Managing SMS conversations |
| [Analytics](../analytics/call-analytics) | Reporting and monitoring |
| [Admin Guide](../admin/admin-overview) | Platform administrators |
| [API Reference](/api-reference) | Developers integrating programmatically |
