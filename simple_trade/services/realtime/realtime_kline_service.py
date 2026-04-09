#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时K线数据服务 - 负责K线数据的获取、解析和存储
"""

import logging
import time
from typing import Dict, Any, List, Optional
from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient


class RealtimeKlineService:
    """实时K线数据服务"""

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self._kline_fetcher = None  # 延迟初始化，避免循环依赖

    def fetch_and_save_kline_data(self, stock_codes: Optional[List[str]] = None,
                                 ktype: str = 'K_DAY', limit: int = 100) -> Dict[str, Any]:
        """获取并保存K线数据"""
        result = {
            'success': False,
            'message': '',
            'processed_stocks': 0,
            'saved_klines': 0,
            'errors': []
        }

        try:
            if not self.futu_client.is_available():
                result['message'] = '富途API不可用'
                result['errors'].append('富途API不可用')
                return result

            if not stock_codes:
                result['message'] = '没有可获取K线的股票'
                return result

            total_saved = 0

            for stock_code in stock_codes:
                try:
                    # 获取K线数据
                    kline_result = self._fetch_stock_kline(stock_code, ktype, limit)

                    if kline_result['success']:
                        # 保存K线数据到数据库
                        saved_count = self._save_kline_to_database(stock_code, kline_result['klines'])
                        total_saved += saved_count

                        logging.debug(f"股票{stock_code}保存了{saved_count}条K线数据")
                    else:
                        result['errors'].append(f"股票{stock_code}: {kline_result['message']}")

                    result['processed_stocks'] += 1

                    # 避免请求过于频繁
                    time.sleep(0.1)

                except Exception as e:
                    logging.warning(f"处理股票{stock_code}的K线数据失败: {e}")
                    result['errors'].append(f"股票{stock_code}: {str(e)}")
                    continue

            result.update({
                'success': True,
                'message': f'成功处理{result["processed_stocks"]}只股票，保存{total_saved}条K线数据',
                'saved_klines': total_saved
            })

        except Exception as e:
            logging.error(f"获取并保存K线数据失败: {e}")
            result.update({
                'success': False,
                'message': f'获取并保存K线数据异常: {str(e)}'
            })
            result['errors'].append(str(e))

        return result

    def _fetch_stock_kline(self, stock_code: str, ktype: str = 'K_DAY', limit: int = 100) -> Dict[str, Any]:
        """获取单只股票的K线数据（通过 KlineFetcher，带频率控制和重试）"""
        result = {'success': False, 'message': '', 'klines': []}

        try:
            # 延迟初始化 fetcher
            if self._kline_fetcher is None:
                from ..analysis.kline.kline_fetcher import KlineFetcher
                from ...config.config import Config
                config = Config()
                self._kline_fetcher = KlineFetcher(self.futu_client, config)

            records = self._kline_fetcher.fetch_kline(stock_code, days=limit)

            if records:
                klines = [self._kline_fetcher._record_to_dict(r) for r in records]
                result.update({
                    'success': True,
                    'message': f'获取到{len(klines)}条K线数据',
                    'klines': klines
                })
            else:
                result['message'] = f'获取K线数据失败: {stock_code}'

        except Exception as e:
            result['message'] = f'获取K线数据异常: {str(e)}'

        return result

    def _save_kline_to_database(self, stock_code: str, klines: List[Dict[str, Any]]) -> int:
        """保存K线数据到数据库（复用 KlineStorage）"""
        try:
            from .analysis.kline_storage import KlineStorage
            storage = KlineStorage(self.db_manager)
            return storage.save_kline_batch(stock_code, klines)
        except Exception as e:
            logging.error(f"保存K线数据到数据库失败: {e}")
            return 0

    def get_stock_kline_from_db(self, stock_code: str, limit: int = 100) -> Dict[str, Any]:
        """从数据库获取股票K线数据"""
        result = {
            'success': False,
            'message': '',
            'klines': [],
            'stock_code': stock_code
        }

        try:
            rows = self.db_manager.execute_query('''
                SELECT time_key, open_price, close_price, high_price, low_price,
                       volume, turnover, pe_ratio, turnover_rate, created_at
                FROM kline_data
                WHERE stock_code = ?
                ORDER BY time_key DESC
                LIMIT ?
            ''', (stock_code, limit))

            klines = []
            for row in rows:
                klines.append({
                    'time_key': row[0],
                    'open_price': row[1],
                    'close_price': row[2],
                    'high_price': row[3],
                    'low_price': row[4],
                    'volume': row[5],
                    'turnover': row[6],
                    'pe_ratio': row[7],
                    'turnover_rate': row[8],
                    'created_at': row[9]
                })

            result.update({
                'success': True,
                'message': f'获取到{len(klines)}条K线数据',
                'klines': klines
            })

        except Exception as e:
            logging.error(f"从数据库获取K线数据失败: {e}")
            result.update({
                'success': False,
                'message': f'获取K线数据异常: {str(e)}'
            })

        return result
