---
id: messaging-inbox
title: Messaging Inbox
sidebar_label: Messaging Inbox
---

# Messaging Inbox

The **Messaging Inbox** is the unified view for all SMS conversations across your account. Agents use it to monitor AI-handled threads, take over conversations when needed, and send manual replies.

## Accessing the Inbox

Navigate to **SMS** → **Inbox** in the left sidebar.

## Filtering Conversations

Use the filter bar at the top to narrow the conversation list:

| Filter | Description |
|---|---|
| **All** | Show all conversations |
| **Open** | Active conversations (AI or human handling) |
| **Closed** | Resolved conversations |
| **AI** | Conversations currently handled by the AI |
| **Human** | Conversations where a human agent has taken over |
| **Unread** | Conversations with messages you haven't seen |
| **Assistant** | Filter by a specific assistant |

## Conversation List

Each conversation shows:
- **Contact number** — the customer's phone number
- **Last message preview** — first 80 characters of the most recent message
- **Timestamp** — time of last message
- **Unread badge** — count of unread messages
- **Status badge** — AI / Human / Closed
- **Presence indicator** — which agent (if any) is currently viewing this conversation

## Real-Time Presence

When another agent has a conversation open, their name appears as a presence indicator on the conversation row. This prevents two agents from simultaneously sending conflicting replies.

## Opening a Conversation

Click any conversation row to open the detail view. The detail view shows:

- **Message history** — all messages in chronological order, labeled Inbound / Outbound / AI / Agent
- **MMS attachments** — images displayed inline; other file types shown as download links
- **Customer info panel** — phone number, conversation status, assigned assistant
- **Reply box** — visible when the conversation is in Human mode

## Reading MMS Attachments

Images received as MMS are displayed inline in the message thread. Click an image to open it full-size. Other attachment types (PDF, audio, etc.) show a download link.

:::note Attachment Storage
MMS attachments are stored on the Botelier server in `uploads/`. They are served over your Botelier domain and are accessible to anyone with the URL — do not treat them as private.
:::
