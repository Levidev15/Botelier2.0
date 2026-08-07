---
name: Adapter runtime guardrails
description: Durable invariants of the certified integration client and operation test/publish parity — header precedence, path encoding, size caps, and the single-normalizer parity rule.
---

## Rules

- **Auth headers always win over config headers.** Adapter auth headers are applied last with case-insensitive collision removal.
  **Why:** stored/draft header maps are operator- and LLM-editable JSON; they must never spoof or blank credentials.
  **How to apply:** any new header-merge path (new adapter, new tester) must keep auth-last ordering.

- **URL path substitutions are percent-encoded; body/query template substitution is not.** A path variable can only occupy one segment.
  **Why:** un-encoded values containing `/ ? #` rewrite the path or smuggle a query string.
  **How to apply:** if an API legitimately needs a multi-segment placeholder, that needs an explicit trusted raw-path mode — don't just drop the encoding.

- **Response caps must be transport-level, pre-parse (streamed read + Content-Length precheck).** The redaction layer's size bound runs post-parse and cannot protect memory. When testing caps, `httpx.MockTransport` with `content=` only proves post-buffer rejection — use a true async streaming transport that counts pulled chunks.

- **Tested and published request shapes must flow through ONE normalizer + ONE config builder** (`normalize_request_overrides` → policy row → publish config → shared channel builder). Any new channel dispatcher or tester must use the shared builder, never hand-build the runtime config.
  **Why:** a completion review rejected an earlier version where the tester accepted draft request settings that publish never persisted — a green test validated behavior live channels would never execute.

- **Spec-DERIVED origins (extracted server URL, absolute token URLs) get the same fail-closed SSRF/origin validation as user-supplied overrides, before commit.** Validating only user input leaves the spec content itself as an unvalidated origin source.
