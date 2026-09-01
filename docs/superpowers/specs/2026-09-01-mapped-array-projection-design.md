# Mapped Array Projection Design

## Goal

Make the API Request test panel and the LLM-facing result readable when a
response mapping produces related, parallel arrays such as cancellation policy
IDs, names, and rules.

## Scope

The change applies after the existing response mapping has extracted values
from an API response. It does not change HTTP responses, configured mapping
expressions, or the flow variables stored for subsequent nodes.

## Data flow

1. Existing response mapping continues to produce its original dictionary of
   extracted values.
2. Flow variables retain those original values unchanged. For example,
   `cancellation_name` remains an array for any later flow node that references
   it.
3. A display-only projection normalizes a dictionary containing related arrays
   into index-aligned entries for the LLM result and the API test panel's
   “Projected (what LLM sees)” section.
4. The existing Voice result script receives this formatted projection, rather
   than a separate competing formatter being introduced.

## Parallel-array normalization

- The normalizer creates one entry for every index in the longest top-level
  array.
- Every array value at that index becomes a field on the entry. Scalars remain
  shared metadata.
- Missing values remain absent from their entry. They do not cause the entry to
  be dropped and are never replaced with invented values.
- Nested lists and objects are preserved as readable structured values within
  the corresponding entry.
- The result is compact caller- and LLM-readable text, not raw JSON.

For the current test-server example, “Flexible Cancelation” is retained as the
fifth item even if `cancellation_rules` has only four entries.

## Safety and fallback behavior

- Responses without top-level arrays retain the existing projection behavior.
- A single unrelated array is presented as a simple list rather than forcing a
  record-like shape.
- HTML-only fields are converted to readable text for the display projection;
  raw mapped values remain unchanged.
- The transformation is deterministic and has no network or LLM dependency.

## Testing

Tests will cover:

- aligned arrays producing one readable item per index;
- uneven arrays retaining the unmatched final item;
- nested cancellation rules;
- scalar metadata and ordinary non-array mappings retaining their behavior;
- API test and runtime result paths using the same display projection.