#!/bin/bash
set -e

echo "Building Next.js frontend..."
cd botelier/frontend
npm run build
echo "Build complete."
