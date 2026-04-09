#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热度报价服务

为热度分析提供独立的全量股票快照获取能力，
通过 Futu API 的 get_market_snapshot 接口批量获取市场快照数据。
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from ....api.futu_client import FutuClient
from ....api.market_types import ReturnCode
from ....utils.rate_limiter import wait_for_api
from ....utils.retry_helper import parse_error_type, ErrorType


BATCH_SIZE = 400  # 每批最大股票数
MAX_RATE_LIMIT_RETRIES = 2  # 频率限制最大重试次数
MAX_INVALID_RETRIES = 3  # 单批次无效股票剔除最大重试次数
RATE_LIMIT_WAIT_SECONDS = 30  # 频率限制等待秒数
CACHE_TTL = 60  # 缓存有效期（秒）

# 无效股票错误关键词
_INVALID_KEYWORDS = ['OTC', '暂不提供美股 OTC 市场行情', '未知股票', 'unknown stock']


@dataclass
class SnapshotQuote:
    """市场快照报价数据项"""
    last_price: float       # 最新价
    change_pct: float       # 涨跌幅 (%)
    volume: int             # 成交量
    volume_ratio: float     # 量比
    turnover_rate: float    # 换手率 (%)
    net_inflow_ratio: float  # 资金净流入占比
    market_cap: float           # 总市值


