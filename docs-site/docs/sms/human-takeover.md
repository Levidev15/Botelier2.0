---
id: human-takeover
title: Human Takeover
sidebar_label: Human Takeover
---

# Human Takeover

**Human Takeover** lets a human agent take control of an AI-managed SMS conversation, reply directly to the customer, and optionally hand the conversation back to the AI.

## AI Handoff State Machine

Each SMS conversation is in one of these states:

```
  OPEN (AI)
    │
    ├─ agent clicks "Take Over" ──► OPEN (Human)
    │                                   │
    │                                   ├─ agent clicks "Hand Back to AI" ──► OPEN (AI)
    │                                   │
    │                                   └─ agent clicks "Close" ──► CLOSED
    │
    └─ AI or agent clicks "Close" ──► CLOSED
```

## Taking Over a Conversation

1. Open the conversation in the Messaging Inbox.
2. Click **Take Over** in the header bar.
3. The conversation status changes to **Human**.
4. The AI stops responding to new incoming messages from this customer.
5. The reply box becomes active — type your message and press **Send**.

:::note
Taking over does not interrupt a message the AI is currently generating. If the AI sends a reply in the same second as your takeover, both messages will appear.
:::

## Sending Replies as a Human Agent

With the conversation in **Human** mode:

1. Type your message in the reply box at the bottom.
2. Press **Enter** or click **Send**.
3. The message is sent via Twilio and marked in the thread as **Agent**.

You can send multiple messages in sequence. There is no character limit per message, but messages over 160 characters are split into multiple SMS segments by Twilio.

## Handing Back to AI

When the conversation is resolved or you want the AI to continue:

1. Click **Hand Back to AI** in the header bar.
2. The conversation status returns to **AI**.
3. The next inbound message from the customer will be handled by the AI.

## Closing a Conversation

To mark a conversation as resolved:

1. Click **Close Conversation**.
2. The conversation status changes to **Closed**.
3. Future inbound messages from this number will open a new conversation.

You can reopen a closed conversation by clicking **Reopen**.

## Opt-Out Handling

If a customer replies with an opt-out keyword (`STOP`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT`), Twilio automatically blocks all future outbound messages to that number. Botelier marks the conversation as **Opted Out**. You cannot send messages to opted-out numbers.

Customers can re-subscribe by replying `START` or `UNSTOP`.
