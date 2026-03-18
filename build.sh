#!/bin/bash
set -e

# Always run from the repo root regardless of where Replit calls this from
cd "$(dirname "$0")"

echo "=== Installing Python backend dependencies ==="
python3 -m pip install --upgrade pip
python3 -m pip install -r botelier/backend/requirements.txt

echo "=== Building Next.js frontend ==="
cd botelier/frontend
npm run build

echo "=== Build complete ==="
