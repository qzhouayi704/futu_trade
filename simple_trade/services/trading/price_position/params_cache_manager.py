#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置参数缓存管理器

负责异步获取回测分析结果并缓存，供实时策略使用。
缓存当日有效，收盘后自动过期。
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

from .pp_live_models import CachedAnalysisParams, FailureRecord


# 缓存过期时间：当日 17:00（港股收盘后）
_EXPIRE_HOUR = 17

# 分析轮询间隔（秒）
_POLL_INTERVAL = 3.0

# 最大轮询次数（约 3 分钟超时）
_MAX_POLL_COUNT = 60


class ParamsCacheManager:
    """
    参数缓存管理器

    - get_params(stock_code): 获取缓存参数，无缓存返回 None
    - request_analysis(stock_code): 异步触发分析，完成后自动缓存
    - put_params(stock_code, result): 手动写入缓存（供 analysis 路由使用）
    """

    def __init__(self, analysis_service=None):
        """
        Args:
            analysis_service: AnalysisService 实例（可延迟注入）
        """
        self._analysis_service = analysis_service
        self._cache: Dict[str, CachedAnalysisParams] = {}
        self._pending: Set[str] = set()  # 正在分析中的股票代码
        self._failure_records: Dict[str, FailureRecord] = {}  # 失败记录
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # 主事件循环引用

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """注入主事件循环引用（应在 async 上下文中调用）"""
        self._loop = loop

    def set_analysis_service(self, service):
        """延迟注入 AnalysisService"""
        self._analysis_service = service

    def get_params(self, stock_code: str) -> Optional[CachedAnalysisParams]:
        """获取缓存的分析参数，过期或不存在返回 None"""
        cached = self._cache.get(stock_code)
        if not cached:
            return None

        # 检查过期
        if cached.expires_at:
            try:
                expires = datetime.fromisoformat(cached.expires_at)
                if datetime.now() > expires:
                    del self._cache[stock_code]
                    logging.info(f"[参数缓存] {stock_code} 缓存已过期，已清除")
                    return None
            except ValueError:
                pass

        return cached

    def put_params(self, stock_code: str, analysis_result: Dict) -> bool:
        """
        手动写入缓存（供 analysis 路由在分析完成后调用）

        Args:
            stock_code: 股票代码
            analysis_result: AnalysisService 的 task['result'] 字典

        Returns:
            是否成功写入
        """
        try:
            now = datetime.now()
            expires = now.replace(hour=_EXPIRE_HOUR, minute=0, second=0, microsecond=0)
            if now.hour >= _EXPIRE_HOUR:
                expires += timedelta(days=1)

            cached = CachedAnalysisParams.from_analysis_result(
                stock_code=stock_code,
                result=analysis_result,
                analyzed_at=now.isoformat(),
                expires_at=expires.isoformat(),
            )
            self._cache[stock_code] = cached
            self._pending.discard(stock_code)
            logging.info(
                f"[参数缓存] {stock_code} 已缓存，"
                f"zone参数 {len(cached.zone_params)} 个区间，"
                f"开盘类型参数 {list(cached.open_type_params.keys())}"
            )
            return True
        except Exception as e:
            logging.error(f"[参数缓存] {stock_code} 写入缓存失败: {e}")
            return False

    def is_pending(self, stock_code: str) -> bool:
        """是否正在分析中"""
        return stock_code in self._pending

    def _classify_error(self, error_message: str) -> str:
        """
        分类错误类型

        永久失败（permanent）：
        - 无法获取K线数据（股票无效/退市）
        - 股票不存在
        - 数据不足

        当日失败（daily）：
        - 额度不足 - 当天不重试，第二天允许重试

        临时失败（temporary）：
        - 网络超时
        - 频率限制
        - 富途客户端未连接
        """
        permanent_keywords = ['无法获取', '不存在', '数据不足', '无效']
        daily_keywords = ['额度不足', '额度已用完', 'quota', 'limit exceeded']
        temporary_keywords = ['超时', '频率限制', '未连接', 'timeout', 'rate_limit']

        error_lower = error_message.lower()
        if any(kw in error_lower for kw in permanent_keywords):
            return 'permanent'
        if any(kw in error_lower for kw in daily_keywords):
            return 'daily'
        if any(kw in error_lower for kw in temporary_keywords):
            return 'temporary'
        return 'temporary'  # 默认视为临时失败

    def _record_failure(self, stock_code: str, error: str, error_type: str):
        """记录失败信息"""
        if stock_code in self._failure_records:
            record = self._failure_records[stock_code]
            record.failure_count += 1
            record.last_failure_time = datetime.now().isoformat()
            record.error_message = error
            # 如果之前是临时失败，现在是永久失败，更新类型
            if error_type == 'permanent':
                record.error_type = 'permanent'
        else:
            self._failure_records[stock_code] = FailureRecord(
                stock_code=stock_code,
                failure_count=1,
                last_failure_time=datetime.now().isoformat(),
                error_type=error_type,
                error_message=error
            )

    def request_analysis(self, stock_code: str):
        """
        异步触发回测分析，完成后自动写入缓存。
        重复调用同一股票会被忽略。
        """
        if stock_code in self._cache or stock_code in self._pending:
            return

        # 检查失败记录
        if stock_code in self._failure_records:
            record = self._failure_records[stock_code]

            # 永久失败：直接拒绝
            if record.error_type == 'permanent':
                logging.debug(
                    f"[参数缓存] {stock_code} 已标记为永久失败，跳过分析 "
                    f"(失败{record.failure_count}次)"
                )
                return

            # 当日失败（如额度不足）：当天不重试，第二天允许
            if record.error_type == 'daily':
                last_time = datetime.fromisoformat(record.last_failure_time)
                # 检查是否是同一天
                if last_time.date() == datetime.now().date():
                    logging.debug(
                        f"[参数缓存] {stock_code} 当日失败（{record.error_message}），"
                        f"今日不再重试"
                    )
                    return
                else:
                    # 新的一天，清除失败记录，允许重试
                    logging.info(
                        f"[参数缓存] {stock_code} 新的一天，清除昨日失败记录，允许重试"
                    )
                    del self._failure_records[stock_code]

            # 临时失败：检查重试次数和时间间隔
            if record.error_type == 'temporary' and record.failure_count >= 3:
                last_time = datetime.fromisoformat(record.last_failure_time)
                # 3次失败后，等待30分钟再重试
                if datetime.now() - last_time < timedelta(minutes=30):
                    logging.debug(
                        f"[参数缓存] {stock_code} 临时失败{record.failure_count}次，"
                        f"等待冷却期后再重试"
                    )
                    return

        if not self._analysis_service:
            logging.warning(f"[参数缓存] AnalysisService 未注入，无法分析 {stock_code}")
            return

        self._pending.add(stock_code)
        logging.info(f"[参数缓存] 触发异步分析: {stock_code}")

        loop = self._loop
        if loop is None or loop.is_closed():
            self._pending.discard(stock_code)
            logging.warning(f"[参数缓存] 主事件循环未设置或已关闭，分析取消: {stock_code}")
            return

        asyncio.run_coroutine_threadsafe(self._poll_analysis(stock_code), loop)

    async def _poll_analysis(self, stock_code: str):
        """启动分析并轮询结果"""
        try:
            task_id = self._analysis_service.start_analysis(stock_code)
            logging.info(f"[参数缓存] {stock_code} 分析任务已启动: {task_id}")

            for _ in range(_MAX_POLL_COUNT):
                await asyncio.sleep(_POLL_INTERVAL)
                task_status = self._analysis_service.get_task_status(task_id)
                if not task_status:
                    break

                status = task_status.get('status', '')
                if status == 'completed':
                    result = task_status.get('result')
                    if result:
                        self.put_params(stock_code, result)
                    else:
                        logging.warning(f"[参数缓存] {stock_code} 分析完成但无结果")
                    return

                if status == 'error':
                    error = task_status.get('error', '未知错误')
                    error_type = self._classify_error(error)
                    self._record_failure(stock_code, error, error_type)
                    logging.error(f"[参数缓存] {stock_code} 分析失败: {error}")
                    return

            logging.warning(f"[参数缓存] {stock_code} 分析超时")
        except Exception as e:
            logging.error(f"[参数缓存] {stock_code} 分析异常: {e}")
        finally:
            self._pending.discard(stock_code)

    def clear_expired(self):
        """清除所有过期缓存"""
        now = datetime.now()
        expired = [
            code for code, cached in self._cache.items()
            if cached.expires_at and datetime.fromisoformat(cached.expires_at) < now
        ]
        for code in expired:
            del self._cache[code]
        if expired:
            logging.info(f"[参数缓存] 清除 {len(expired)} 个过期缓存")

    def get_cached_codes(self) -> list:
        """获取所有已缓存的股票代码"""
        return list(self._cache.keys())

    def clear_failure_records(self, stock_code: str = None):
        """清除失败记录（用于手动重置）"""
        if stock_code:
            self._failure_records.pop(stock_code, None)
            logging.info(f"[参数缓存] 已清除 {stock_code} 的失败记录")
        else:
            self._failure_records.clear()
            logging.info("[参数缓存] 已清除所有失败记录")

    def get_failure_summary(self) -> Dict:
        """获取失败统计摘要"""
        permanent_failures = [
            r for r in self._failure_records.values()
            if r.error_type == 'permanent'
        ]
        daily_failures = [
            r for r in self._failure_records.values()
            if r.error_type == 'daily'
        ]
        temporary_failures = [
            r for r in self._failure_records.values()
            if r.error_type == 'temporary'
        ]

        return {
            'total_failures': len(self._failure_records),
            'permanent_count': len(permanent_failures),
            'daily_count': len(daily_failures),
            'temporary_count': len(temporary_failures),
            'permanent_codes': [r.stock_code for r in permanent_failures],
            'daily_codes': [r.stock_code for r in daily_failures],
            'temporary_codes': [r.stock_code for r in temporary_failures],
        }

    def get_status(self) -> Dict:
        """获取缓存状态摘要"""
        return {
            'cached_count': len(self._cache),
            'pending_count': len(self._pending),
            'cached_codes': list(self._cache.keys()),
            'pending_codes': list(self._pending),
            'failure_summary': self.get_failure_summary(),
        }
