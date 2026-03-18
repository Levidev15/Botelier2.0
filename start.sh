#!/bin/bash
set -e

# Always run from the repo root regardless of where Replit calls this from
REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "=== Starting Botelier ==="
echo "Repo root: $REPO_ROOT"

# Activate the virtual environment created by build.sh
source "$REPO_ROOT/.venv/bin/activate"
echo "Python venv activated: $(python3 --version)"

# Start FastAPI backend in the background
cd "$REPO_ROOT/botelier/backend"
python3 -m uvicorn main:app --host 0.0.0.0 --port 3001 &
BACKEND_PID=$!
echo "Backend started (PID $BACKEND_PID) on port 3001"

# Start Next.js frontend in the foreground (keeps the container alive)
cd "$REPO_ROOT/botelier/frontend"
export PORT=5000
export NODE_ENV=production
echo "Starting Next.js server on port 5000..."
exec node server.js
