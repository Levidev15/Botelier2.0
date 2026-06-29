#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "=== Starting Botelier (repo root: $REPO_ROOT) ==="

# In production the build step (scripts/build.sh) pre-installs Python
# dependencies into .venv, so we only install here when that venv is absent
# (e.g. local dev, or a first-run edge case).
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  echo "=== Using pre-built Python venv ==="
else
  echo "=== Installing Python dependencies (no pre-built venv found) ==="
  uv venv "$REPO_ROOT/.venv"
  uv pip install --python "$REPO_ROOT/.venv/bin/python" \
    -r "$REPO_ROOT/botelier/backend/requirements-replit.txt"
fi

# Activate the venv for all subsequent python commands
source "$REPO_ROOT/.venv/bin/activate"
echo "Python: $(python3 --version)"

# Start FastAPI backend in the background
cd "$REPO_ROOT/botelier/backend"
python3 -m uvicorn main:app --host 0.0.0.0 --port 3001 &
BACKEND_PID=$!
echo "Backend started (PID $BACKEND_PID) on port 3001"

# Start Next.js frontend in the foreground (keeps container alive)
cd "$REPO_ROOT/botelier/frontend"
export PORT=5000
export NODE_ENV=production
echo "Starting Next.js server on port 5000..."
exec node server.js
