---
name: Universal API Adapter (DYNAMIC_OPERATION)
description: Gotchas and durable rules for the DYNAMIC_OPERATION tool type and its supporting pipeline.
---

## IntegrationAPIConfig does NOT have integration_type_id or property_id

`IntegrationAPIConfig` (services/integration_runtime/types.py) only accepts:
`integration_id`, `endpoint_id`, `method`, `path`, `endpoint_template`, `headers`,
`body_template`, `timeout`, `retry_count`, `query_param_overrides`,
`response_variables`, and on_*_message strings.

Do NOT pass `integration_type_id`, `property_id`, or other fields — they will
raise a TypeError at construction time.

**Why:** The dataclass is strict; property scoping is handled internally by
IntegrationClient using the stored AccountIntegration.property_id.

## check_account_permission is in auth.middleware, not auth.permissions

```python
from botelier.auth.middleware import check_account_permission, get_current_user
```

**Why:** `botelier.auth.permissions` defines permission SCHEMAS, not the enforcement
function. Every other API file imports from `auth.middleware`.

## Tool slug must be namespaced by connection slug

`_derive_tool_name` in `operation_publisher.py` creates
`{safe_conn_slug}_{fn_name}` to prevent two connections on the same account
from registering the same function name with the LLM.

**Why:** Two connections from the same imported integration type would produce
identical `fn_name` values. The LLM tool list must have unique names or
execution is undefined.

## DYNAMIC_OPERATION routes ONLY through IntegrationAPIConfig, never legacy_config

All 3-channel handlers (`_map_dynamic_operation`, `_execute_dynamic_operation`,
`_build_dynamic_operation_tool_schemas`) build an `IntegrationAPIConfig` and
pass it as `integration_config=config` to `ActionExecutionRequest` — never
`legacy_config`.

**Why:** The certified pipeline (property isolation, resilience, redaction) only
activates when the `integration_config` path is taken. `legacy_config` bypasses
all of these guards.

## How to apply

When adding new DYNAMIC_OPERATION handler paths or extending the
integration_builder API: check these three things first before writing code.
