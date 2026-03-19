#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "=== Post-merge setup (repo root: $REPO_ROOT) ==="

# Install Python backend dependencies
echo "=== Installing Python backend dependencies ==="
pip install -q -r "$REPO_ROOT/botelier/backend/requirements.txt"

# Install Node.js frontend dependencies
echo "=== Installing Node.js frontend dependencies ==="
npm install --prefix "$REPO_ROOT/botelier/frontend" --legacy-peer-deps --silent

echo "=== Post-merge setup complete ==="
