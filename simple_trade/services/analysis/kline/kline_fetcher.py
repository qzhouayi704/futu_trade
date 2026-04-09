#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K线数据获取服务

负责从富途API获取K线数据，内置频率控制和重试机制。
频率限制：每30秒最多60次历史K线请求。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from ....api.futu_client import FutuClient
from ....api.market_types import ReturnCode
from ....config.config import Config
from ....core.models import KlineData
from ....utils.rate_limiter import get_global_rate_limiter, RateLimiter
from ....utils.retry_helper import retry_with_backoff, RetryConfig
from ....utils.error_parsers import parse_futu_error


class KlineFetcher:
    """K线数据获取服务（内置频率控制）"""

    # 富途API限制：30秒内最多60次历史K线请求
    DEFAULT_MAX_REQUESTS = 60
    DEFAULT_TIME_WINDOW = 30

    def __init__(self, futu_client: FutuClient, config: Config):
        self.futu_client = futu_client
        self.config = config

        # 频率控制器（全局单例，所有调用方共享）
        rate_cfg = config.kline_rate_limit
        self.rate_limiter: RateLimiter = get_global_rate_limiter(
            max_requests=rate_cfg.get("max_requests", self.DEFAULT_MAX_REQUESTS),
            time_window=rate_cfg.get("time_window", self.DEFAULT_TIME_WINDOW)
        )

        # 重试配置
        retry_cfg = config.kline_retry
        self.retry_config: Optional[RetryConfig] = None
        if retry_cfg.get("enabled", True):
            self.retry_config = RetryConfig(
                max_retries=retry_cfg.get("max_retries", 3),
                initial_backoff=retry_cfg.get("initial_backoff", 1.0),
                max_backoff=retry_cfg.get("max_backoff", 32.0),
                backoff_multiplier=retry_cfg.get("backoff_multiplier", 2.0)
            )

        # K线额度缓存
        self._quota_cache: Dict[str, Any] = {
            'data': None,
            'last_update': None,
            'cache_valid_hours': 24
        }

    # ==================== 核心获取方法 ====================

    def fetch_kline(
        self,
        stock_code: str,
        days: int,
        limit_days: Optional[int] = None
    ) -> List[KlineData]:
        """获取K线数据（统一入口，内置频率控制+重试）

        Args:
            stock_code: 股票代码
            days: 请求的历史天数
            limit_days: 只返回最近N天数据（None=全部返回）

        Returns:
            KlineData 列表
        """
        if self.retry_config:
            @retry_with_backoff(self.retry_config)
            def _with_retry():
                return self._fetch_kline_internal(stock_code, days, limit_days)
            try:
                return _with_retry()
            except Exception as e:
                logging.error(f"获取{stock_code}K线数据失败（已重试）: {e}")
                return []
        return self._fetch_kline_internal(stock_code, days, limit_days)

    def _fetch_kline_internal(
        self,
        stock_code: str,
        days: int,
        limit_days: Optional[int] = None
    ) -> List[KlineData]:
        """内部方法：单次获取K线数据"""
        if not self.futu_client.is_available():
            logging.debug(f"获取K线失败: {stock_code}, 富途API不可用")
            return []

        # 频率控制：请求前等待
        self.rate_limiter.wait_if_needed()

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days + 30)).strftime('%Y-%m-%d')

        ret, data, _ = self.futu_client.request_history_kline(
            code=stock_code, start=start_date, end=end_date, max_count=1000
        )

        if ReturnCode.is_ok(ret) and data is not None and not data.empty:
            df = data.tail(limit_days) if limit_days else data
            return self._parse_dataframe(df)

        # 错误处理
        error_msg, error_type = self._parse_error(ret, data)
        if self.retry_config and error_type in ('rate_limit', 'timeout'):
            raise Exception(error_msg)

        if ret == 0:
            logging.debug(f"K线无数据: {stock_code}, {error_msg}")
        else:
            logging.warning(f"K线获取失败: {stock_code}, {error_msg}")
        return []

    # ==================== 向后兼容方法 ====================

    def fetch_kline_data(self, stock_code: str, days: int) -> List[Dict[str, Any]]:
        """获取K线数据（兼容旧接口，返回字典列表）"""
        records = self.fetch_kline(stock_code, days)
        return [self._record_to_dict(r) for r in records]

    def fetch_kline_data_with_limit(
        self, stock_code: str, days: int, limit_days: int = None
    ) -> List[Dict[str, Any]]:
        """获取K线数据（兼容旧接口，返回字典列表）"""
        records = self.fetch_kline(stock_code, days, limit_days)
        return [self._record_to_dict(r) for r in records]

    # ==================== 额度管理 ====================

    def get_quota_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        """获取K线额度信息（带缓存）"""
        if not force_refresh and self._is_quota_cache_valid():
            return self._quota_cache['data']

        quota_data = {
            'used': 0, 'remaining': 0, 'total': 0, 'usage_rate': 0.0,
            'last_update': datetime.now().isoformat(), 'status': 'unknown'
        }

        try:
            if not self.futu_client.is_available():
                quota_data['status'] = 'api_disconnected'
                return quota_data

            ret, data = self.futu_client.get_history_kl_quota(get_detail=True)
            if ReturnCode.is_ok(ret):
                parsed = self._parse_quota_data(data)
                quota_data.update(parsed)
                quota_data['usage_rate'] = (
                    round(parsed['used'] / parsed['total'] * 100, 2)
                    if parsed['total'] > 0 else 0.0
                )
                quota_data['status'] = 'connected'
                quota_data['last_update'] = datetime.now().isoformat()
                self._quota_cache['data'] = quota_data
                self._quota_cache['last_update'] = datetime.now()
                logging.info(f"K线额度: 已用{quota_data['used']}, 剩余{quota_data['remaining']}")
            else:
                quota_data['status'] = 'api_error'
        except Exception as e:
            logging.error(f"获取K线额度异常: {e}")
            quota_data['status'] = 'error'

        return quota_data

    def get_cached_quota_info(self) -> Optional[Dict[str, Any]]:
        """获取缓存的额度信息"""
        return self._quota_cache['data'] if self._is_quota_cache_valid() else None

    def clear_quota_cache(self):
        """清除额度缓存"""
        self._quota_cache['data'] = None
        self._quota_cache['last_update'] = None

    # ==================== 内部工具方法 ====================

    @staticmethod
    def _parse_dataframe(df) -> List[KlineData]:
        """将 DataFrame 解析为 KlineData 列表"""
        records = []
        for _, row in df.iterrows():
            records.append(KlineData(
                time_key=row['time_key'],
                open_price=float(row['open']),
                close_price=float(row['close']),
                high_price=float(row['high']),
                low_price=float(row['low']),
                volume=int(row['volume']),
                turnover=float(row.get('turnover', 0)),
                pe_ratio=float(row.get('pe_ratio', 0)) if row.get('pe_ratio') else None,
                turnover_rate=float(row.get('turnover_rate', 0)) if row.get('turnover_rate') else None
            ))
        return records

    @staticmethod
    def _record_to_dict(record: KlineData) -> Dict[str, Any]:
        """KlineData 转为兼容旧代码的字典"""
        return {
            'time_key': record.time_key,
            'open_price': record.open_price,
            'close_price': record.close_price,
            'high_price': record.high_price,
            'low_price': record.low_price,
            'volume': record.volume,
            'turnover': record.turnover,
            'pe_ratio': record.pe_ratio,
            'turnover_rate': record.turnover_rate
        }

    @staticmethod
    def _parse_error(ret, data) -> Tuple[str, str]:
        """解析K线获取失败的原因 → (message, error_type)"""
        return parse_futu_error(ret, data)
        if ret == 0:
            return "数据为空（非交易日或无数据）", "no_data"
        return f"未知错误码: {ret}", "unknown"

    def _is_quota_cache_valid(self) -> bool:
        """检查额度缓存是否有效"""
        if not self._quota_cache['data'] or not self._quota_cache['last_update']:
            return False
        hours = (datetime.now() - self._quota_cache['last_update']).total_seconds() / 3600
        return hours < self._quota_cache['cache_valid_hours']

    def _parse_quota_data(self, data) -> Dict[str, Any]:
        """解析富途API返回的额度数据

        富途API get_history_kl_quota 返回格式为 tuple:
        (used_quota: int, remain_quota: int, detail_list: list)
        """
        quota = {'used': 0, 'remaining': 0, 'total': 0}
        try:
            if isinstance(data, tuple) and len(data) >= 2:
                # 标准返回格式: (used_quota, remain_quota, detail_list)
                used = int(data[0]) if data[0] is not None else 0
                remain = int(data[1]) if data[1] is not None else 0
                quota = {'used': used, 'remaining': remain, 'total': used + remain}
            elif hasattr(data, 'iloc') and len(data) > 0:
                row = data.iloc[0]
                used = remain = 0
                for col in data.columns:
                    cl = col.lower()
                    if 'used' in cl or 'use' in cl:
                        used = int(row[col]) if row[col] is not None else 0
                    elif 'remain' in cl or 'left' in cl:
                        remain = int(row[col]) if row[col] is not None else 0
                quota = {'used': used, 'remaining': remain, 'total': used + remain}
            elif isinstance(data, dict):
                used = int(data.get('used_quota', data.get('used', 0)))
                remain = int(data.get('remain_quota', data.get('remaining', 0)))
                quota = {'used': used, 'remaining': remain, 'total': used + remain}
            else:
                logging.warning(f"未知的额度数据格式: type={type(data)}, data={data}")
        except Exception as e:
            logging.error(f"解析额度数据失败: {e}")
        return quota

    # 兼容旧代码的方法名
    parse_kline_error = _parse_error
