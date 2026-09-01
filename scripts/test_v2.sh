#!/usr/bin/env bash
set -euo pipefail

uv run pytest tests/v2 "$@"
