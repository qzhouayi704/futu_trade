#!/usr/bin/env bash
set -euo pipefail
cd "${BASH_SOURCE[0]%/*}/.."
mode="${1:-run}"
shift || true
default_runtime=".venv/bin/python"
[[ -x "$default_runtime" ]] || default_runtime="C:/Users/ZHOUYICAN/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
runtime="${SWING_PYTHON:-$default_runtime}"
if [[ "$mode" == "test" ]]; then
  uv --cache-dir backtest_results/uv-cache run --offline --no-project --python "$runtime" python -X utf8 -m unittest tests.v2.test_swing_study tests.v2.test_minute_entry_study tests.v2.test_history_data_audit tests.v2.test_legacy_swing_study tests.v2.test_forward_study_readiness tests.v2.test_cross_day_research tests.v2.test_forward_source_intake tests.v2.test_forward_stage_probe tests.v2.test_forward_episode_probe tests.v2.test_forward_theme_audit tests.v2.test_theme_capture "$@"
else
  uv --cache-dir backtest_results/uv-cache run --offline --no-project --python "$runtime" python -X utf8 -m "scripts.analysis.swing_study.$mode" "$@"
fi
