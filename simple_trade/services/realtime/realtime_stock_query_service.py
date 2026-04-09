#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时股票查询服务 - 负责从数据库和股票池获取目标股票
"""

import logging
from typing import Dict, Any, List, Optional, Set
from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ..pool.stock_pool import get_global_stock_pool
from ...core.models import StockWithPlate


class RealtimeStockQueryService:
    """实时股票查询服务"""

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient, config=None):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.config = config

    def get_target_stocks(self, limit: Optional[int] = None, markets: Optional[List[str]] = None,
                         kline_priority: bool = True,
                         position_codes: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        """从全局股票池获取目标股票 - 支持K线优先、按优先级排序、市场筛选并限制数量

        Args:
            limit: 数量限制
            markets: 市场筛选
            kline_priority: 是否K线优先
            position_codes: 持仓股票代码集合，这些股票绕过 is_low_activity 排除
        """
        stocks = []

        try:
            # 获取K线订阅信息
            kline_info = None
            if kline_priority:
                kline_info = self._get_kline_subscription_info()

            # 从数据库获取按优先级排序的股票
            stocks = self._get_priority_stocks_from_db(
                limit, markets, kline_info, position_codes=position_codes
            )

            if not stocks:
                # 如果数据库获取失败，fallback到全局股票池
                global_pool = get_global_stock_pool()

                if not global_pool['initialized']:
                    logging.warning("全局股票池未初始化，无法获取目标股票")
                    return stocks

                # 直接从全局变量获取股票列表
                pool_stocks = global_pool.get('stocks', [])
                kline_stocks = kline_info.get('kline_stocks', set()) if kline_info else set()

                stocks_with_kline = []
                stocks_without_kline = []

                for stock in pool_stocks:
                    # 市场筛选
                    stock_market = stock.get('market', '')
                    if markets and stock_market not in markets:
                        continue

                    # 确保格式兼容性
                    stock_data = {
                        'code': stock.get('code', ''),
                        'name': stock.get('name', ''),
                        'market': stock_market,
                        'id': stock.get('id', 0),
                        'priority': stock.get('priority', 10),
                        'has_kline': stock.get('code', '') in kline_stocks
                    }

                    # K线优先分组
                    if kline_priority and stock_data['has_kline']:
                        stocks_with_kline.append(stock_data)
                    else:
                        stocks_without_kline.append(stock_data)

                # 合并：K线优先
                stocks = stocks_with_kline + stocks_without_kline

                # 如果有限制，应用限制
                if limit and len(stocks) > limit:
                    stocks = stocks[:limit]

            # 记录筛选情况
            if kline_priority and kline_info:
                kline_count = sum(1 for s in stocks if s.get('has_kline', False))
                logging.info(f"获取到{len(stocks)}只目标股票用于订阅，其中{kline_count}只已有K线数据")

            if markets:
                market_stats = {}
                for stock in stocks:
                    market = stock.get('market', 'Unknown')
                    if market not in market_stats:
                        market_stats[market] = 0
                    market_stats[market] += 1

                market_summary = ', '.join([f"{m}: {c}只" for m, c in market_stats.items()])
                logging.info(f"市场分布: {market_summary}")

        except Exception as e:
            logging.error(f"获取目标股票失败: {e}")

        return stocks

    def _get_kline_subscription_info(self) -> Optional[Dict[str, Any]]:
        """获取K线订阅信息"""
        try:
            # 检查配置是否启用详细日志
            log_detail = True
            if self.config:
                log_detail = getattr(self.config, 'log_kline_detail', True)

            kline_info = self.futu_client.get_kline_quota_detail()
            if kline_info and kline_info['success']:
                if log_detail:
                    logging.info(f"获取K线订阅信息成功: {kline_info['message']}")
                    logging.debug(f"K线股票集合大小: {len(kline_info['kline_stocks'])}")
                    # 记录前几只K线股票作为样例
                    if kline_info['detail_list']:
                        sample_stocks = kline_info['detail_list'][:5]
                        sample_codes = [detail['code'] for detail in sample_stocks]
                        logging.debug(f"K线股票样例: {', '.join(sample_codes)}")
                else:
                    logging.info(f"获取到 {len(kline_info['kline_stocks'])} 只K线订阅股票")
                return kline_info
            else:
                logging.warning(f"获取K线订阅信息失败: {kline_info.get('message', '未知错误') if kline_info else '返回空结果'}")
                return None
        except Exception as e:
            logging.error(f"获取K线订阅信息异常: {e}")
            return None

    def _get_priority_stocks_from_db(self, limit: Optional[int] = None, markets: Optional[List[str]] = None,
                                   kline_info: Optional[Dict[str, Any]] = None,
                                   skip_low_activity: bool = True,
                                   position_codes: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
        """从数据库按优先级获取股票，支持自选股优先、市场筛选和K线优先

        Args:
            limit: 数量限制
            markets: 市场筛选
            kline_info: K线订阅信息
            skip_low_activity: 是否跳过低活跃度股票
            position_codes: 持仓股票代码集合，绕过 is_low_activity 排除
        """
        stocks = []

        try:
            # 获取低活跃度重检周期配置
            recheck_days = 7
            if self.config:
                activity_config = getattr(self.config, 'realtime_activity_filter', {})
                recheck_days = activity_config.get('low_activity_recheck_days', 7)

            # 构建SQL查询，使用stock_plates多对多关联，包含自选股优先级字段
            # 同时检查 is_target=1（目标板块）和 is_enabled=1（启用状态）
            # 排除OTC股票和低活跃度股票（但允许超过重检周期的低活跃度股票重新参与筛选）
            # 低活跃度标记在超过 recheck_days 天后过期，股票将重新参与活跃度筛选
            # 【时区修复】使用 'localtime' 确保时间比较一致（low_activity_checked_at 存储的是本地时间）
            # 【永久排除】排除 low_activity_count >= 3 的股票（连续3次标记为低活跃度）
            # 构建持仓股票绕过条件
            position_bypass = ''
            position_params_for_sql = []
            if position_codes:
                position_placeholders = ','.join(['?' for _ in position_codes])
                position_bypass = f' OR s.code IN ({position_placeholders})'
                position_params_for_sql = list(position_codes)

            sql = f'''
                SELECT DISTINCT s.id, s.code, s.name, s.market, p.plate_name, p.priority,
                       s.is_manual, s.stock_priority, s.is_low_activity, s.low_activity_checked_at
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.is_target = 1 AND p.is_enabled = 1
                  AND (s.is_otc IS NULL OR s.is_otc = 0)
                  AND (s.low_activity_count IS NULL OR s.low_activity_count < 3{position_bypass})
                  AND (
                      s.is_low_activity IS NULL
                      OR s.is_low_activity = 0
                      OR (s.is_low_activity = 1
                          AND s.low_activity_checked_at IS NOT NULL
                          AND datetime(s.low_activity_checked_at) < datetime('now', 'localtime', '-{recheck_days} days'))
                      {position_bypass}
                  )
            '''

            # 【调试日志】统计被永久排除的股票数量
            permanently_excluded_sql = '''
                SELECT COUNT(*) FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.is_target = 1 AND p.is_enabled = 1
                  AND (s.is_otc IS NULL OR s.is_otc = 0)
                  AND s.low_activity_count >= 3
            '''
            try:
                perm_excluded_count = self.db_manager.execute_query(permanently_excluded_sql)
                if perm_excluded_count and perm_excluded_count[0][0] > 0:
                    logging.info(f"【永久排除】{perm_excluded_count[0][0]} 只股票因连续3次标记为低活跃度被永久排除")
            except Exception as e:
                logging.debug(f"统计永久排除数量失败: {e}")

            # 【调试日志】统计被临时排除的低活跃度股票数量
            excluded_sql = f'''
                SELECT COUNT(*) FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.is_target = 1 AND p.is_enabled = 1
                  AND (s.is_otc IS NULL OR s.is_otc = 0)
                  AND (s.low_activity_count IS NULL OR s.low_activity_count < 3)
                  AND s.is_low_activity = 1
                  AND s.low_activity_checked_at IS NOT NULL
                  AND datetime(s.low_activity_checked_at) >= datetime('now', 'localtime', '-{recheck_days} days')
            '''
            try:
                excluded_count = self.db_manager.execute_query(excluded_sql)
                if excluded_count and excluded_count[0][0] > 0:
                    logging.info(f"【临时排除】{excluded_count[0][0]} 只低活跃度股票被临时排除（标记未过期，recheck_days={recheck_days}）")
            except Exception as e:
                logging.debug(f"统计临时排除数量失败: {e}")

            params = list(position_params_for_sql) * 2  # position_bypass 出现两次

            # 添加市场筛选条件
            if markets:
                placeholders = ','.join(['?' for _ in markets])
                sql += f' AND s.market IN ({placeholders})'
                params.extend(markets)

            # 不在SQL中排序，在Python中处理复合优先级排序
            rows = self.db_manager.execute_query(sql, tuple(params) if params else None)

            # 获取K线股票集合
            kline_stocks = kline_info.get('kline_stocks', set()) if kline_info else set()

            # 多维度分组处理：自选股 > K线优先 > 板块优先级
            manual_stocks_with_kline = []
            manual_stocks_without_kline = []
            plate_stocks_with_kline = []
            plate_stocks_without_kline = []

            # 用于按股票代码去重（同一股票可能属于多个板块）
            seen_codes = set()

            for row in rows:
                code = row[1]
                # 跳过已处理的股票代码（同一股票可能属于多个板块）
                if code in seen_codes:
                    continue
                seen_codes.add(code)

                # 使用 StockWithPlate 数据模型
                stock_obj = StockWithPlate.from_db_row(row, kline_stocks)
                stock_data = stock_obj.to_dict()

                # 多维度分组：自选股优先，然后K线优先
                if stock_data['is_manual']:
                    if stock_data['has_kline']:
                        manual_stocks_with_kline.append(stock_data)
                    else:
                        manual_stocks_without_kline.append(stock_data)
                else:
                    if stock_data['has_kline']:
                        plate_stocks_with_kline.append(stock_data)
                    else:
                        plate_stocks_without_kline.append(stock_data)

            # 分别按最终优先级排序
            manual_stocks_with_kline.sort(key=lambda x: (x['final_priority'], x['name']), reverse=True)
            manual_stocks_without_kline.sort(key=lambda x: (x['final_priority'], x['name']), reverse=True)
            plate_stocks_with_kline.sort(key=lambda x: (x['final_priority'], x['name']), reverse=True)
            plate_stocks_without_kline.sort(key=lambda x: (x['final_priority'], x['name']), reverse=True)

            # 合并：自选股优先，K线优先
            stocks = (manual_stocks_with_kline +
                     manual_stocks_without_kline +
                     plate_stocks_with_kline +
                     plate_stocks_without_kline)

            # 应用数量限制
            if limit and len(stocks) > limit:
                stocks = stocks[:limit]

            # 记录统计信息
            if stocks:
                manual_count = sum(1 for s in stocks if s['is_manual'])
                plate_count = len(stocks) - manual_count
                kline_count = sum(1 for s in stocks if s.get('has_kline', False))

                priority_info = {}
                market_info = {}

                for stock in stocks:
                    priority = stock['final_priority']
                    market = stock['market']

                    if priority not in priority_info:
                        priority_info[priority] = 0
                    priority_info[priority] += 1

                    if market not in market_info:
                        market_info[market] = 0
                    market_info[market] += 1

                # 记录优先级和市场分布
                priority_summary = ', '.join([f"优先级{p}: {c}只" for p, c in sorted(priority_info.items(), reverse=True)])
                market_summary = ', '.join([f"{m}: {c}只" for m, c in market_info.items()])

                logging.info(f"按自选股和K线优先获取{len(stocks)}只股票")
                logging.info(f"  - 自选股: {manual_count}只, 板块股票: {plate_count}只")
                logging.info(f"  - 有K线数据: {kline_count}只, 无K线数据: {len(stocks)-kline_count}只")
                logging.info(f"  - 优先级分布: {priority_summary}")
                logging.info(f"  - 市场分布: {market_summary}")

        except Exception as e:
            logging.error(f"从数据库按优先级获取股票失败: {e}")

        return stocks
