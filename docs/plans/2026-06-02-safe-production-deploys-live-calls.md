# Provider-Grade Safe Deploys For Live Voice Calls

## Summary

Current deploys can end active calls because ACA replaces/deactivates old replicas and the app shutdown path intentionally finalizes active calls with `forced_by="shutdown"` and cancels Pipecat pipelines. That cleanup is correct, but it must become a last-resort safety net, not the normal deploy path.

Implement blue-green deploys with ACA multiple revision mode, revision-pinned Twilio lifecycle URLs, and a Postgres-backed active-call runtime registry. New calls move to the new revision after health passes; existing calls stay pinned to the revision that answered `/incoming` until they finish.

Docs basis:

- [ACA revisions](https://learn.microsoft.com/en-us/azure/container-apps/revisions)
- [ACA revision management](https://learn.microsoft.com/en-us/azure/container-apps/revisions-manage)
- [ACA traffic splitting](https://learn.microsoft.com/en-us/azure/container-apps/traffic-splitting)
- [ACA blue-green deployment](https://learn.microsoft.com/en-us/azure/container-apps/blue-green-deployment)

## Key Changes

### Voice Runtime

- Add a `call_runtime_sessions` table for active call ownership:
  - `call_sid`, `call_log_id`, `account_id`, `revision_name`, `revision_label`, `deployment_id`, `replica_name`, `stream_sid`, `status`, `started_at`, `last_heartbeat_at`, `ended_at`, `end_reason`.
  - Unique index on `call_sid`.
  - Index active rows by `revision_name`, `revision_label`, `status`, and `last_heartbeat_at`.
- Register a runtime session when `/api/ws/call` successfully authenticates and `CallHandler.handle_call()` starts the pipeline.
- Heartbeat active calls every 10-15 seconds from the owning process.
- Mark the runtime session ended in `CallHandler` cleanup after transcript/finalization work finishes.
- Keep the existing shutdown finalizer, but deploys must not depend on it for normal call draining.

### Revision-Pinned Twilio URLs

- Add voice-specific callback URL helpers separate from generic `PUBLIC_BASE_URL`.
- For `/api/calls/incoming`, build TwiML using the current revision label URL:
  - `<Connect action="{revision_base}/api/calls/connect-complete">`
  - `<Stream url="wss://{revision_label_host}/api/ws/call" statusCallback="{revision_base}/api/calls/status">`
- Update warm transfer TwiML in `function_mapper.py` to use the same revision-pinned base for `/api/calls/transfer-status`.
- Update Twilio signature validation to reconstruct the URL from the actual forwarded request host for voice webhooks, so root incoming URLs and revision-label callback URLs both validate correctly.
- Do not move a revision label off an old revision until that revision has zero active runtime sessions.

### Deploy Control Plane

- Add a protected internal deploy endpoint:
  - `GET /api/deploy/drain-status?revision_name=...`
  - Requires `X-Botelier-Deploy-Token`.
  - Returns active count, stale heartbeat count, latest heartbeat time, deployment id, revision label, and drain-safe boolean.
  - Does not expose customer data or transcripts.
- Keep `/api/health` public and simple.
- Add env vars per revision:
  - `BOTELIER_DEPLOYMENT_ID`
  - `BOTELIER_REVISION_NAME`
  - `BOTELIER_REVISION_LABEL`
  - `BOTELIER_ACA_DEFAULT_FQDN`
  - `BOTELIER_DEPLOY_TOKEN`
- Compute revision callback base as `https://{BOTELIER_REVISION_LABEL}.{BOTELIER_ACA_DEFAULT_FQDN}` and verify it with `/api/health` before traffic switch.

### GitHub / ACA Workflow

- Set the Container App to `multiple` revision mode.
- Use two stable revision labels, `blue` and `green`.
- On deploy:
  - Detect current production revision and label.
  - Choose the opposite label for the new revision.
  - Deploy the new image with a deterministic revision suffix.
  - Assign the new label to the new revision.
  - Health-check the new label URL.
  - Switch 100% of new root traffic to the new revision.
  - Poll the old revision's drain status through Postgres.
  - Deactivate the old revision only when active count is zero and heartbeat state is healthy.
- If the drain window expires, do not force deactivate. Leave the old revision active, fail/stop the workflow after traffic has already moved, and emit a clear manual-action message.
- First rollout requires a bootstrap deployment when active calls are zero, because the currently deployed old code does not yet emit revision-pinned Twilio URLs.

## Test Plan

### Backend Tests

- Runtime session registers on authenticated WebSocket start.
- Runtime session heartbeats while active and ends in `CallHandler` cleanup.
- Cleanup still runs when the pipeline errors, transfers, or disconnects normally.
- Drain endpoint reports active, stale, and safe states correctly.
- Drain endpoint rejects missing/invalid deploy token.
- Twilio signature validation passes for both root host and revision-label host.
- Incoming TwiML uses revision-pinned WebSocket, status, and connect-complete URLs.
- Warm transfer TwiML uses revision-pinned transfer-status URL.

### Deploy Workflow Tests

- New revision can be deployed and health-checked by label before traffic switch.
- Root traffic moves to the new revision without deactivating the old revision.
- Old revision remains active while runtime sessions exist.
- Workflow stops without deactivation when active calls remain after the drain window.
- Workflow deactivates old revision only after active count reaches zero.

### Production Acceptance

- Start a live call on old revision.
- Deploy new revision.
- Confirm the live call stays connected.
- Confirm new calls hit the new revision.
- Confirm status/connect/transfer callbacks for the old call hit the old revision label.
- Confirm old revision deactivates only after the call ends.

## Assumptions

- Use Postgres for the active-call runtime registry.
- Use blue-green drain, not canary, for the first robust version.
- Drain timeout means stop and keep old revision alive, not force-kill.
- Do not add multiple Uvicorn workers; current in-memory Pipecat call state assumes one process per replica.
- Future very-large scale can move the runtime registry heartbeat path to Redis, but the interface should be isolated now so that swap does not affect voice logic.
