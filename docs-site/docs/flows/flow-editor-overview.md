---
id: flow-editor-overview
title: Flow Editor Overview
sidebar_label: Flow Editor Overview
---

# Flow Editor Overview

The **Visual Flow Editor** is a drag-and-drop canvas for building structured conversation scripts. Instead of relying solely on a system prompt to guide the AI, flows let you define explicit paths, collect structured data from callers, and branch based on their responses.

## When to Use a Flow vs. a System Prompt

| Scenario | Recommendation |
|---|---|
| General Q&A from a knowledge base | System prompt only |
| Collect name, date, confirmation number | Flow with Collect Slot nodes |
| Route callers to different departments | Flow with Router/Condition nodes |
| Look up a booking in an external API | Flow with API Request node |
| Transfer caller to a specific agent | Flow with Transfer node |
| Complex multi-step booking or intake | Full flow with multiple branches |

## Canvas Layout

| Area | Description |
|---|---|
| **Node Palette** (left) | Drag nodes onto the canvas from here |
| **Canvas** (center) | Arrange and connect nodes |
| **Properties Panel** (right) | Configure the selected node |
| **Toolbar** (top) | Save, version history, simulate, zoom controls |

## Node Types

| Node | Purpose |
|---|---|
| **Start** | Entry point — every flow has exactly one |
| **Message** | Speak a static text to the caller |
| **Collect Slot** | Ask a question and capture the caller's response into a variable |
| **API Request** | Make an outbound HTTP call and map the response to variables |
| **Router** | Branch on a variable's value (multiple outputs) |
| **Condition** | True/false branch on a boolean expression |
| **Transfer** | Transfer the call to a PSTN number or SIP URI |
| **End** | Terminate the flow |

See [Node Reference](./node-reference) for full details on every node type.

## Connection Rules

- Every node must have at least one **incoming** connection, except the Start node.
- **Router** and **Condition** nodes have **multiple output handles** — wire each branch.
- Unconnected output handles are silently ignored at runtime (the flow ends).
- You cannot create cycles — flows are directed acyclic graphs (DAGs).

## Saving and Versioning

Click **Save** to persist the current canvas state. Botelier creates a new **version** on every save. The version becomes the **active version** immediately.

To promote a prior version or roll back, see [Flow Versioning](./flow-versioning).

## How Flows Relate to Assistants

A flow is attached to an assistant. When a call starts:

1. If the assistant has an **active flow**, the voice engine loads the flow and begins at the Start node.
2. The assistant's **system prompt** and **knowledge base** are still active — the flow controls the conversation structure, but the LLM still uses them for natural language generation.
3. If no active flow exists, the assistant runs in **free-form mode** (pure LLM with knowledge base).

## Accessing the Flow Editor

1. Open an assistant.
2. Click the **Flow** tab.
3. Click **Open Flow Editor**.

The editor opens in a full-screen canvas view.
