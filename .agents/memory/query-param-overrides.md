---
name: Query-param overrides & the api-tester secrets asymmetry
description: How per-node query_param_overrides flow through the three API-request execution paths, and the deliberate secrets-substitution gap in the api-tester path.
---

# Query-param overrides across the three API-request paths

API-request nodes can carry a sparse per-node `query_param_overrides`
(`api.queryParamOverrides` in the frontend store) that overrides an integration
endpoint's seed query-param values.

**Single chokepoint:** all three paths converge on `IntegrationClient._build_url`
(`integration_client.py`), which resolves each endpoint-declared param as
`overrides[key] if key in overrides else seed value`. Consequences:
- Overrides for keys **not** declared on the endpoint are silently ignored (the
  loop only iterates `endpoint_def["query_params"]`) — overrides can't inject
  arbitrary/undeclared params.
- An **empty-string** override on a **required** param still fails closed
  (`_MissingRequiredVariables`); empty on an optional param is omitted.

**The asymmetry (real trap):** the live-call and simulator paths go through
`flow_executor._handle_integration_api_request`, which resolves `{{secrets.*}}`
inside overrides before calling `_build_url`. The **api-tester path does NOT**
substitute `{{secrets.*}}`.

**Why:** pre-existing, architect-approved. The api-tester intentionally never
substituted secrets even before overrides existed; overrides just inherit that.

**How to apply:** a secret-referencing override (`{{secrets.FOO}}`) will
**fail-fast in the Run-test panel but work in a live call / simulator**. Don't
"fix" this by adding secret substitution to the api-tester without revisiting
the original decision. When changing override plumbing, keep all three paths
threading through the single `_build_url` — do not fork the resolution logic.
