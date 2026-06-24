#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持仓做T腿查询（t_trade_legs 表）

高抛低吸的两腿状态机（卖一档 → 回落买回）落库与对账。
遵守 CLAUDE.md：内部关联用 stock_id INTEGER，外部接口保留 stock_code TEXT。

state: IDLE / SELL_PENDING / SOLD_WAITING_BUYBACK / BUY_PENDING / COMPLETED / EXPIRED
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class TTradeQueries:
    """t_trade_legs 表的增删查改。db 为同步 db_manager。"""

    def __init__(self, db_manager):
        self.db = db_manager

    def _resolve_stock_id(self, stock_code: str) -> int:
        try:
            rows = self.db.execute_query(
                "SELECT id FROM stocks WHERE code=?", (stock_code,)) or []
            if rows:
                return int(rows[0][0])
        except Exception as e:
            logger.debug("resolve stock_id 失败 %s: %s", stock_code, e)
        return 0  # 兜底哨兵：外部仍以 stock_code 为准

    def create_leg(self, stock_code: str, stock_name: str, trade_date: str,
                   mode: str, state: str, original_qty: int,
                   sold_qty: int = 0, sold_price: Optional[float] = None,
                   sold_time: Optional[str] = None, sell_reason: Optional[str] = None,
                   sell_order_id: Optional[str] = None,
                   peak_after_sell: Optional[float] = None,
                   trough_after_sell: Optional[float] = None) -> int:
        """新建一条做T腿，返回自增 id（失败返回 0）。"""
        sid = self._resolve_stock_id(stock_code)
        self.db.execute_update(
            "INSERT INTO t_trade_legs "
            "(stock_id, stock_code, stock_name, trade_date, state, mode, "
            " original_qty, sold_qty, sold_price, sold_time, sell_reason, sell_order_id, "
            " peak_after_sell, trough_after_sell) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, stock_code, stock_name, trade_date, state, mode,
             original_qty, sold_qty, sold_price, sold_time, sell_reason, sell_order_id,
             peak_after_sell, trough_after_sell))
        rows = self.db.execute_query(
            "SELECT id FROM t_trade_legs WHERE stock_code=? AND trade_date=? "
            "ORDER BY id DESC LIMIT 1", (stock_code, trade_date)) or []
        return int(rows[0][0]) if rows else 0

    def update_leg(self, leg_id: int, **fields) -> None:
        """更新指定腿的字段（白名单字段，自动带 updated_at）。"""
        allowed = {
            'state', 'mode', 'sold_qty', 'sold_price', 'sold_time', 'sell_order_id',
            'sell_reason', 'target_buyback_price', 'bought_price', 'bought_time',
            'buy_order_id', 'buy_reason', 'peak_after_sell', 'trough_after_sell',
            'realized_pnl',
        }
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k}=?")
                params.append(v)
        if not sets:
            return
        sets.append("updated_at=CURRENT_TIMESTAMP")
        params.append(leg_id)
        self.db.execute_update(
            f"UPDATE t_trade_legs SET {', '.join(sets)} WHERE id=?", tuple(params))

    def get_open_legs(self, trade_date: str) -> List[dict]:
        """当日未完结的腿（IDLE/SELL_PENDING/SOLD_WAITING_BUYBACK/BUY_PENDING）。"""
        rows = self.db.execute_query(
            "SELECT id, stock_id, stock_code, stock_name, trade_date, state, mode, "
            "original_qty, sold_qty, sold_price, sold_time, sell_order_id, sell_reason, "
            "target_buyback_price, bought_price, bought_time, buy_order_id, buy_reason, "
            "peak_after_sell, trough_after_sell, realized_pnl "
            "FROM t_trade_legs WHERE trade_date=? "
            "AND state IN ('IDLE','SELL_PENDING','SOLD_WAITING_BUYBACK','BUY_PENDING') "
            "ORDER BY id ASC", (trade_date,)) or []
        return [self._row_to_dict(r) for r in rows]

    def get_leg(self, leg_id: int) -> Optional[dict]:
        rows = self.db.execute_query(
            "SELECT id, stock_id, stock_code, stock_name, trade_date, state, mode, "
            "original_qty, sold_qty, sold_price, sold_time, sell_order_id, sell_reason, "
            "target_buyback_price, bought_price, bought_time, buy_order_id, buy_reason, "
            "peak_after_sell, trough_after_sell, realized_pnl "
            "FROM t_trade_legs WHERE id=?", (leg_id,)) or []
        return self._row_to_dict(rows[0]) if rows else None

    def list_legs(self, trade_date: str) -> List[dict]:
        """列出某交易日所有腿（含已完结，供前端展示/对账）。"""
        rows = self.db.execute_query(
            "SELECT id, stock_id, stock_code, stock_name, trade_date, state, mode, "
            "original_qty, sold_qty, sold_price, sold_time, sell_order_id, sell_reason, "
            "target_buyback_price, bought_price, bought_time, buy_order_id, buy_reason, "
            "peak_after_sell, trough_after_sell, realized_pnl "
            "FROM t_trade_legs WHERE trade_date=? ORDER BY id DESC", (trade_date,)) or []
        return [self._row_to_dict(r) for r in rows]

    def count_completed_today(self, stock_code: str, trade_date: str) -> int:
        """某股当日已完成的做T次数（用于每股每日上限护栏）。"""
        rows = self.db.execute_query(
            "SELECT COUNT(*) FROM t_trade_legs "
            "WHERE stock_code=? AND trade_date=? AND state='COMPLETED'",
            (stock_code, trade_date)) or []
        return int(rows[0][0]) if rows else 0

    def sum_realized_loss_today(self, trade_date: str) -> float:
        """当日做T已实现盈亏合计（负数=亏损，用于亏损熔断）。"""
        rows = self.db.execute_query(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM t_trade_legs "
            "WHERE trade_date=? AND realized_pnl IS NOT NULL", (trade_date,)) or []
        try:
            return float(rows[0][0]) if rows else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _row_to_dict(r) -> dict:
        return {
            "id": r[0], "stock_id": r[1], "stock_code": r[2], "stock_name": r[3],
            "trade_date": r[4], "state": r[5], "mode": r[6], "original_qty": r[7],
            "sold_qty": r[8], "sold_price": r[9], "sold_time": r[10],
            "sell_order_id": r[11], "sell_reason": r[12], "target_buyback_price": r[13],
            "bought_price": r[14], "bought_time": r[15], "buy_order_id": r[16],
            "buy_reason": r[17], "peak_after_sell": r[18], "trough_after_sell": r[19],
            "realized_pnl": r[20],
        }
