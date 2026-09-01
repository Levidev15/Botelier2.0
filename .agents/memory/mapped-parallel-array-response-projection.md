---
name: Mapped parallel-array response projection
description: Rules for presenting API response mappings that contain related arrays of unequal lengths.
---

Mapped API response values remain in their original shape for flow execution.
Only their LLM-facing and test-preview representation is normalized.

**Why:** GuestCentric test responses can supply related arrays with unequal
lengths. Dropping a record because one associated array has no value would hide
a valid policy name and make testing misleading.

**How to apply:** Join top-level arrays by their shared index using the longest
array as the record count. Omit only the unavailable field from that record;
never invent a value or remove the record. Keep nested values attached to their
matching record, and clean markup only in the display representation.