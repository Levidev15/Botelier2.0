#!/usr/bin/env bash
# Additional V1 gates only. Existing lifecycle, authentication and speech
# characterizations remain registered separately in voice-flow-candidate.yml.
set -Eeuo pipefail

refuse() {
  printf '%s\n' "Full Flow V1 checks require the exact candidate image in GitHub CI." >&2
  exit 2
}

[[ "${GITHUB_ACTIONS:-}" == "true" ]] || refuse
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || refuse
[[ "${IMAGE:-}" == "voice-flow-candidate:${GITHUB_SHA}" ]] || refuse
[[ -n "${RUNNER_TEMP:-}" && -n "${GITHUB_WORKSPACE:-}" ]] || refuse
[[ -n "${EVIDENCE:-}" && "$EVIDENCE" == "$RUNNER_TEMP/"* ]] || refuse

root="${GITHUB_WORKSPACE%/}"
trial="/ci/examples/features/botelier-flow-trial"
mkdir -p "$EVIDENCE"
checkpoint="$EVIDENCE/full-flow-v1-checkpoint.json"
# A failed retry must not retain a completed checkpoint from an earlier run.
# Failure logs remain available, but completion is emitted only after every gate.
rm -f -- "$checkpoint" "$checkpoint.tmp"

pure_tests=(
  test_native_graph.py
  test_native_graph_imports.py
  test_native_values.py
  test_native_output_values.py
  test_native_request_templates.py
  test_native_json_templates.py
  test_native_booking_graph.py
  test_reservation_quote_contract.py
  test_native_quote_actions.py
  test_native_quote_graph.py
)
runtime_tests=(
  test_native_prepared_transport.py
  test_native_graph_runtime.py
  test_native_caller_grounding.py
  test_native_quote_privacy.py
  test_native_graph_corrections.py
  test_native_graph_text_host.py
  test_native_graph_host_selection.py
  test_native_effect_actions.py
  test_native_messaging.py
  test_native_integration_binding.py
)
editor_tests=(
  test_native_actions.py
  test_native_capabilities.py
  test_native_tool_sources.py
  test_native_integration_resolution.py
  test_native_effect_ledger.py
  test_native_record_actions.py
  test_flow_response_preview.py
  test_flow_response_preview_routes.py
  test_native_flow_recovery.py
  test_native_quote_bridge.py
  test_native_quote_delivery.py
  test_native_sms_submission.py
  test_native_booking_journey.py
)
mcp_tests=(
  test_mcp_native_policy.py
)

run_boundary() {
  local label="$1" guard="$2"
  shift 2
  local name
  local -a tests=() profile_env=()
  for name in "$@"; do
    [[ "$name" =~ ^test_[a-z0-9_]+\.py$ ]] || refuse
    [[ -f "$root/examples/features/botelier-flow-trial/$name" ]] || {
      printf 'Missing explicitly registered V1 test: %s\n' "$name" >&2
      exit 2
    }
    tests+=("$trial/$name")
  done

  if [[ "$label" == "editor" || "$label" == "mcp_management" ]]; then
    profile_env=(
      NEXTAUTH_SECRET=botelier-editor-trial-only-synthetic-nextauth-secret-v1
      INTEGRATION_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
      BOTELIER_ENV=development BOTELIER_NATIVE_FLOWS_DEV=1
      NEXTAUTH_URL=http://127.0.0.1:5011
    )
  elif [[ "$label" == "runtime" ]]; then
    profile_env=(
      HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
      HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1
    )
  fi

  # No CI credentials, network, host ports, writable checkout or database are
  # forwarded. Test tools are a separate read-only mount, not image mutations.
  timeout --signal=TERM --kill-after=10s 600 \
    docker run --rm --network none --read-only \
      --tmpfs /tmp:rw,nosuid,nodev,size=256m \
      -v "$root/examples/features/botelier-flow-trial:$trial:ro" \
      -v "$RUNNER_TEMP/voice-test-tools:/test-tools:ro" \
      --entrypoint env "$IMAGE" -i \
      PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp NLTK_DATA=/opt/nltk_data \
      PYTHONPATH=/test-tools PYTHONDONTWRITEBYTECODE=1 \
      PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 LOGURU_LEVEL=ERROR \
      "${profile_env[@]}" \
      python -B "$trial/$guard" \
      --backend-root /app \
      --package-root /usr/local/lib/python3.11/site-packages/pipecat \
      --tests "${tests[@]}" \
    2>&1 | tee "$EVIDENCE/full-flow-v1-$label.log"
}

run_mcp_management_self_test() {
  local log="$EVIDENCE/full-flow-v1-mcp_management_self_test.log"
  # This is a separate container from the zero-block suite; its twelve expected
  # denials must never be reset, hidden, or attributed to another guard profile.
  timeout --signal=TERM --kill-after=10s 600 \
    docker run --rm --network none --read-only \
      --tmpfs /tmp:rw,nosuid,nodev,size=256m \
      -v "$root/examples/features/botelier-flow-trial:$trial:ro" \
      -v "$RUNNER_TEMP/voice-test-tools:/test-tools:ro" \
      --entrypoint env "$IMAGE" -i \
      PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp NLTK_DATA=/opt/nltk_data \
      PYTHONPATH=/test-tools PYTHONDONTWRITEBYTECODE=1 \
      PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 LOGURU_LEVEL=ERROR \
      NEXTAUTH_SECRET=botelier-editor-trial-only-synthetic-nextauth-secret-v1 \
      INTEGRATION_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
      BOTELIER_ENV=development BOTELIER_NATIVE_FLOWS_DEV=1 \
      NEXTAUTH_URL=http://127.0.0.1:5011 \
      python -B "$trial/mcp_management_guard.py" \
      --backend-root /app \
      --package-root /usr/local/lib/python3.11/site-packages/pipecat \
      --self-test \
    2>&1 | tee "$log"
  if ! grep -Eq '"expected_denials"[[:space:]]*:[[:space:]]*12' "$log"; then
    printf '%s\n' "MCP-management self-test did not report all twelve expected denials." >&2
    exit 2
  fi
}

run_boundary pure application_guard.py "${pure_tests[@]}"
run_boundary runtime lifecycle_guard.py "${runtime_tests[@]}"
run_boundary editor editor_guard.py "${editor_tests[@]}"
run_mcp_management_self_test
# The real management suite has its own process and must report zero blocks.
run_boundary mcp_management mcp_management_guard.py "${mcp_tests[@]}"
grep -Fxq \
  "MCP_MANAGEMENT_GUARD_BLOCKED_ATTEMPTS=0" \
  "$EVIDENCE/full-flow-v1-mcp_management.log"

printf '{"commit":"%s","profile":"full-flow-v1","result":"passed","completed_boundaries":["application_guard","lifecycle_guard","editor_guard","mcp_management_self_test","mcp_management_guard"],"network":"none","production_activation":false,"manual_audio_certified":false,"providers":"synthetic","database":"synthetic","phone_routing_changed":false}\n' \
  "$GITHUB_SHA" > "$checkpoint.tmp"
mv -- "$checkpoint.tmp" "$checkpoint"
