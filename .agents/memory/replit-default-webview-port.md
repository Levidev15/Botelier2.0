---
name: Replit default webview/preview port selection
description: Why a multi-service Replit project's preview can default to the wrong port, and which .replit levers actually persist vs get silently reverted.
---

In a multi-workflow Replit App (a parent "Project" workflow running several child workflows in parallel via `task = "workflow.run"`), the parent itself had no `outputType` metadata — only the nested child workflow (e.g. the dashboard) declared `outputType = "webview"`. That gap is a plausible cause of the Run button's aggregate preview defaulting to a different service's port than the one the nested webview workflow declares.

**`[[ports]]` edits do NOT persist.** Manually reordering `[[ports]]` entries, adding `exposeLocalhost`, or deleting dead/orphaned entries in `.replit` gets silently reverted by the platform back to ascending-numeric-localPort order (with `exposeLocalhost` re-added only where actually needed) within one workflow-restart cycle. Verified twice: an edit that read back correctly immediately after `verifyAndReplaceDotReplit` was gone after workflows next restarted. Do not rely on `[[ports]]` ordering as a fix for anything — treat it as derived/read-mostly state.

**What does persist:** `[workflows.workflow.metadata]` blocks (including `outputType`) on every workflow, including the top-level parent that `runButton` points to. Adding `outputType = "webview"` to the parent orchestrator (in addition to the child that actually owns port 5000) survived multiple restarts untouched.

**How to apply:** If a Replit project's preview keeps opening on the wrong service, set `outputType` explicitly on every workflow in the tree — parent included — rather than trying to fix it via `[[ports]]` order/flags. Verify a `.replit` port-config change actually stuck by re-reading the file after the next workflow restart, not just right after writing it.
