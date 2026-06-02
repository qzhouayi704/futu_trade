#!/bin/bash
BASE=http://127.0.0.1:5001
endpoints=(
  /api/system/status
  /api/monitor/health
  /api/trading/positions/standalone
  /api/trading/positions/capital-flow
  /api/hot-stocks/top
  /api/sniper/signals
  /api/sniper/signal-pipeline
  /api/overnight-screen/dashboard
  /api/enhanced-heat/plate-alerts
  /api/enhanced-heat/volume-price-alerts
  /api/strategy/plate-strength
  /api/quote/trade-signals
  /api/sniper/ranking
  /api/high-turnover/stocks
  /api/sniper/simulated-trades
)
for ep in "${endpoints[@]}"; do
  t=$(curl -s -o /dev/null -w '%{time_total}' "${BASE}${ep}" --max-time 5)
  printf '%-50s %ss\n' "$ep" "$t"
done
