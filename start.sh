#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "=== Starting Botelier (repo root: $REPO_ROOT) ==="

# Install Python backend dependencies using uv (avoids Nix store restriction)
echo "=== Installing Python dependencies ==="
uv venv "$REPO_ROOT/.venv"
uv pip install --python "$REPO_ROOT/.venv/bin/python" \
  -r "$REPO_ROOT/botelier/backend/requirements.txt"

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
