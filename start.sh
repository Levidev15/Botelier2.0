#!/bin/bash
set -e

# Start FastAPI backend in the background
cd botelier/backend
python -m uvicorn main:app --host 0.0.0.0 --port 3001 &
BACKEND_PID=$!

echo "Backend started (PID $BACKEND_PID) on port 3001"

# Move back to repo root then start the Next.js frontend in the foreground.
# Keeping the frontend in the foreground keeps the container alive;
# the backend subprocess is tied to this shell and will be cleaned up
# automatically when the container stops.
cd ../../botelier/frontend
export PORT=5000
export NODE_ENV=production

echo "Starting Next.js server on port 5000..."
exec node server.js
