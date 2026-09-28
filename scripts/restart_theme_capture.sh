#!/usr/bin/env bash
# 仅后端维护重启；发布人必须先核实当天日线/分钟归档已完成。
set -euo pipefail
cd "${BASH_SOURCE[0]%/*}/.."
mode="${1:-check}"
expected="${2:-}"
[[ "$mode" == check || "$mode" == restart ]] || { echo 'Use check or restart <full-commit-sha>'; exit 2; }
[[ "$(pwd -P)" == /opt/futu_trade_sys ]] || { echo 'Refusing non-production checkout'; exit 2; }
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || { echo 'Explicit full commit SHA required'; exit 2; }
[[ "$(git rev-parse HEAD)" == "$expected" ]] || { echo 'Release SHA mismatch'; exit 2; }
git diff --quiet HEAD -- simple_trade || { echo 'Production source is dirty'; exit 2; }
# 只允许香港时间17:30–20:00，避开港股、美股及16:30日线更新启动窗口。
# 时间窗不代表归档已成功，执行者还必须核对归档元数据和日线完成日志。
hhmm="$(TZ=Asia/Hong_Kong date +%H%M)"
[[ "$hhmm" > 1729 && "$hhmm" < 2000 ]] || { echo 'Outside approved post-close maintenance window'; exit 3; }
if [[ -f .env ]] && grep -Eq '^[[:space:]]*FORCE_MARKET[[:space:]]*=.*(HK|US)' .env; then
  echo 'Forced market override is unsafe for this maintenance'; exit 3
fi
systemctl is-active --quiet futu-trade-backend.service
curl --max-time 5 -fsS http://127.0.0.1:5001/health
[[ "$mode" == restart ]] || exit 0
old_pid="$(systemctl show futu-trade-backend.service -p MainPID --value)"
systemctl restart --no-block futu-trade-backend.service
for ((attempt=0; attempt<45; attempt++)); do
  new_pid="$(systemctl show futu-trade-backend.service -p MainPID --value)"
  if [[ "$new_pid" != 0 && "$new_pid" != "$old_pid" ]] && systemctl is-active --quiet futu-trade-backend.service; then
    if curl --max-time 3 -fsS http://127.0.0.1:5001/health; then
      echo "Backend restarted: old_pid=$old_pid new_pid=$new_pid"
      exit 0
    fi
  fi
  sleep 2
done
echo 'Backend did not become healthy; inspect service state before any retry'
exit 1
