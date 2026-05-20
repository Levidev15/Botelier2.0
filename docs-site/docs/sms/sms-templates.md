---
id: sms-templates
title: SMS Templates
sidebar_label: SMS Templates
---

# SMS Templates

**SMS Templates** are reusable message snippets that agents can insert into the reply box with a single click. They save time for common responses and ensure consistent messaging.

## Creating a Template

1. Navigate to **SMS** → **Templates**.
2. Click **New Template**.
3. Fill in:
   - **Name** — internal label (not sent to the customer)
   - **Content** — the message text. Supports `{{variable}}` placeholders.
4. Click **Save**.

**Example template:**
```
Name: Reservation Confirmed
Content: Hi! Your reservation at {{property_name}} is confirmed for {{check_in_date}}. 
         Confirmation number: {{confirmation_number}}. Reply STOP to opt out.
```

## Using Templates from the Inbox

1. Open a conversation in **Human** mode.
2. Click the **Templates** icon (📋) in the reply toolbar.
3. Search or browse the template list.
4. Click a template to insert its content into the reply box.
5. Fill in any `{{variable}}` placeholders.
6. Click **Send**.

## Variable Placeholders

Template variables are filled manually before sending — they are not automatically populated from call data. Use them as prompts to remind agents what to fill in.

Format: `{{variable_name}}` — use lowercase, underscores, no spaces.

## Editing and Deleting Templates

- **Edit:** Click the template name → make changes → **Save**.
- **Delete:** Click the **...** menu → **Delete Template**. This is irreversible; copy the content first if needed.

## Best Practices

- Keep templates short — long messages split into multiple SMS segments, which can feel disjointed.
- Always include an opt-out line in promotional templates: `Reply STOP to unsubscribe.`
- Create templates for your most common agent responses: confirmations, holds, callback requests, apologies.
