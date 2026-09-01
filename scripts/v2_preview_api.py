#!/usr/bin/env python3
"""Local read-only fixture API for visually checking the V2 workbench."""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import urlparse


NOW = datetime.now().astimezone().isoformat()


def candidate(code, name, status, score, net15, net60, buys, sells):
    return {
        "stock_code": code, "stock_name": name, "status": status, "version": 4,
        "confirmed_price": 100.0, "peak_price": 106.2, "updated_at": NOW,
        "reason_code": "MULTI_INFLOW_PRICE_ACCEPTED", "score": score, "quality": "GOOD",
        "quote": {"last_price": 104.8, "prev_close": 99.2},
        "market_context": {"market_breadth": 0.43, "sector_breadth": 0.61, "market_regime": "WEAK"},
        "price_position": {"daily_percentile": 0.54, "structure": "RECOVERING", "distance_to_ma20": 2.1},
        "capital_windows": [
            {"window_seconds": 900, "main_net": net15, "independent_buy_events": buys, "independent_sell_events": sells, "buy_sell_ratio": 2.4},
            {"window_seconds": 3600, "main_net": net60, "independent_buy_events": buys + 2, "independent_sell_events": sells + 1, "buy_sell_ratio": 2.1},
        ],
    }


CANDIDATES = [
    candidate("HK.00100", "MINIMAX-W", "CONFIRMED", 88.6, 18_600_000, 42_800_000, 5, 1),
    candidate("HK.06082", "壁仞科技", "WATCHING", 81.2, 8_200_000, 22_100_000, 3, 1),
    candidate("HK.01888", "建滔积层板", "SETUP", 76.4, 5_400_000, 17_800_000, 3, 2),
    candidate("HK.02513", "智谱", "WATCHING", 73.9, -2_100_000, 9_600_000, 2, 2),
]

POSITIONS = [{
    "stock_code": "HK.01347", "stock_name": "华虹宏力", "status": "STALLED",
    "opened_at": NOW, "cost_price": 151.2, "peak_price": 162.8, "trough_price": 149.5,
    "mfe_pct": 7.67, "mae_pct": -1.12, "stalled_since": NOW, "updated_at": NOW,
    "reason_code": "POSITION_STALLED", "last_action": "ROTATE",
    "position": {"current_price": 159.4, "current_return_pct": 5.42, "quantity": 1000},
    "efficiency": {"score": 52.4, "current_return_pct": 5.42, "drawdown_from_peak_pct": -2.09, "flow_drawdown_ratio": 0.68, "slope_15m_pct": 0.08, "minutes_since_high": 38},
    "rotation": {"buy_stock_code": "HK.00100", "candidate_score": 88.6, "held_efficiency_score": 52.4, "net_advantage_score": 19.2, "estimated_cost_pct": 0.35},
}]

DECISIONS = [
    {"event_id": "e1", "event_type": "ROTATION_PROPOSED", "stock_code": "HK.01347", "exchange_time": NOW, "old_state": "STALLED", "new_state": "ROTATION_READY", "reason_code": "CONFIRMED_CANDIDATE_NET_ADVANTAGE", "strategy_version": "v2-preview"},
    {"event_id": "e2", "event_type": "BUY_CONFIRMED", "stock_code": "HK.00100", "exchange_time": NOW, "old_state": "WATCHING", "new_state": "CONFIRMED", "reason_code": "MULTI_INFLOW_PRICE_ACCEPTED", "strategy_version": "v2-preview"},
    {"event_id": "e3", "event_type": "CANDIDATE_UPDATED", "stock_code": "HK.06082", "exchange_time": NOW, "old_state": "SETUP", "new_state": "WATCHING", "reason_code": "SINGLE_INFLOW_OBSERVE", "strategy_version": "v2-preview"},
]

OUTCOMES = [{
    "event_id": f"o{index}", "stock_code": item[0], "stock_name": item[1], "event_type": item[2],
    "signal_time": NOW, "signal_price": 100, "mfe_pct": item[3], "mae_pct": item[4],
    "close_return_pct": item[5], "next_day_return_pct": item[6],
    "reached_1_5": item[3] >= 1.5, "reached_3": item[3] >= 3, "reached_5": item[3] >= 5,
    "time_to_1_5_seconds": 1200 if item[3] >= 1.5 else None,
    "time_to_3_seconds": 2400 if item[3] >= 3 else None,
    "time_to_5_seconds": 4200 if item[3] >= 5 else None,
    "hold_control_return_pct": item[7], "rotation_return_pct": item[8],
} for index, item in enumerate([
    ("HK.00100", "MINIMAX-W", "BUY_CONFIRMED", 8.4, -1.2, 6.8, 5.4, None, None),
    ("HK.06082", "壁仞科技", "BUY_CONFIRMED", 5.7, -0.8, 4.1, 2.8, None, None),
    ("HK.01888", "建滔积层板", "BUY_CONFIRMED", 3.6, -2.1, 1.9, 1.2, None, None),
    ("HK.00100", "MINIMAX-W", "ROTATION_PROPOSED", 6.2, -0.9, 4.8, 3.9, 0.6, 4.8),
])]


