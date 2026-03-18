#!/bin/bash
set -e

# Always run from the repo root regardless of where Replit calls this from
cd "$(dirname "$0")"

echo "=== Creating Python virtual environment ==="
uv venv .venv

echo "=== Installing Python backend dependencies ==="
uv pip install --python .venv/bin/python -r botelier/backend/requirements.txt

echo "=== Building Next.js frontend ==="
cd botelier/frontend
npm run build

echo "=== Build complete ==="
