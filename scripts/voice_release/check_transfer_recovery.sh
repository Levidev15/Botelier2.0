#!/usr/bin/env bash
# Disposable CI-only PostgreSQL. No host ports, provider network or credentials.
set -euo pipefail

[[ "${GITHUB_ACTIONS:-}" == true ]] || { echo "Recovery database is CI-only" >&2; exit 2; }
[[ "${IMAGE:-}" =~ ^voice-flow-candidate:[0-9a-f]{40}$ ]] || {
  echo "An exact candidate image is required" >&2; exit 2;
}
: "${RUNNER_TEMP:?}" "${GITHUB_WORKSPACE:?}" "${EVIDENCE:?}"
socket=$(mktemp -d "$RUNNER_TEMP/voice-recovery-socket.XXXXXX")
chmod 0777 "$socket"
db_id=""
cleanup() {
  local result=$?
  if [[ -n "$db_id" ]]; then
    docker logs "$db_id" > "$EVIDENCE/recovery-database.log" 2>&1 \
      || echo "Fixture log capture unavailable" >&2
    docker inspect --format '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}' \
      "$db_id" > "$EVIDENCE/recovery-database-state.log" 2>&1 \
      || echo "Fixture state capture unavailable" >&2
    if [[ "$result" != 0 ]]; then
      docker exec "$db_id" pg_isready -h /offline-db -U postgres \
        -d voice_recovery_fixture >> "$EVIDENCE/recovery-database-state.log" 2>&1 \
        || echo "Fixture server-side readiness failed" >> "$EVIDENCE/recovery-database-state.log"
      docker exec "$db_id" stat -c '%F %a %u:%g %d:%i' /offline-db/.s.PGSQL.5432 \
        >> "$EVIDENCE/recovery-database-state.log" 2>&1 \
        || echo "Fixture server socket unavailable" >> "$EVIDENCE/recovery-database-state.log"
      docker run --rm --network none --read-only -v "$socket:/offline-db:ro" \
        --entrypoint env postgres:16.10-bookworm -i PATH=/usr/bin:/bin \
        stat -c '%F %a %u:%g %d:%i' /offline-db/.s.PGSQL.5432 \
        >> "$EVIDENCE/recovery-database-state.log" 2>&1 \
        || echo "Fixture client socket unavailable" >> "$EVIDENCE/recovery-database-state.log"
      cat "$EVIDENCE/recovery-database-state.log" "$EVIDENCE/recovery-database.log" >&2
    fi
    docker rm -f "$db_id" >/dev/null
  fi
  rm -rf -- "$socket"
  return "$result"
}
trap cleanup EXIT
mkdir -p "$EVIDENCE"

# The official image permits password-free bootstrap only with this fixture
# setting. It is NOT production auth: there is no TCP listener, container
# networking or published port, and clients see only this temporary Unix socket.
# The image's bootstrap psql clears PGHOST and needs the default local socket
# too. That internal directory is never shared with the test clients.
db_id=$(docker run -d --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=32m \
  --tmpfs /var/run/postgresql:rw,nosuid,nodev,size=16m \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,nodev,size=256m \
  -v "$socket:/offline-db:rw" \
  -e POSTGRES_DB=voice_recovery_fixture -e POSTGRES_HOST_AUTH_METHOD=trust \
  postgres:16.10-bookworm \
  -c listen_addresses= -c unix_socket_directories=/var/run/postgresql,/offline-db \
  -c unix_socket_permissions=0777 -c fsync=on -c synchronous_commit=on)
ready=false
for _ in {1..40}; do
  # The official entrypoint starts and stops a temporary initializer. Its
  # pg_isready success is not readiness of the final PID-1 server.
  if docker exec "$db_id" sh -c 'test "$(cat /proc/1/comm)" = postgres' \
      && docker exec "$db_id" pg_isready -h /offline-db -U postgres \
      -d voice_recovery_fixture >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 0.5
done
if [[ "$ready" != true ]]; then
  docker logs "$db_id" >&2
  exit 1
fi

printf '{"image":"%s","database":"disposable_postgresql_16_10","transport":"unix_socket","network":"none","independent_test_processes":3,"customer_database":false,"server_boot_tested":false}\n' \
  "$IMAGE" > "$EVIDENCE/recovery-checkpoint.json"

# Seed and resume MUST be different containers/processes against the same fixture
# database. The second process cannot retain a Python guard, cache or connection.
for suite in test_transfer_attempts_postgres.py test_recovery_process_seed.py test_recovery_process_resume.py; do
  printf '\nRECOVERY_PROCESS=%s\n' "$suite" | tee -a "$EVIDENCE/transfer-recovery.log"
  docker run --rm --network none --read-only \
    --tmpfs /tmp:rw,nosuid,nodev,size=256m \
    -v "$socket:/offline-db:ro" \
    -v "$GITHUB_WORKSPACE/examples/features/botelier-flow-trial:/ci/examples/features/botelier-flow-trial:ro" \
    -v "$RUNNER_TEMP/voice-test-tools:/test-tools:ro" \
    --entrypoint env "$IMAGE" -i \
    PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp NLTK_DATA=/opt/nltk_data \
    PYTHONPATH=/test-tools PYTHONDONTWRITEBYTECODE=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 LOGURU_LEVEL=ERROR \
    python -B /ci/examples/features/botelier-flow-trial/recovery_guard.py \
    --diagnose --backend-root /app \
    --package-root /usr/local/lib/python3.11/site-packages/pipecat \
    --tests "/ci/examples/features/botelier-flow-trial/$suite" \
    2>&1 | tee -a "$EVIDENCE/transfer-recovery.log"
done
