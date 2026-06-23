#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离场计划查询（exit_plans 表）

盘前为持仓预设"开盘若X则卖/减/持有"，开盘检查(exit_timing/open_check)读取后判定是否命中。
遵守 CLAUDE.md：内部关联用 stock_id INTEGER，外部接口保留 stock_code TEXT。
"""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class ExitPlanQueries:
    """exit_plans 表的增删查（软删）。db 为同步 db_manager。"""

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

    def upsert(self, stock_code: str, planned_action: str, trigger_type: str,
               trigger_value: Optional[float], note: Optional[str],
               valid_for_date: str) -> None:
        """按 (stock_code, valid_for_date) upsert：先软删旧的同键活跃行，再插新行。"""
        sid = self._resolve_stock_id(stock_code)
        self.db.execute_update(
            "UPDATE exit_plans SET is_active=0, updated_at=CURRENT_TIMESTAMP "
            "WHERE stock_code=? AND valid_for_date=? AND is_active=1",
            (stock_code, valid_for_date))
        self.db.execute_update(
            "INSERT INTO exit_plans "
            "(stock_id, stock_code, planned_action, trigger_type, trigger_value, note, valid_for_date) "
            "VALUES (?,?,?,?,?,?,?)",
            (sid, stock_code, planned_action, trigger_type, trigger_value, note, valid_for_date))

    def get_active_plans_map(self, codes: List[str], date: str) -> dict:
        """{code: plan} 当日生效的离场计划（同键取最新一条）。"""
        if not codes:
            return {}
        ph = ",".join("?" for _ in codes)
        rows = self.db.execute_query(
            f"SELECT stock_code, planned_action, trigger_type, trigger_value, note "
            f"FROM exit_plans WHERE is_active=1 AND valid_for_date=? AND stock_code IN ({ph}) "
            f"ORDER BY id DESC", (date, *codes)) or []
        out: dict = {}
        for r in rows:
            if r[0] not in out:
                out[r[0]] = {
                    "stock_code": r[0], "planned_action": r[1],
                    "trigger_type": r[2], "trigger_value": r[3], "note": r[4],
                }
        return out

    def list_plans(self, date: str) -> List[dict]:
        rows = self.db.execute_query(
            "SELECT id, stock_id, stock_code, planned_action, trigger_type, "
            "trigger_value, note, valid_for_date, created_at "
            "FROM exit_plans WHERE is_active=1 AND valid_for_date=? ORDER BY id DESC",
            (date,)) or []
        return [{
            "id": r[0], "stock_id": r[1], "stock_code": r[2],
            "planned_action": r[3], "trigger_type": r[4], "trigger_value": r[5],
            "note": r[6], "valid_for_date": r[7], "created_at": r[8],
        } for r in rows]

    def soft_delete(self, plan_id: int) -> None:
        self.db.execute_update(
            "UPDATE exit_plans SET is_active=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (plan_id,))
