---
name: flow_versions version_number invariant
description: How draft/published version numbers must be assigned across save/publish/revert to avoid uq_tool_version duplicate-key crashes.
---

# flow_versions version_number invariant

`flow_versions` has `uq_tool_version (tool_id, version_number)` plus a partial
unique index `ix_flow_versions_single_draft` (at most one DRAFT row per tool).
A tool tracks its live/draft rows via `tool.published_version_number`,
`tool.published_version_id`, `tool.draft_version_id`.

## Rule
- A draft's `version_number` is assigned **once, at creation**, and must stay
  **stable** across subsequent saves. Never reassign it on an update.
- When **creating** a new draft (save with no existing draft, or revert with no
  existing draft), derive the number from the highest existing version for the
  tool: `next = max(published_version_number+1, max(version_number)+1)`. Do NOT
  use `published_version_number + 1` alone.
- Publish flips the existing draft row in place (status DRAFT→PUBLISHED, keeps
  its `version_number`); it does not mint a new number.
- Wrap the draft-save commit in `try/except IntegrityError` → HTTP 409 so any
  residual race (concurrent first-save, single-draft index) returns a clean
  error instead of a 500.

**Why:** `save_flow_draft` previously did `draft.version_number = published+1`
on *every* save of an existing draft. Once a version at that number already
existed (e.g. after publish+revert churn), the UPDATE violated
`uq_tool_version` and 500ed every save — the flow editor could not save at all.

**How to apply:** Any change to `save_flow_draft`, `publish_flow`, or
`revert_to_version` in `botelier/backend/botelier/api/flow_versions.py` must
keep these three endpoints' numbering logic consistent. The max-version guard
already lives in both draft-creation paths — keep them mirrored.
