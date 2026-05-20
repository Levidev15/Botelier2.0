---
id: flow-versioning
title: Flow Versioning
sidebar_label: Flow Versioning
---

# Flow Versioning

Botelier creates a new **version** every time you save a flow. Versions let you track changes, roll back to a previous state, and promote a past version to active.

## How Versions Are Created

Every **Save** action in the Flow Editor commits a new version. Versions are numbered sequentially (v1, v2, v3 …) and include:

- The full flow canvas state (nodes, edges, configuration)
- Timestamp and user who saved it
- Optional version label (add a label in the Save dialog)

## Active Version

The **active version** is the version loaded at the start of every new call. When you save, the new version becomes active immediately — there is no separate "publish" step.

To change the active version without creating a new save:

1. Open the assistant's **Flow** tab.
2. Click **Version History**.
3. Find the version you want and click **Set as Active**.

## Rolling Back

To roll back to an earlier version:

1. Open **Version History**.
2. Click the version to preview its canvas.
3. Click **Set as Active** to make it the current active version.

Rolling back does not delete newer versions — they remain in history.

## How the Active Version Is Determined at Call Time

When a call arrives:

1. Botelier queries the assistant's `flow_config` field (the current active version).
2. The flow executor loads this configuration and begins at the Start node.
3. Changes saved mid-call do not affect the in-progress call — it continues with the version it started with.

## Version History Retention

All versions are retained indefinitely. There is no automatic cleanup or version limit.

## API Access

```bash
# List versions for an assistant's flow
GET /api/flow-versions?assistant_id={id}&account_id={account_id}

# Get a specific version
GET /api/flow-versions/{version_id}?account_id={account_id}

# Set a version as active
POST /api/flow-versions/{version_id}/activate?account_id={account_id}
```
