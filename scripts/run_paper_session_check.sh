#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --offline python scripts/inspect_paper_session.py "$@"
