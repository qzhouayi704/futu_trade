#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""决策助理查询服务"""

import json
import logging
from typing import List, Dict, Any

from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries

logger = logging.getLogger(__name__)


class AdvisorQueries(BaseQueries):
    """决策助理评估记录查询"""

    def __init__(self, conn_manager: ConnectionManager):
        super().__init__(conn_manager)

    def save_evaluation(self, advices: List[Dict[str, Any]]) -> int:
        """批量保存评估结果

        Args:
            advices: DecisionAdvice.to_dict() 列表

        Returns:
            插入的记录数
        """
        if not advices:
            return 0

        params_list = []
        for a in advices:
            health = a.get('position_health') or {}
            ai_json = json.dumps(a['ai_analysis'], ensure_ascii=False) \
                if a.get('ai_analysis') else None
            params_list.append((
                a['advice_type'],
                a['urgency'],
                a['title'],
                a.get('description', ''),
                a.get('sell_stock_code'),
                a.get('sell_stock_name'),
                a.get('sell_price'),
                a.get('buy_stock_code'),
                a.get('buy_stock_name'),
                a.get('buy_price'),
                a.get('quantity'),
                a.get('sell_ratio'),
                health.get('score'),
                health.get('health_level'),
                ai_json,
                a.get('is_dismissed', False),
                a.get('created_at'),
            ))

        query = '''
            INSERT INTO advisor_evaluations
            (advice_type, urgency, title, description,
             sell_stock_code, sell_stock_name, sell_price,
             buy_stock_code, buy_stock_name, buy_price,
             quantity, sell_ratio, health_score, health_level,
             ai_analysis, is_dismissed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        return self.execute_batch(query, params_list)

    def get_latest_evaluation(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近一次评估的所有建议

        通过 created_at 分组，取最新一批（同一秒内的记录视为同一次评估）

        Returns:
            字典列表，每条对应一个建议
        """
        query = '''
            SELECT id, advice_type, urgency, title, description,
                   sell_stock_code, sell_stock_name, sell_price,
                   buy_stock_code, buy_stock_name, buy_price,
                   quantity, sell_ratio, health_score, health_level,
                   ai_analysis, is_dismissed, created_at
            FROM advisor_evaluations
            WHERE is_dismissed = 0
              AND created_at >= (
                  SELECT MAX(created_at) FROM advisor_evaluations
              )
            ORDER BY urgency DESC
            LIMIT ?
        '''
        rows = self.execute_query(query, (limit,))
        return [self._row_to_dict(r) for r in rows]

    def get_recent_evaluations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的评估记录"""
        query = '''
            SELECT id, advice_type, urgency, title, description,
                   sell_stock_code, sell_stock_name, sell_price,
                   buy_stock_code, buy_stock_name, buy_price,
                   quantity, sell_ratio, health_score, health_level,
                   ai_analysis, is_dismissed, created_at
            FROM advisor_evaluations
            ORDER BY created_at DESC
            LIMIT ?
        '''
        rows = self.execute_query(query, (limit,))
        return [self._row_to_dict(r) for r in rows]

    def dismiss_advice(self, advice_id: int) -> bool:
        """标记建议为已忽略"""
        affected = self.execute_update(
            'UPDATE advisor_evaluations SET is_dismissed = 1 WHERE id = ?',
            (advice_id,)
        )
        return affected > 0

    def cleanup_old_records(self, keep_days: int = 7) -> int:
        """清理过期记录"""
        return self.execute_update(
            '''DELETE FROM advisor_evaluations
               WHERE created_at < datetime('now', ?)''',
            (f'-{keep_days} days',)
        )

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        ai_raw = row[15]
        ai_analysis = None
        if ai_raw:
            try:
                ai_analysis = json.loads(ai_raw)
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            'id': row[0],
            'advice_type': row[1],
            'urgency': row[2],
            'title': row[3],
            'description': row[4],
            'sell_stock_code': row[5],
            'sell_stock_name': row[6],
            'sell_price': row[7],
            'buy_stock_code': row[8],
            'buy_stock_name': row[9],
            'buy_price': row[10],
            'quantity': row[11],
            'sell_ratio': row[12],
            'health_score': row[13],
            'health_level': row[14],
            'ai_analysis': ai_analysis,
            'is_dismissed': bool(row[16]),
            'created_at': row[17],
        }
