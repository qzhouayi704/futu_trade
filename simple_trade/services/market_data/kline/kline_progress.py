#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线下载进度管理模块
负责完整K线初始化（半年）、进度追踪、目标股票获取
"""

import logging
import time
from typing import Dict, Any, List, Optional, Callable

from ....database.core.db_manager import DatabaseManager
from ....config.config import Config
from ....api.futu_client import FutuClient
from .kline_data_fetcher import KlineDataFetcher


class KlineProgressManager:
    """K线下载进度管理器"""

    def __init__(self, data_fetcher: KlineDataFetcher,
                 db_manager: DatabaseManager,
                 futu_client: FutuClient,
                 config: Config):
        self.data_fetcher = data_fetcher
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.config = config

        # 初始化进度状态
        self._init_progress = {
            'is_running': False,
            'total_stocks': 0,
            'processed_stocks': 0,
            'current_stock': '',
            'errors': []
        }

    def get_init_progress(self) -> Dict[str, Any]:
        """获取初始化进度"""
        return {
            'is_running': self._init_progress['is_running'],
            'total_stocks': self._init_progress['total_stocks'],
            'processed_stocks': self._init_progress['processed_stocks'],
            'current_stock': self._init_progress['current_stock'],
            'progress_percent': round(
                self._init_progress['processed_stocks'] / max(self._init_progress['total_stocks'], 1) * 100,
                1
            ),
            'errors_count': len(self._init_progress['errors'])
        }

    def initialize_kline_for_all_stocks(self,
                                        days: int = None,
                                        max_stocks: int = None,
                                        progress_callback: Optional[Callable] = None) -> Dict[str, Any]:
        """
        为所有目标股票初始化K线数据（默认半年）

        Args:
            days: 获取天数，默认使用配置kline_init_days（180天）
            max_stocks: 最大股票数量，默认使用配置kline_init_max_stocks
            progress_callback: 进度回调函数 (current, total, stock_code, message)

        Returns:
            初始化结果字典
        """
        # 使用配置或默认值
        days = days or getattr(self.config, 'kline_init_days', 180)
        max_stocks = max_stocks or getattr(self.config, 'kline_init_max_stocks', 500)
        batch_size = getattr(self.config, 'kline_batch_size', 10)
        request_delay = getattr(self.config, 'kline_request_delay', 0.3)

        result = {
            'success': False,
            'message': '',
            'total_stocks': 0,
            'processed_stocks': 0,
            'kline_records': 0,
            'skipped_stocks': 0,
            'failed_stocks': 0,
            'errors': [],
            'duration_seconds': 0
        }

        start_time = time.time()

        try:
            # 检查是否已在运行
            if self._init_progress['is_running']:
                result['message'] = 'K线初始化任务已在运行中'
                return result

            self._init_progress['is_running'] = True
            self._init_progress['errors'] = []

            logging.info(f"开始初始化K线数据: 目标{days}天，最大{max_stocks}只股票")

            # 1. 检查API可用性
            if not self.futu_client.is_available():
                result['message'] = '富途API不可用'
                result['errors'].append('富途API客户端未连接')
                return result

            # 2. 获取K线额度
            quota_info = self.data_fetcher.get_quota_info(force_refresh=True)
            if quota_info['status'] != 'connected' or quota_info['remaining'] <= 0:
                result['message'] = f"K线额度不足: {quota_info['remaining']} 剩余"
                result['errors'].append(result['message'])
                return result

            logging.info(f"K线额度: 已用{quota_info['used']}, 剩余{quota_info['remaining']}")

            # 3. 获取目标股票列表（去重）
            stocks = self._get_target_stocks_for_kline(max_stocks)
            if not stocks:
                result['message'] = '没有找到目标股票'
                return result

            result['total_stocks'] = len(stocks)
            self._init_progress['total_stocks'] = len(stocks)
            logging.info(f"获取到{len(stocks)}只目标股票")

            # 4. 分批获取K线数据
            batch_result = self._process_stocks_in_batches(
                stocks, days, batch_size, request_delay, progress_callback
            )
            result.update(batch_result)

            # 计算耗时
            duration = time.time() - start_time
            result['duration_seconds'] = round(duration, 2)
            result['success'] = True
            result['message'] = (
                f"K线初始化完成: 处理{result['processed_stocks']}只股票，"
                f"获取{result['kline_records']}条记录，"
                f"跳过{result['skipped_stocks']}只，失败{result['failed_stocks']}只"
            )
            logging.info(f"{result['message']}，耗时{duration:.1f}秒")

        except Exception as e:
            logging.error(f"K线初始化异常: {e}")
            result['message'] = f'K线初始化异常: {str(e)}'
            result['errors'].append(str(e))
        finally:
            self._init_progress['is_running'] = False
            self._init_progress['current_stock'] = ''

        return result

    def _process_stocks_in_batches(self, stocks: List[Dict[str, Any]],
                                   days: int, batch_size: int,
                                   request_delay: float,
                                   progress_callback: Optional[Callable]) -> Dict[str, Any]:
        """分批处理股票的K线数据获取"""
        processed, skipped, failed, total_records = 0, 0, 0, 0
        errors: List[str] = []
        fetcher = self.data_fetcher.fetcher
        parser = self.data_fetcher.parser
        storage = self.data_fetcher.storage

        for batch_start in range(0, len(stocks), batch_size):
            batch_end = min(batch_start + batch_size, len(stocks))

            for stock in stocks[batch_start:batch_end]:
                stock_code = stock['code']
                try:
                    self._init_progress['processed_stocks'] = processed
                    self._init_progress['current_stock'] = stock_code
                    if progress_callback:
                        progress_callback(
                            processed, len(stocks), stock_code,
                            f"正在获取 {stock.get('name', stock_code)} 的K线数据"
                        )

                    if parser.has_enough_kline_data(stock_code, days):
                        skipped += 1
                        processed += 1
                        continue

                    kline_data = fetcher.fetch_kline_data(stock_code, days)
                    if kline_data:
                        filtered = parser.filter_today_incomplete_data(stock_code, kline_data)
                        saved = storage.save_kline_batch(stock_code, filtered)
                        total_records += saved
                        logging.info(f"{stock_code} 获取{len(kline_data)}条，保存{saved}条K线数据")
                    else:
                        logging.warning(f"{stock_code} 未获取到K线数据")
                        failed += 1
                    processed += 1
                    time.sleep(request_delay)
                except Exception as e:
                    error_msg = f"获取{stock_code}K线失败: {e}"
                    logging.error(error_msg)
                    errors.append(error_msg)
                    self._init_progress['errors'].append(error_msg)
                    failed += 1
                    processed += 1

            if batch_end < len(stocks):
                logging.info(f"已处理 {batch_end}/{len(stocks)} 只股票")
                time.sleep(self.config.kline_rate_limit.get("batch_delay", 0.5))

        return {
            'processed_stocks': processed, 'kline_records': total_records,
            'skipped_stocks': skipped, 'failed_stocks': failed, 'errors': errors
        }

    def _get_target_stocks_for_kline(self, limit: int) -> List[Dict[str, Any]]:
        """获取目标股票列表（按板块优先级排序，去重）"""
        stocks: List[Dict[str, Any]] = []
        seen_codes: set = set()

        try:
            plate_priority = getattr(self.config, 'plate_priority', {})
            priority_levels = [
                ('高', plate_priority.get('高优先级', [])),
                ('中', plate_priority.get('中优先级', [])),
                ('低', plate_priority.get('低优先级', [])),
            ]

            # 按优先级获取股票
            for priority_level, plate_names in priority_levels:
                if len(stocks) >= limit:
                    break
                self._collect_stocks_by_plates(
                    stocks, seen_codes, plate_names, priority_level, limit
                )

            # 如果优先级板块的股票不足，补充其他目标板块的股票
            if len(stocks) < limit:
                self._fill_remaining_stocks(stocks, seen_codes, limit)

            logging.info(f"按优先级获取到 {len(stocks)} 只目标股票用于K线初始化")
        except Exception as e:
            logging.error(f"获取目标股票失败: {e}", exc_info=True)

        return stocks

    def _collect_stocks_by_plates(self, stocks: List, seen_codes: set,
                                  plate_names: List[str], priority: str, limit: int):
        """从指定板块收集股票"""
        for plate_name in plate_names:
            if len(stocks) >= limit:
                break
            rows = self.db_manager.execute_query('''
                SELECT DISTINCT s.id, s.code, s.name, s.market, p.plate_name
                FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                INNER JOIN plates p ON sp.plate_id = p.id
                WHERE p.is_target = 1 AND p.plate_name LIKE ?
                ORDER BY s.code
            ''', (f'%{plate_name}%',))

            added = 0
            for row in rows:
                if len(stocks) >= limit:
                    break
                if row[1] not in seen_codes:
                    seen_codes.add(row[1])
                    stocks.append({
                        'id': row[0], 'code': row[1], 'name': row[2],
                        'market': row[3], 'priority': priority, 'plate': row[4]
                    })
                    added += 1
            if added:
                logging.info(f"[{priority}优先级] 板块 '{plate_name}' 获取到 {added} 只股票")

    def _fill_remaining_stocks(self, stocks: List, seen_codes: set, limit: int):
        """补充其他目标板块的股票"""
        rows = self.db_manager.execute_query('''
            SELECT DISTINCT s.id, s.code, s.name, s.market
            FROM stocks s
            INNER JOIN stock_plates sp ON s.id = sp.stock_id
            INNER JOIN plates p ON sp.plate_id = p.id
            WHERE p.is_target = 1
            ORDER BY s.code LIMIT ?
        ''', (limit * 2,))

        added = 0
        for row in rows:
            if len(stocks) >= limit:
                break
            if row[1] not in seen_codes:
                seen_codes.add(row[1])
                stocks.append({
                    'id': row[0], 'code': row[1], 'name': row[2],
                    'market': row[3], 'priority': '普通', 'plate': ''
                })
                added += 1
        if added:
            logging.info(f"补充其他板块股票: {added} 只")
