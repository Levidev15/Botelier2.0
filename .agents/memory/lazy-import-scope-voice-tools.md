---
name: Function-local imports don't cross method scopes (voice tool registration)
description: Why a NameError silently dropped every non-flow tool on live calls, and how to spot it
---

# Function-local imports don't cross method scopes

A name imported inside one method (e.g. a lazy `from ..models.tool import Tool, ToolType` inside `handle_call`) is LOCAL to that method. Referencing it from a sibling method of the same class (`_build_function_schemas_and_handlers`) raises `NameError` — the fix must be a module-level import, not an addition to the other method's lazy import.

**Why:** A `ToolType` comparison added to the regular-tool branch of voice schema building crashed for EVERY non-flow tool (END_CALL, TRANSFER_CALL, SEND_SMS) on every live call. The broad `except Exception` around per-tool schema building caught it, so tools were silently dropped — calls couldn't end via AI, no transfers, no SMS — while FLOW tools (earlier branch) kept working, masking the outage. A first fix that added the name to the *other method's* lazy import changed nothing.

**How to apply:**
- Symptom signature in backend logs: `Failed to build schema for tool <name>: name 'X' is not defined`, repeated for all non-flow tools, plus transcripts showing 0 tool calls and pipeline teardown only via the Twilio `/status` webhook.
- The per-tool except now uses `logger.exception` so the traceback is loud — keep it that way.
- Voice path is the only one with lazy tool imports; SMS (`sms_service.py`) and simulator (`simulation.py`) import `ToolType` at module level. When touching tool-type logic in `call_handler.py`, verify the name is in module globals, and confirm registration with a `✅ Built function schema for tool:` line per tool in the call-start logs.
