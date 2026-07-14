---
name: confirmation node "confirmed" branch must resolve even without a sourceHandle
description: Why a confirmed booking never fires the next action node (e.g. API POST) — confirmation edge missing sourceHandle="confirmed" — and how the engine tolerates it.
---

# Confirmation node "confirmed" branch resolution

A CONFIRMATION node renders two source handles in the editor: `confirmed` and
`edit`. When the caller confirms, `_handle_confirmation` in `flow_executor.py`
advances to the node wired to the `confirmed` handle.

## The trap
`get_next_node(from, handle="confirmed")` skips any edge whose `source_handle`
is not exactly `"confirmed"` (`if handle and edge.source_handle != handle`).
Seeded/imported/template flows often store the confirmation→next edge with
**no `sourceHandle` at all** (e.g. `{"id":"e12","source":"confirm_details",
"target":"create_booking"}`). That edge never matches, so `next_node` is None,
the flow **stays on the confirmation node**, and the downstream action (a
booking API POST, save-record, etc.) never runs. Symptom: the assistant says
"thank you for confirming… one moment while I finalize" and then stalls forever
— both in the simulator and on live calls (same executor).

**Why it hid for so long:** hand-drawn edges from the `confirmed` handle DO get
`sourceHandle` persisted (React Flow `addEdge` + store `saveFlow`), so new
flows look fine; only seeded/legacy edges are affected, and they were identical
across every saved version.

## The rule
The confirmed branch resolves via `_confirmed_branch_next_node`: exact
`confirmed`-handle match first, else fall back to any outgoing edge whose
`source_handle` is **not** `"edit"`. Only `edit` is excluded so a "no" answer
can never be routed down the confirmed path. Do not "fix" this by loosening
`get_next_node` globally — routers/API success-error branches depend on strict
handle matching.

**How to apply:** when debugging "confirmed but nothing happened" in a flow,
check the confirmation node's outgoing edge JSON for a missing/blank
`sourceHandle` before suspecting the API node itself.
