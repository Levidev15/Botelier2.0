#!/usr/bin/env bash
# Candidate-only auth/MFA protocol and schema checks, never a customer database.
set -euo pipefail

[[ "${GITHUB_ACTIONS:-}" == true ]] || {
  echo "Container auth checks are CI-only" >&2; exit 2;
}
[[ "${IMAGE:-}" =~ ^voice-flow-candidate:[0-9a-f]{40}$ ]] || {
  echo "An exact candidate image is required" >&2; exit 2;
}
: "${RUNNER_TEMP:?}" "${GITHUB_WORKSPACE:?}" "${EVIDENCE:?}"
frontend="$GITHUB_WORKSPACE/botelier/frontend"
dependencies="${FRONTEND_DEPENDENCIES:-"$frontend/node_modules"}"
dependencies="${dependencies%/}"
encoder_root=$(dirname "$dependencies")
[[ "$(basename "$dependencies")" == node_modules \
   && -f "$encoder_root/package.json" && -d "$dependencies/next-auth" ]] || {
  echo "The candidate's locked frontend dependencies are required" >&2; exit 2;
}
node_binary=$(command -v node)
socket=$(mktemp -d "$RUNNER_TEMP/voice-auth-socket.XXXXXX")
chmod 0777 "$socket"
db_id=""
cleanup() {
  local result=$?
  if [[ -n "$db_id" ]]; then
    docker logs "$db_id" > "$EVIDENCE/auth-database.log" 2>&1 \
      || echo "Fixture logs unavailable" >&2
    docker inspect --format '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}' \
      "$db_id" > "$EVIDENCE/auth-database-state.log" 2>&1 \
      || echo "Fixture state unavailable" >&2
    if [[ "$result" != 0 ]]; then
      cat "$EVIDENCE/auth-database-state.log" "$EVIDENCE/auth-database.log" >&2
    fi
    docker rm -f "$db_id" >/dev/null
  fi
  rm -rf -- "$socket"
  return "$result"
}
trap cleanup EXIT
mkdir -p "$EVIDENCE"

# Password-free trust is limited to a temporary Unix socket inside network-none
# containers. Neither the temporary initializer nor final server listens on TCP.
db_id=$(docker run -d --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --tmpfs /var/run/postgresql:rw,nosuid,nodev,size=16m \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,nodev,size=256m \
  -v "$socket:/tmp/botelier-auth-fixture:rw" \
  -e POSTGRES_DB=voice_auth_fixture -e POSTGRES_HOST_AUTH_METHOD=trust \
  postgres:16.10-bookworm \
  -c listen_addresses= \
  -c unix_socket_directories=/var/run/postgresql,/tmp/botelier-auth-fixture \
  -c unix_socket_permissions=0777 -c fsync=on -c synchronous_commit=on)
ready=false
for _ in {1..40}; do
  if docker exec "$db_id" sh -c 'test "$(cat /proc/1/comm)" = postgres' \
      && docker exec "$db_id" pg_isready -h /tmp/botelier-auth-fixture \
      -U postgres -d voice_auth_fixture >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 0.5
done
if [[ "$ready" != true ]]; then
  docker logs "$db_id" >&2
  exit 1
fi
printf '{"image":"%s","database":"disposable_postgresql_16_10","transport":"unix_socket","network":"none","customer_database":false,"signed_in_ui_verified":false}\n' \
  "$IMAGE" > "$EVIDENCE/auth-checkpoint.json"

for check in self-test protocol postgres; do
  case "$check" in
    self-test) set -- --self-test ;;
    protocol)
      set -- --tests /ci/auth-tests/test_authenticator_mfa.py \
        /ci/examples/features/botelier-flow-trial/test_auth_enforcement.py
      ;;
    postgres)
      set -- --postgres --tests /ci/auth-tests/test_mfa_postgres_races.py \
        /ci/examples/features/botelier-flow-trial/test_mfa_schema_upgrade.py
      ;;
  esac
  # Mount the already-populated package cache once: a nested bind cannot create
  # node_modules inside a read-only source mount. Node/NextAuth remain test-only
  # inputs; the guard permits only its fixed synthetic encoder.
  docker run --rm --network none --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,size=256m \
    -v "$socket:/tmp/botelier-auth-fixture:ro" \
    -v "$node_binary:/test-node/node:ro" \
    -v "$encoder_root:/frontend:ro" \
    -v "$GITHUB_WORKSPACE/botelier/backend/tests:/ci/auth-tests:ro" \
    -v "$GITHUB_WORKSPACE/examples/features/botelier-flow-trial:/ci/examples/features/botelier-flow-trial:ro" \
    -v "$RUNNER_TEMP/voice-test-tools:/test-tools:ro" \
    --entrypoint env "$IMAGE" -i \
    PATH=/test-node:/usr/local/bin:/usr/bin:/bin HOME=/tmp \
    PYTHONPATH=/test-tools PYTHONDONTWRITEBYTECODE=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 LOGURU_LEVEL=ERROR \
    NEXTAUTH_SECRET=botelier-auth-trial-only-synthetic-nextauth-secret-v1 \
    INTEGRATION_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
    python -B /ci/examples/features/botelier-flow-trial/auth_guard.py \
    --diagnose --backend-root /app --frontend-root /frontend \
    --node-binary /test-node/node "$@" \
    2>&1 | tee "$EVIDENCE/auth-$check.log"
done
