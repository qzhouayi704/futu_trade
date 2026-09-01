#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$PWD"
cd "$ROOT_DIR"

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

UV_CACHE_DIR="$ROOT_DIR/.uv-cache" uv run uvicorn simple_trade.asgi:app --host 127.0.0.1 --port 5001 --log-level warning &
BACKEND_PID=$!

(
  cd "$ROOT_DIR/futu-trade-frontend"
  npm run dev -- -p 3000
) &
FRONTEND_PID=$!

wait "$BACKEND_PID" "$FRONTEND_PID"
