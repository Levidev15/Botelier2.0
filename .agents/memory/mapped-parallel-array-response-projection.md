---
name: Mapped parallel-array response projection
description: Rules for presenting API response mappings that contain related arrays of unequal lengths.
---

Mapped API response values remain in their original shape for flow execution.
Only their LLM-facing and test-preview representation is normalized.
That representation uses multiline result blocks: one field per line,
structured indentation for nested values, and a blank line between results.

**Why:** GuestCentric test responses can supply related arrays with unequal
lengths. Dropping a record because one associated array has no value would hide
a valid policy name and make testing misleading. Dense semicolon-separated
records are also harder for people and the LLM to scan without mixing fields.

**How to apply:** Join top-level arrays by their shared index using the longest
array as the record count. Omit only the unavailable field from that record;
never invent a value or remove the record. Keep nested values attached to their
matching record, clean markup only in the display representation, and retain
the multiline block layout in all shared projection consumers.