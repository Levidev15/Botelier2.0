#!/bin/bash
set -e

cd botelier/frontend
echo "=== Building Next.js frontend ==="
npm run build
echo "=== Build complete ==="
