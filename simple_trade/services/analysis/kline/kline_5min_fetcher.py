#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5分钟K线数据获取服务
用于日内交易回测，支持容错机制
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from futu import KLType, AuType, KL_FIELD, RET_OK, RET_ERROR

from ....api.futu_client import FutuClient
from ....api.market_types import ReturnCode
from ....config.config import Config
from ....database.core.db_manager import DatabaseManager
from ....utils.rate_limiter import get_global_rate_limiter
from .kline_fetcher import KlineFetcher


class Kline5MinFetcher:
    """5分钟K线数据获取服务（含容错机制）"""

    def __init__(
        self,
        futu_client: FutuClient,
        db_manager: DatabaseManager,
        config: Config
    ):
        self.futu_client = futu_client
        self.db_manager = db_manager
        self.config = config
        self.logger = logging.getLogger(__name__)

        # 跳过的股票记录
        self.skipped_stocks: List[Dict[str, str]] = []

        # 请求间隔（秒），从配置读取
        self.request_delay = config.kline_rate_limit.get("request_delay", 1.0)

        # 初始化全局频率控制器
        rate_limit_config = config.kline_rate_limit
        if rate_limit_config.get("enabled", True):
            self.rate_limiter = get_global_rate_limiter(
                max_requests=rate_limit_config.get("max_requests", 60),
                time_window=rate_limit_config.get("time_window", 30)
            )
        else:
            self.rate_limiter = None

    def get_stocks_with_daily_kline(self) -> List[str]:
        """获取数据库中已有日线数据的股票列表"""
        try:
            query = '''
                SELECT DISTINCT stock_code FROM kline_data
                WHERE time_key >= date('now', '-30 days')
            '''
            result = self.db_manager.execute_query(query)
            return [row[0] for row in result] if result else []
        except Exception as e:
            self.logger.error(f"获取已有日线数据的股票列表失败: {e}")
            return []

    def get_cached_5min_kline(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """从数据库缓存获取5分钟K线数据"""
        try:
            query = '''
                SELECT time_key, open_price, close_price, high_price,
                       low_price, volume, turnover, turnover_rate
                FROM kline_5min_data
                WHERE stock_code = ?
                  AND time_key >= ?
                  AND time_key <= ?
                ORDER BY time_key ASC
            '''
            result = self.db_manager.execute_query(
                query,
                (stock_code, f"{start_date} 00:00:00", f"{end_date} 23:59:59")
            )

            if not result:
                return []

            return [
                {
                    'time_key': row[0],
                    'open_price': float(row[1]) if row[1] else 0.0,
                    'close_price': float(row[2]) if row[2] else 0.0,
                    'high_price': float(row[3]) if row[3] else 0.0,
                    'low_price': float(row[4]) if row[4] else 0.0,
                    'volume': int(row[5]) if row[5] else 0,
                    'turnover': float(row[6]) if row[6] else 0.0,
                    'turnover_rate': float(row[7]) if row[7] else None
                }
                for row in result
            ]
        except Exception as e:
            self.logger.error(f"从缓存获取5分钟K线失败 {stock_code}: {e}")
            return []

    def has_cached_data(self, stock_code: str, date: str) -> bool:
        """检查指定日期是否有缓存数据"""
        try:
            query = '''
                SELECT COUNT(*) FROM kline_5min_data
                WHERE stock_code = ?
                  AND time_key >= ?
                  AND time_key < ?
            '''
            result = self.db_manager.execute_query(
                query,
                (stock_code, f"{date} 00:00:00", f"{date} 23:59:59")
            )
            return result and result[0][0] > 0
        except Exception:
            return False

    def _parse_kline_rows(self, data) -> List[Dict[str, Any]]:
        """将API返回的DataFrame解析为K线数据列表"""
        kline_data = []
        if data is None or data.empty:
            return kline_data
        for _, row in data.iterrows():
            kline_data.append({
                'time_key': row['time_key'],
                'open_price': float(row['open']),
                'close_price': float(row['close']),
                'high_price': float(row['high']),
                'low_price': float(row['low']),
                'volume': int(row['volume']),
                'turnover': float(row.get('turnover', 0)),
                'turnover_rate': float(row.get('turnover_rate', 0))
                    if row.get('turnover_rate') else None
            })
        return kline_data

    def fetch_from_api(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """从富途API获取5分钟K线数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            timeout: 单次API请求超时时间（秒）
        """
        kline_data = []

        if not self.futu_client.is_available():
            self.logger.warning(f"富途API不可用，跳过 {stock_code}")
            return kline_data

        try:
            self.logger.info(f"  请求API: {stock_code} ({start_date} ~ {end_date})")
            # 频率控制已由 futu_client.request_history_kline() 统一处理

            request_start = time.time()
            ret, data, page_req_key = self.futu_client.request_history_kline(
                code=stock_code,
                start=start_date,
                end=end_date,
                ktype=KLType.K_5M,
                max_count=1000,
                timeout=timeout
            )
            request_time = time.time() - request_start
            self.logger.info(f"  API响应: {stock_code} 耗时 {request_time:.1f}秒, ret={ret}")

            if ReturnCode.is_ok(ret) and data is not None and not data.empty:
                kline_data.extend(self._parse_kline_rows(data))

                # 处理分页
                page_num = 1
                while page_req_key:
                    page_num += 1
                    self.logger.info(f"  {stock_code} 分页请求第{page_num}页...")

                    # 频率控制已由 futu_client.request_history_kline() 统一处理
                    time.sleep(self.request_delay)

                    ret, data, page_req_key = self.futu_client.request_history_kline(
                        code=stock_code,
                        start=start_date,
                        end=end_date,
                        ktype=KLType.K_5M,
                        max_count=1000,
                        timeout=timeout
                    )
                    if ReturnCode.is_ok(ret) and data is not None and not data.empty:
                        kline_data.extend(self._parse_kline_rows(data))
            else:
                error_msg = self._parse_error(ret, data)
                self.logger.warning(f"获取5分钟K线失败 {stock_code}: {error_msg}")

        except Exception as e:
            self.logger.error(f"获取5分钟K线异常 {stock_code}: {e}")

        return kline_data

    def _parse_error(self, ret, data) -> str:
        """解析API错误（复用 KlineFetcher 的解析逻辑）"""
        msg, _ = KlineFetcher._parse_error(ret, data)
        return msg

    def save_to_cache(
        self,
        stock_code: str,
        kline_data: List[Dict[str, Any]]
    ) -> int:
        """保存5分钟K线数据到数据库（批量写入）"""
        if not kline_data:
            return 0

        try:
            query = '''
                INSERT OR REPLACE INTO kline_5min_data
                (stock_code, time_key, open_price, close_price,
                 high_price, low_price, volume, turnover, turnover_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            params_list = [
                (
                    stock_code,
                    kline['time_key'],
                    kline['open_price'],
                    kline['close_price'],
                    kline['high_price'],
                    kline['low_price'],
                    kline['volume'],
                    kline['turnover'],
                    kline['turnover_rate']
                )
                for kline in kline_data
            ]
            result = self.db_manager.execute_many(query, params_list)
            saved_count = len(params_list) if result >= 0 else 0
            self.logger.debug(f"保存 {stock_code} 5分钟K线 {saved_count} 条")
            return saved_count
        except Exception as e:
            self.logger.error(f"保存5分钟K线失败 {stock_code}: {e}")
            return 0

    def fetch_batch(
        self,
        stock_codes: List[str],
        start_date: str,
        end_date: str,
        use_cache: bool = True
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        批量获取5分钟K线数据（含容错机制）

        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            use_cache: 是否优先使用缓存

        Returns:
            {stock_code: [kline_data]} 字典
        """
        results: Dict[str, List[Dict[str, Any]]] = {}
        self.skipped_stocks = []

        total = len(stock_codes)
        cache_hit = 0
        api_success = 0
        api_fail = 0
        start_time = time.time()

        self.logger.info(f"开始批量获取5分钟K线，共 {total} 只股票")
        self.logger.info(f"日期范围: {start_date} ~ {end_date}, 缓存优先: {use_cache}")

        # 连续API失败计数，用于检测连接问题
        consecutive_failures = 0
        max_consecutive_failures = 10

        for i, code in enumerate(stock_codes):
            progress = f"[{i+1}/{total}]"
            elapsed = time.time() - start_time
            # 每处理10只或每60秒输出一次汇总进度
            if (i + 1) % 10 == 0 or elapsed > 60:
                speed = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (total - i - 1) / speed if speed > 0 else 0
                self.logger.info(
                    f"进度: {i+1}/{total} ({(i+1)*100//total}%) | "
                    f"缓存命中: {cache_hit}, API成功: {api_success}, 失败: {api_fail} | "
                    f"速度: {speed:.1f}只/秒, 预计剩余: {eta:.0f}秒"
                )

            # 1. 优先检查缓存
            if use_cache:
                cached = self.get_cached_5min_kline(code, start_date, end_date)
                if cached:
                    results[code] = cached
                    cache_hit += 1
                    self.logger.debug(f"{progress} {code} 使用缓存 {len(cached)} 条")
                    consecutive_failures = 0
                    continue

            # 2. 检查连续失败次数，防止API挂死
            if consecutive_failures >= max_consecutive_failures:
                self.logger.error(
                    f"连续 {consecutive_failures} 次API请求失败，"
                    f"可能是连接问题或额度耗尽，停止后续请求"
                )
                # 将剩余股票全部标记为跳过
                for remaining_code in stock_codes[i:]:
                    self.skipped_stocks.append({
                        'code': remaining_code,
                        'reason': '连续失败，提前终止'
                    })
                break

            # 3. 从API获取
            try:
                self.logger.info(f"{progress} 正在获取 {code} ...")

                # 额外请求间隔（fetcher 内部已有频率控制）
                time.sleep(self.request_delay)

                data = self.fetch_from_api(code, start_date, end_date)

                if data:
                    results[code] = data
                    self.save_to_cache(code, data)
                    api_success += 1
                    consecutive_failures = 0
                    self.logger.info(f"{progress} {code} 获取成功 {len(data)} 条")
                else:
                    api_fail += 1
                    consecutive_failures += 1
                    self.skipped_stocks.append({
                        'code': code,
                        'reason': '无数据'
                    })
                    self.logger.warning(f"{progress} {code} 无数据，跳过")

            except Exception as e:
                api_fail += 1
                consecutive_failures += 1
                error_msg = str(e)
                # 检查是否是额度不足
                if 'quota' in error_msg.lower() or '额度' in error_msg:
                    self.skipped_stocks.append({
                        'code': code,
                        'reason': '额度不足'
                    })
                    self.logger.warning(f"{progress} {code} 额度不足，跳过")
                else:
                    self.skipped_stocks.append({
                        'code': code,
                        'reason': error_msg
                    })
                    self.logger.error(f"{progress} {code} 获取失败: {error_msg}")
                continue

        # 输出最终统计
        total_time = time.time() - start_time
        skip_count = len(self.skipped_stocks)
        self.logger.info("=" * 60)
        self.logger.info(
            f"批量获取完成 | 耗时: {total_time:.1f}秒 | "
            f"成功: {len(results)} 只 (缓存: {cache_hit}, API: {api_success}) | "
            f"跳过: {skip_count} 只"
        )
        self.logger.info("=" * 60)

        return results

    def get_skipped_stocks(self) -> List[Dict[str, str]]:
        """获取跳过的股票列表"""
        return self.skipped_stocks.copy()

    def get_date_kline(
        self,
        stock_code: str,
        date: str
    ) -> List[Dict[str, Any]]:
        """获取指定日期的5分钟K线数据"""
        # 先检查缓存
        if self.has_cached_data(stock_code, date):
            return self.get_cached_5min_kline(stock_code, date, date)

        # 从API获取
        data = self.fetch_from_api(stock_code, date, date)
        if data:
            self.save_to_cache(stock_code, data)
        return data

    def get_intraday_stats(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> Dict[str, Any]:
        """
        获取日内统计数据（用于分析日内低点规律）

        Returns:
            {
                'avg_low_deviation': float,  # 平均日内低点偏离度
                'p50_low_deviation': float,  # 50分位日内低点偏离度
                'p70_low_deviation': float,  # 70分位日内低点偏离度
                'avg_amplitude': float,      # 平均日内振幅
                'trading_days': int          # 交易天数
            }
        """
        kline_data = self.get_cached_5min_kline(stock_code, start_date, end_date)
        if not kline_data:
            return {}

        # 按日期分组
        daily_data: Dict[str, List[Dict]] = {}
        for kline in kline_data:
            date = kline['time_key'][:10]
            if date not in daily_data:
                daily_data[date] = []
            daily_data[date].append(kline)

        low_deviations = []
        amplitudes = []

        for date, day_klines in daily_data.items():
            if len(day_klines) < 10:  # 数据不足跳过
                continue

            # 获取开盘价（第一根K线）
            open_price = day_klines[0]['open_price']
            if open_price <= 0:
                continue

            # 计算日内最低价
            day_low = min(k['low_price'] for k in day_klines)
            day_high = max(k['high_price'] for k in day_klines)

            # 日内低点偏离度 = (开盘价 - 日内最低价) / 开盘价
            low_deviation = (open_price - day_low) / open_price * 100
            low_deviations.append(low_deviation)

            # 日内振幅 = (最高价 - 最低价) / 开盘价
            amplitude = (day_high - day_low) / open_price * 100
            amplitudes.append(amplitude)

        if not low_deviations:
            return {}

        # 排序计算分位数
        low_deviations.sort()
        n = len(low_deviations)

        return {
            'avg_low_deviation': sum(low_deviations) / n,
            'p50_low_deviation': low_deviations[int(n * 0.5)],
            'p70_low_deviation': low_deviations[int(n * 0.7)],
            'avg_amplitude': sum(amplitudes) / len(amplitudes) if amplitudes else 0,
            'trading_days': n
        }
