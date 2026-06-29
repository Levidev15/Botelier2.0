#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "=== Botelier build (repo root: $REPO_ROOT) ==="

echo "=== Installing Python dependencies ==="
uv venv "$REPO_ROOT/.venv"
uv pip install --python "$REPO_ROOT/.venv/bin/python" \
  -r "$REPO_ROOT/botelier/backend/requirements-replit.txt"
echo "Python dependencies installed."

echo "=== Building Next.js frontend ==="
npm run build --prefix "$REPO_ROOT/botelier/frontend"
echo "Frontend build complete."
