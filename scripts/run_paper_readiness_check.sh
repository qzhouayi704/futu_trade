#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --offline python scripts/check_paper_readiness.py "$@"