def distribution():
    bins = [
        {"label": "<-3%", "count": 0, "ratio": 0}, {"label": "-3~0%", "count": 0, "ratio": 0},
        {"label": "0~1.5%", "count": 0, "ratio": 0}, {"label": "1.5~3%", "count": 1, "ratio": .25},
        {"label": "3~5%", "count": 1, "ratio": .25}, {"label": ">=5%", "count": 2, "ratio": .5},
    ]
    metric = {"count": 4, "percentiles": {"p10": 3.6, "p25": 4.1, "p50": 5.95, "p75": 6.75, "p90": 7.74, "p95": 8.07}, "max": 8.4, "min": 3.6, "mean": 5.98}
    return {"sample_count": 4, "mfe": {**metric, "histogram": bins}, "mae": metric, "close_return": {**metric, "histogram": bins}, "rotation_advantage": {**metric, "percentiles": {**metric["percentiles"], "p50": 4.2}}, "milestones": {"reached_1_5_ratio": 1, "reached_3_ratio": 1, "reached_5_ratio": .75}, "items": OUTCOMES}


def cohort_metric(count, success, mfe=3.2, key=None):
    metric = {
        "count": count, "percentiles": {"p10": 0.8, "p25": 1.4, "p50": mfe, "p75": 5.1, "p90": 7.2, "p95": 8.1},
        "max": 9.4, "min": -1.2, "mean": mfe,
    }
    return {
        "key": key, "sample_count": count, "completed_count": count,
        "reached_1_5_ratio": success, "reached_3_ratio": max(0, success - .18),
        "reached_5_ratio": max(0, success - .36), "mfe": metric, "mae": metric,
        "close_return": metric, "median_time_to_1_5_seconds": 1680 if count else None,
    }


def shadow_acceptance():
    entry = cohort_metric(24, .708, 3.8)
    control = cohort_metric(37, .432, 1.35)
    rotation = {**cohort_metric(6, .667, 4.1), "comparable_count": 6,
                "advantage": {**entry["mfe"], "percentiles": {**entry["mfe"]["percentiles"], "p50": 1.7}},
                "rotation_win_ratio": .667}
    daily = [{
        "trade_date": f"2026-08-{day:02d}", "entry": cohort_metric(day % 4 + 1, .75),
        "first_inflow": cohort_metric(day % 5 + 2, .45), "rotation": rotation,
    } for day in range(31, 23, -1)]
    return {
        "target_days": 10, "observed_days": 8, "ready": False,
        "date_range": {"start": "2026-08-24", "end": "2026-08-31"},
        "sample_count": 67, "entry_summary": entry, "first_inflow_control": control,
        "rotation_summary": rotation,
        "cohorts": {
            "market_regime": [cohort_metric(15, .80, 4.4, "NORMAL"), cohort_metric(9, .556, 2.1, "WEAK")],
            "confirmation_window": [cohort_metric(18, .778, 4.0, "FAST_15M"), cohort_metric(6, .50, 2.2, "SLOW_60M")],
            "inflow_frequency": [cohort_metric(37, .432, 1.35, "SINGLE"), cohort_metric(16, .688, 3.6, "MULTI_2"), cohort_metric(8, .75, 4.5, "MULTI_3_PLUS")],
            "outflow_context": [cohort_metric(39, .641, 3.4, "NO_LARGE_OUTFLOW"), cohort_metric(18, .50, 2.1, "MINOR_OUTFLOW"), cohort_metric(4, .25, .9, "MATERIAL_OFFSET")],
            "signal_stage": [control, entry],
        },
        "daily": daily, "warnings": ["当前仅覆盖 8/10 个交易日"],
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        data = {
            "/health": {"status": "ok"},
            "/api/v2/candidates": {"items": CANDIDATES, "count": len(CANDIDATES)},
            "/api/v2/positions": {"items": POSITIONS, "count": len(POSITIONS)},
            "/api/v2/decisions": {"items": DECISIONS, "count": len(DECISIONS)},
            "/api/v2/outcomes/distribution": distribution(),
            "/api/v2/outcomes/shadow-acceptance": shadow_acceptance(),
            "/api/v2/system/health": {"status": "running", "mode": "shadow", "event_queue": {"size": 3, "capacity": 10000, "dropped": 0}, "tasks": [{"name": "v2-event-bus", "status": "RUNNING"}, {"name": "v2-outcomes", "status": "RUNNING"}], "execution_enabled": False},
            "/api/v2/cockpit": {"mode": "shadow", "strategy_version": "v2-preview", "summary": {"confirmed_candidates": 1, "open_positions": 1, "actionable_positions": 1, "evaluated_signals": 4, "reached_5_ratio": .75}, "candidates": CANDIDATES, "positions": POSITIONS, "decisions": DECISIONS},
        }.get(path)
        if data is None:
            self.send_error(404)
            return
        payload = json.dumps({"success": True, "data": data}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 5001), Handler).serve_forever()