class HeatQuoteService:
    """热度报价服务 - 独立获取全量股票快照"""

    def __init__(self, futu_client: FutuClient):
        self.futu_client = futu_client
        self.logger = logging.getLogger(__name__)
        self._cache: Optional[Dict[str, SnapshotQuote]] = None
        self._cache_time: float = 0.0
        self._known_invalid_codes: Set[str] = set()

    def get_snapshot_quotes(
        self, stock_codes: List[str]
    ) -> Dict[str, SnapshotQuote]:
        """获取股票快照报价（带缓存）

        缓存有效时直接返回缓存数据，过期时重新获取全量快照。
        API 完全失败时降级返回过期缓存数据（如有），否则返回空字典。

        Args:
            stock_codes: 需要获取报价的股票代码列表

        Returns:
            {stock_code: SnapshotQuote} 字典
        """
        if not stock_codes:
            return {}

        # 缓存有效时直接返回
        if self._is_cache_valid():
            self.logger.debug("热度报价缓存命中，直接返回缓存数据")
            return dict(self._cache)  # type: ignore

        # 缓存过期，重新获取
        self.logger.info("热度报价缓存过期，开始获取全量快照")
        try:
            quotes = self._fetch_all_snapshots(stock_codes)
        except Exception as e:
            self.logger.error(f"获取全量快照异常: {e}", exc_info=True)
            quotes = {}

        if quotes:
            # 获取成功，更新缓存
            self._cache = quotes
            self._cache_time = time.time()

            # 覆盖率检查
            self._check_coverage(quotes, stock_codes)

            return dict(quotes)

        # API 完全失败，降级逻辑
        if self._cache is not None:
            self.logger.error(
                "全量快照获取失败，降级返回过期缓存数据"
            )
            return dict(self._cache)

        self.logger.error(
            "全量快照获取失败且无可用缓存，返回空字典"
        )
        return {}

    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if self._cache is None:
            return False
        return (time.time() - self._cache_time) < CACHE_TTL

    def _check_coverage(
        self,
        quotes: Dict[str, SnapshotQuote],
        stock_codes: List[str],
    ) -> None:
        """检查报价覆盖率，低于 50% 时记录警告"""
        total = len(stock_codes)
        if total == 0:
            return

        covered = len(quotes)
        coverage = covered / total

        if coverage < 0.5:
            self.logger.warning(
                f"报价覆盖率不足: {covered}/{total} "
                f"({coverage:.1%})，低于 50% 阈值"
            )


    def _fetch_batch(
        self, batch: List[str], batch_num: int
    ) -> Dict[str, SnapshotQuote]:
        """获取单批快照，带频率限制重试和无效股票剔除

        当批次因无效股票失败时，从错误消息中提取股票代码，
        剔除后重试剩余股票，避免一只坏股票导致整批 400 只被跳过。
        """
        result: Dict[str, SnapshotQuote] = {}
        remaining = list(batch)

        for attempt in range(1 + MAX_RATE_LIMIT_RETRIES + MAX_INVALID_RETRIES):
            if not remaining:
                return result

            wait_for_api('market_snapshot')

            try:
                ret, data = self.futu_client.client.get_market_snapshot(remaining)

                if ReturnCode.is_ok(ret):
                    result.update(self._parse_snapshot_data(data, batch_num))
                    return result

                error_msg = data if isinstance(data, str) else str(data)
                error_type = parse_error_type(error_msg)

                # 频率限制：等待后重试
                if error_type == ErrorType.RATE_LIMIT:
                    if attempt < MAX_RATE_LIMIT_RETRIES:
                        self.logger.warning(
                            f"批次 {batch_num} 触发频率限制，"
                            f"等待 {RATE_LIMIT_WAIT_SECONDS} 秒后重试 "
                            f"({attempt + 1}/{MAX_RATE_LIMIT_RETRIES})"
                        )
                        time.sleep(RATE_LIMIT_WAIT_SECONDS)
                        continue
                    self.logger.warning(f"批次 {batch_num} 频率限制重试已耗尽，跳过")
                    return result

                # 无效股票错误：提取代码，剔除后重试
                if self._is_invalid_stock_error(error_msg):
                    bad_code = self._find_invalid_code(error_msg, remaining)
                    if bad_code:
                        self._known_invalid_codes.add(bad_code)
                        remaining = [c for c in remaining if c != bad_code]
                        self.logger.info(
                            f"批次 {batch_num} 检测到无效股票 {bad_code}，"
                            f"剔除后重试（剩余 {len(remaining)} 只）"
                        )
                        continue

                self.logger.warning(
                    f"批次 {batch_num} 获取市场快照失败: {error_msg}"
                )
                return result

            except Exception as e:
                self.logger.error(
                    f"批次 {batch_num} 获取快照异常: {e}", exc_info=True
                )
                return result

        return result

    @staticmethod
    def _is_invalid_stock_error(error_msg: str) -> bool:
        """判断是否为无效股票错误（OTC 或未知股票）"""
        msg_lower = error_msg.lower()
        return any(kw.lower() in msg_lower for kw in _INVALID_KEYWORDS)

    @staticmethod
    def _find_invalid_code(
        error_msg: str, batch: List[str]
    ) -> Optional[str]:
        """从错误消息中提取无效股票代码，并匹配 batch 中的完整代码

        错误消息格式示例：
        - "暂不提供美股 OTC 市场行情 SSKN" → 匹配 batch 中的 "US.SSKN"
        - "未知股票 TRUE" → 匹配 batch 中的 "US.TRUE"
        """
        # 提取末尾的短名称（如 SSKN、TRUE）
        m = re.search(r'\s([A-Z][A-Z0-9]{1,10})\s*$', error_msg)
        if not m:
            return None
        short_name = m.group(1)

        # 在 batch 中查找包含该短名称的完整代码（如 US.SSKN）
        for code in batch:
            if code.endswith(f'.{short_name}') or code == short_name:
                return code
        return None

    def _parse_snapshot_data(
        self, data, batch_num: int
    ) -> Dict[str, SnapshotQuote]:
        """解析 DataFrame 行转为 SnapshotQuote 字典"""
        result: Dict[str, SnapshotQuote] = {}

        if data is None or data.empty:
            self.logger.warning(f"批次 {batch_num} 返回空数据")
            return result

        for _, row in data.iterrows():
            code = row.get('code', '')
            if not code:
                continue

            try:
                quote = SnapshotQuote(
                    last_price=float(row.get('last_price', 0) or 0),
                    change_pct=float(row.get('change_rate', 0) or 0),
                    volume=int(row.get('volume', 0) or 0),
                    volume_ratio=float(row.get('volume_ratio', 0) or 0),
                    turnover_rate=float(row.get('turnover_rate', 0) or 0),
                    net_inflow_ratio=float(
                        row.get('net_inflow_rate', 0) or 0
                    ),
                    market_cap=float(
                        row.get('market_val', 0) or 0
                    ),
                )
                result[code] = quote
            except (ValueError, TypeError) as e:
                self.logger.warning(
                    f"批次 {batch_num} 解析股票 {code} 数据失败: {e}"
                )
                continue

        return result

    def _fetch_all_snapshots(
        self, stock_codes: List[str]
    ) -> Dict[str, SnapshotQuote]:
        """批量获取市场快照（每批 ≤ 400 只）

        Args:
            stock_codes: 需要获取报价的股票代码列表

        Returns:
            {stock_code: SnapshotQuote} 字典
        """
        if not stock_codes:
            return {}

        # 预过滤已知无效股票
        codes = [c for c in stock_codes if c not in self._known_invalid_codes]
        if len(codes) < len(stock_codes):
            self.logger.debug(
                f"预过滤 {len(stock_codes) - len(codes)} 只已知无效股票"
            )

        all_quotes: Dict[str, SnapshotQuote] = {}
        total_batches = (len(codes) + BATCH_SIZE - 1) // BATCH_SIZE

        self.logger.info(
            f"开始获取 {len(codes)} 只股票快照，"
            f"分 {total_batches} 批处理"
        )

        for i in range(0, len(codes), BATCH_SIZE):
            batch = codes[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1

            batch_quotes = self._fetch_batch(batch, batch_num)

            if batch_quotes:
                all_quotes.update(batch_quotes)
                self.logger.debug(
                    f"批次 {batch_num}/{total_batches} 获取 "
                    f"{len(batch_quotes)} 只股票快照"
                )
            else:
                self.logger.warning(
                    f"批次 {batch_num}/{total_batches} 获取快照失败，"
                    f"跳过 {len(batch)} 只股票"
                )

        self.logger.info(
            f"快照获取完成: {len(all_quotes)}/{len(codes)} 只股票"
        )
        return all_quotes
