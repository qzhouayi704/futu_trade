#!/usr/bin/env bash
set -euo pipefail
cd "${BASH_SOURCE[0]%/*}/.."
mode="${1:-check}"
shift || true
default_runtime=".venv/bin/python"
[[ -x "$default_runtime" ]] || default_runtime=".venv/Scripts/python.exe"
runtime="${THEME_SMOKE_PYTHON:-$default_runtime}"
if [[ "$mode" == "check" ]]; then
  uv --cache-dir backtest_results/uv-cache run --offline --no-project --python "$runtime" python -X utf8 -c 'import sys, json, importlib.util, importlib.metadata as m; print(json.dumps({"executable":sys.executable,"version":sys.version,"dependencies":{name:m.version(name) for name in ("fastapi","starlette","pydantic","futu-api","python-socketio")},"optional_pytest":m.version("pytest") if importlib.util.find_spec("pytest") else None},ensure_ascii=False))'
elif [[ "$mode" == "test" ]]; then
  export THEME_CAPTURE_ISOLATED_SMOKE=1
  uv --cache-dir backtest_results/uv-cache run --offline --no-project --python "$runtime" python -B -X utf8 -m unittest tests.v2.test_theme_capture_lifecycle "$@"
elif [[ "$mode" == "regression" ]]; then
  uv --cache-dir backtest_results/uv-cache run --offline --no-project --python "$runtime" python -B -X utf8 -m pytest tests/v2/test_app_startup_order.py tests/test_quote_pipeline.py tests/test_market_helper.py tests/test_capital_trend_detector.py "$@"
else
  echo "Use check, test or regression; this script never launches a server."
  exit 2
fi
