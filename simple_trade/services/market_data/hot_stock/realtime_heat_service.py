#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时热度计算服务

职责：
- 计算股票的实时热度
- 获取实时报价数据
- 应用增强模式过滤
"""

import logging
from typing import Dict, Any, List, Optional
from ....database.core.db_manager import DatabaseManager
from ....api.futu_client import FutuClient
from ...analysis import StockHeatCalculator


class RealtimeHeatService:
    """实时热度计算服务"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        futu_client: FutuClient,
        heat_calculator: StockHeatCalculator,
        quote_service=None
    ):
        """
        初始化实时热度服务

        Args:
            db_manager: 数据库管理器
            futu_client: Futu API客户端
            heat_calculator: 热度计算器
            quote_service: 报价服务（可选）
        """
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.heat_calculator = heat_calculator
        self.quote_service = quote_service
        self.logger = logging.getLogger(__name__)

    def get_hot_stocks_realtime(
        self,
        top_n: int = 100,
        enhanced_mode: bool = False
    ) -> List[Dict[str, Any]]:
        """
        获取实时热门股票（基于当前报价）

        Args:
            top_n: 返回前N只股票
            enhanced_mode: 是否启用增强模式

        Returns:
            热门股票列表
        """
        stocks = []

        try:
            query = '''
                SELECT s.id, s.code, s.name, s.market,
                       s.heat_score, s.avg_turnover_rate, s.avg_volume, s.active_days,
                       s.heat_update_time
                FROM stocks s
                WHERE s.heat_score > 0
                ORDER BY s.heat_score DESC
                LIMIT ?
            '''
            results = self.db_manager.execute_query(query, (top_n,))

            for row in results:
                stocks.append({
                    'id': row[0],
                    'code': row[1],
                    'name': row[2],
                    'market': row[3],
                    'heat_score': row[4],
                    'avg_turnover_rate': row[5],
                    'avg_volume': row[6],
                    'active_days': row[7],
                    'heat_update_time': row[8]
                })

        except Exception as e:
            self.logger.error(f"获取热门股票失败: {e}")

        return stocks

    def calculate_realtime_heat_scores(
        self,
        stock_codes: List[str],
        use_cache: bool = True,
        cache_duration: int = 3600
    ) -> Dict[str, Dict[str, Any]]:
        """计算实时热度分（代理方法，调用 heat_calculator）"""
        return self.heat_calculator.calculate_realtime_heat_scores(
            stock_codes, use_cache, cache_duration
        )

    def get_cached_heat_scores(self) -> Dict[str, Dict[str, Any]]:
        """只读取已缓存的热度分数据，不触发任何 API 调用"""
        import time as _time
        cache_duration = 3600
        cache_key = f"realtime_heat_{int(_time.time() / cache_duration)}"
        return self.heat_calculator._get_cache(cache_key) or {}

    def update_realtime_heat_scores(self, force: bool = False) -> Dict[str, Any]:
        """更新实时热度数据（批量更新所有已订阅股票）"""
        from datetime import datetime
        result = {'success': False, 'message': '', 'updated_count': 0, 'errors': []}

        try:
            # 检查缓存（1小时）
            if not force and self._check_heat_cache():
                elapsed = self._get_last_update_elapsed()
                result.update({
                    'success': True,
                    'message': f'热度数据已是最新（{int(elapsed)}秒前更新）',
                    'cached': True
                })
                return result

            # 获取股票池
            from ...core.state import get_state_manager
            stock_codes = [s['code'] for s in get_state_manager().get_stock_pool().get('stocks', [])]

            if not stock_codes:
                result['message'] = '股票池为空，无法更新热度'
                return result

            self.logger.info(f"开始更新 {len(stock_codes)} 只股票的实时热度...")

            # 计算热度分
            heat_scores = self.heat_calculator.calculate_realtime_heat_scores(stock_codes)
            if not heat_scores:
                result['message'] = '未能获取任何股票的热度数据'
                return result

            # 批量更新数据库
            current_time = datetime.now().isoformat()
            for code, data in heat_scores.items():
                try:
                    self.db_manager.execute_update(
                        'UPDATE stocks SET heat_score=?, heat_update_time=?, updated_at=? WHERE code=?',
                        (data['heat_score'], current_time, current_time, code)
                    )
                    result['updated_count'] += 1
                except Exception as e:
                    result['errors'].append(f"更新 {code} 失败: {e}")

            result['success'] = True
            result['message'] = f"成功更新 {result['updated_count']}/{len(stock_codes)} 只股票"
            self.logger.info(result['message'])

        except Exception as e:
            self.logger.error(f"更新实时热度失败: {e}", exc_info=True)
            result['message'] = f'更新失败: {str(e)}'

        return result

    def _check_heat_cache(self) -> bool:
        """检查热度缓存是否有效（1小时内）"""
        from datetime import datetime
        try:
            result = self.db_manager.execute_query(
                'SELECT MAX(heat_update_time) FROM stocks WHERE heat_update_time IS NOT NULL'
            )
            if result and result[0][0]:
                last_update = datetime.fromisoformat(result[0][0])
                return (datetime.now() - last_update).total_seconds() < 3600
        except Exception as e:
            self.logger.warning(f"检查缓存失败: {e}")
        return False

    def _get_last_update_elapsed(self) -> float:
        """获取距离上次更新的秒数"""
        from datetime import datetime
        try:
            result = self.db_manager.execute_query(
                'SELECT MAX(heat_update_time) FROM stocks WHERE heat_update_time IS NOT NULL'
            )
            if result and result[0][0]:
                last_update = datetime.fromisoformat(result[0][0])
                return (datetime.now() - last_update).total_seconds()
        except:
            pass
        return 0
