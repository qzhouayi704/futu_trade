#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --offline python scripts/paper_capacity_benchmark.py "$@"
