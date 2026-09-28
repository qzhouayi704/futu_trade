#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --offline python -m scripts.analysis.minute_entry_study.run "$@"
