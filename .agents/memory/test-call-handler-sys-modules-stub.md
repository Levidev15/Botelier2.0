---
name: A stray sys.modules stub breaks string-path patch() in full-suite test runs
description: test_voice_webhook_authenticity.py replaces sys.modules["botelier.voice.call_handler"] at import time with no teardown; any test using patch("botelier.voice.call_handler.X") (string path) breaks only when run as part of the full suite, not alone.
---

`tests/test_voice_webhook_authenticity.py` calls `_ensure_voice_stubs()`
at module level (import time, not inside a fixture), which does
`sys.modules["botelier.voice.call_handler"] = <bare stub module>` so it
can import `botelier.api.websockets` without pulling in pipecat's native
extensions. It never restores the real module afterward. Since pytest
imports every collected test file up front, this corruption is
permanent for the rest of the process once that file is collected —
independent of test execution order.

**Why this matters:** `unittest.mock.patch("botelier.voice.call_handler.X")`
(a string dotted path) re-resolves the module via `sys.modules` every
time it's entered. After the stub swap, that resolves to the bare stub,
which lacks real attributes like `logger` —
`AttributeError: <module 'botelier.voice.call_handler'> does not have
the attribute 'logger'`. This only reproduces when running the full
`tests/` directory (or any run that also collects
`test_voice_webhook_authenticity.py`); running the affected test file
alone passes, which makes it look like flaky/order-dependent test
pollution rather than a fixed, explainable cause.

**How to apply:** in any test that needs to patch something on
`botelier.voice.call_handler`, `import botelier.voice.call_handler as
call_handler_module` at the top of the file (captures a direct reference
before any later collection-time corruption) and use
`patch.object(call_handler_module, "X")` instead of the string-path form.
That reference — and anything imported via `from
botelier.voice.call_handler import name` — stays valid regardless of what
`sys.modules` points to later, because a function's `__globals__` is
bound to its defining module's `__dict__` at definition time, not
re-resolved through `sys.modules`.
