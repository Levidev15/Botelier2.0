---
id: tools-overview
title: Tools Overview
sidebar_label: Tools Overview
---

# Tools Overview

**Tools** are actions the AI assistant can take during a conversation. When the LLM decides that an action is needed (e.g. "transfer this caller to billing"), it invokes the appropriate tool by name.

## What Tools Are

Each tool has:
- A **name** — how the LLM refers to it in function-calling
- A **description** — used by the LLM to decide when to invoke the tool
- A **type** — determines what the tool actually does (transfer, API call, sub-flow)
- A **configuration** — type-specific settings (destination number, API URL, etc.)

## Tool Sets

Tools are organized into **Tool Sets** — named collections of tools. An assistant is assigned one Tool Set, and all tools in that set are available during conversations.

This allows you to:
- Share a set of tools across multiple assistants
- Create different tool configurations for different assistants without duplicating definitions

## How the Assistant Invokes Tools

1. The caller's speech is transcribed and sent to the LLM.
2. The LLM evaluates the conversation and decides if a tool should be called.
3. The tool is identified by name from the active Tool Set.
4. Botelier executes the tool (places the transfer, makes the API call, etc.).
5. The result (if any) is returned to the LLM, which continues the conversation.

The LLM chooses tools based on their **description** — write clear, specific descriptions.

**Good description:** "Transfer the call to the billing department when the caller has a question about their invoice, payment method, or account balance."

**Poor description:** "Transfer call."

## Tool Types

| Type | What It Does |
|---|---|
| **Transfer** | Transfer the call to a phone number or SIP URI |
| **API Request** | Call an external HTTP API and return the response |
| **Flow Tool** | Execute a sub-flow defined in the Flow Editor |

See [Tool Types](./tool-types) for full configuration details.

## Per-Call Tool Availability

All tools in the assigned Tool Set are available for every call. There is no per-call filtering at runtime — control tool availability by assigning different Tool Sets to different assistants or by writing targeted tool descriptions.
