---
id: linking-tools-to-assistants
title: Linking Tools to Assistants
sidebar_label: Linking to Assistants
---

# Linking Tools to Assistants

## Creating a Tool Set

A **Tool Set** is a named collection of tools. An assistant can have one Tool Set assigned.

1. Navigate to **Tools** → **Tool Sets**.
2. Click **New Tool Set**.
3. Give it a name (e.g. "Front Desk Tools") and click **Create**.

## Adding Tools to a Tool Set

1. Open the Tool Set.
2. Click **+ Add Tool**.
3. Select the tool type (Transfer, API Request, or Flow Tool).
4. Fill in the name, description, and type-specific configuration.
5. Click **Save Tool**.

Repeat for each tool in the set.

## Assigning a Tool Set to an Assistant

1. Open the assistant.
2. Under **Tool Set**, select the Tool Set from the dropdown.
3. Click **Save**.

All tools in the selected Tool Set are immediately available for the assistant's next call.

## Managing Multiple Assistants with Shared Tools

You can assign the same Tool Set to multiple assistants. Changes to any tool in the set affect all assistants using it.

If different assistants need different tool configurations for the same action (e.g. different transfer destinations per department), create separate Tool Sets.

## Removing a Tool

Removing a tool from a Tool Set takes effect immediately. In-progress calls will fail gracefully if they attempt to invoke a removed tool (the LLM receives an error and continues the conversation).

1. Open the Tool Set.
2. Click the **...** menu on the tool row.
3. Select **Delete Tool**.

## Tool Availability During Calls

All non-disabled tools in the assigned Tool Set are offered to the LLM on every turn. The LLM selects the tool based on the conversation context and each tool's **description**.

To temporarily disable a tool without deleting it:
1. Open the tool.
2. Toggle **Active** to off.
3. Save.

Inactive tools are not sent to the LLM.
