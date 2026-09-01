# Mapped Array Projection: Block Formatting Design

## Goal

Make the LLM-facing projection of mapped API results easier to scan by
displaying every result as a separated, multiline block. This applies to the
integration operation tester's **Projected (what LLM sees)** panel and the
automatic API-result context passed to the LLM when an API Request has no
explicit Voice result script.

## Scope and boundaries

- Keep the API provider's raw response unchanged in the debug-only raw-response
  panel.
- Keep all mapped flow variables in their original API-shaped form, including
  parallel arrays, so existing flow logic is unaffected.
- Change only the shared display/LLM projection.
- Do not summarize, infer, omit, or reorder values.
- Retain an incomplete record whenever it appears in any related top-level
  array. A missing associated value is simply absent from that record.

## Formatting behavior

For multiple top-level arrays, join values by index using the longest array as
the result count:

```text
Results:

1.
   Cancellation id: 9999
   Cancellation name: Non-refundable
   Cancellation rules:
     - Value: 100
       Type: Percentage
       Text: Non refundable

2.
   Cancellation id: 10000
   Cancellation name: 48 Hours
   Cancellation policies text: 48 hours
```

Each top-level field is shown on its own indented line. A nested object begins
on a labelled line, then its non-empty child fields appear below it. A nested
list uses `-` items with their nested fields indented beneath each item. A
blank line separates every top-level result.

The same recursive formatting rules apply to a single mapped array and to
scalar values. Scalars remain in a separately labelled shared-data section
when an array is also present. HTML is decoded and stripped only from the
displayed projection.

## Data flow

The existing shared response-projection formatter accepts mapped values and
returns the formatted text. Its two existing consumers continue to use the
same output:

1. The integration operation test endpoint returns it as `projected`.
2. The flow executor adds it to automatic LLM context when no explicit
   Voice result script is configured.

This preserves runtime/test-panel parity and avoids duplicating formatting
rules.

## Empty and irregular data

- Empty or `null` values do not render.
- An empty result produces no result block.
- Related arrays of different lengths produce all available index-aligned
  results; no padding or invented data is shown.
- Values remain readable text rather than raw JSON syntax.

## Validation

Tests will assert:

- multiline indentation and a blank line between consecutive result blocks;
- readable nested object and list formatting;
- retention of the fifth cancellation-policy result when its rule is missing;
- HTML cleanup;
- equality of the automatic LLM fallback and operation-test projection
  formatting.