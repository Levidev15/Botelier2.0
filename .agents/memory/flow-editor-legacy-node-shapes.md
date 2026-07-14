---
name: flow-editor node components must default nested data keys
description: Historical flow_versions rows contain partial/legacy node data; node components must default nested keys, not just the top-level object.
---

# flow-editor node components must default nested data keys

Node components under `botelier/frontend/components/flow-editor/nodes/` render
`data` straight from a saved `flow_versions.flow_config`. Old versions were
saved with **partial** shapes — e.g. a `confirmation` object that exists but
lacks `variablesToConfirm`, or slots without `validation`.

## Rule
The common pattern `const x = data.x || {defaults}` only fills the object when
`data.x` is entirely absent. If `data.x` exists but is missing a nested array
key, `x.someArray.length` / `.map` still throws. Default **each nested
collection** you index into (`const arr = x.someArray || []`) or guard the
access, in every node component — not just the top-level object.

**Why:** Selecting an old version from the flow-editor version dropdown loads
that historical config into the canvas. A confirmation node saved without
`variablesToConfirm` crashed the whole editor with "Cannot read properties of
undefined (reading 'length')" the moment the version was loaded. This class of
bug is invisible until someone loads a legacy version.

**How to apply:** When adding/editing any node component, assume any nested
array/object in `data` may be missing on old saved flows. Verify against real
historical rows (query `flow_versions.flow_config`) rather than only the shape
the current editor produces.
