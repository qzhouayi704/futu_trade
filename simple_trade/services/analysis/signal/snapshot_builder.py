#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SnapshotBuilder — 统一数据引擎

职责：
- 调用各数据源（报价、K线、资金流、成交分析等）
- 为每只股票构建一份 StockSnapshot（不可变快照）
- 所有指标只计算一次，所有策略共享

使用方式：
    builder = SnapshotBuilder(container)
    snapshots = builder.build_batch(stock_codes)
    # snapshots: Dict[str, StockSnapshot]
    # 各策略直接消费: strategy.score(snapshots["HK.00700"])
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from .stock_snapshot import StockSnapshot

logger = logging.getLogger(__name__)


class SnapshotBuilder:
    """统一数据引擎 — 构建股票指标快照"""

    def __init__(self, container=None):
        """
        初始化快照构建器

        Args:
            container: 服务容器（提供 futu_client, db_manager 等）
        """
        self.container = container
        self._snapshot_cache: Dict[str, StockSnapshot] = {}
        self._cache_timestamp: Optional[datetime] = None

    def build_batch(
        self,
        stock_codes: List[str],
        quote_data: Dict[str, dict] = None,
        kline_data: Dict[str, Any] = None,
        capital_data: Dict[str, dict] = None,
        plate_data: Dict[str, dict] = None,
        ticker_data: Dict[str, dict] = None,
        position_codes: set = None,
        stock_tags: Dict[str, dict] = None,
        liquidity_data: Dict[str, dict] = None,
    ) -> Dict[str, StockSnapshot]:
        """
        批量构建股票快照

        各数据源可以预先获取后传入，也可以为 None（跳过该维度）。
        这种设计让调用方可以控制数据获取的粒度和时机。

        Args:
            stock_codes: 股票代码列表
            quote_data: {code: quote_dict} 报价数据
            kline_data: {code: kline_df} K线数据
            capital_data: {code: capital_dict} 资金流向数据
            plate_data: {code: plate_dict} 板块数据
            ticker_data: {code: ticker_dict} 成交分析数据
            position_codes: 持仓股票代码集合
            stock_tags: {code: tag_dict} 股票标签
            liquidity_data: {code: liquidity_dict} 流动性数据

        Returns:
            {stock_code: StockSnapshot} 快照字典
        """
        results = {}
        position_codes = position_codes or set()

        for code in stock_codes:
            try:
                snapshot = self._build_one(
                    code=code,
                    quote=quote_data.get(code) if quote_data else None,
                    kline=kline_data.get(code) if kline_data else None,
                    capital=capital_data.get(code) if capital_data else None,
                    plate=plate_data.get(code) if plate_data else None,
                    ticker=ticker_data.get(code) if ticker_data else None,
                    is_position=code in position_codes,
                    stock_tag=stock_tags.get(code) if stock_tags else None,
                    liquidity=liquidity_data.get(code) if liquidity_data else None,
                )
                if snapshot:
                    results[code] = snapshot
            except Exception as e:
                logger.error(f"构建快照失败 {code}: {e}", exc_info=True)

        # 更新缓存
        self._snapshot_cache.update(results)
        self._cache_timestamp = datetime.now()
        logger.info(f"[SnapshotBuilder] 构建 {len(results)}/{len(stock_codes)} 只快照")

        return results

    def get_cached(self, code: str) -> Optional[StockSnapshot]:
        """从缓存获取快照"""
        return self._snapshot_cache.get(code)

    def get_all_cached(self) -> Dict[str, StockSnapshot]:
        """获取全部缓存快照"""
        return dict(self._snapshot_cache)

    def _build_one(
        self,
        code: str,
        quote: Optional[dict] = None,
        kline: Optional[Any] = None,
        capital: Optional[dict] = None,
        plate: Optional[dict] = None,
        ticker: Optional[dict] = None,
        is_position: bool = False,
        stock_tag: Optional[dict] = None,
        liquidity: Optional[dict] = None,
    ) -> Optional[StockSnapshot]:
        """构建单只股票的快照"""

        if not quote:
            return None

        # ── 基础行情 ──────────────────────
        last_price = quote.get('last_price') or quote.get('cur_price', 0)
        change_rate = quote.get('change_percent') or quote.get('change_rate', 0)
        market = "HK" if code.startswith("HK.") else "US"

        # ── 资金流向 ──────────────────────
        cap_score = 50.0
        net_inflow = 0.0
        big_ratio = 0.5
        main_inflow = 0.0
        if capital:
            cap_score = capital.get('capital_score', 50.0)
            net_inflow = capital.get('net_inflow_ratio', 0.0)
            big_ratio = capital.get('big_order_buy_ratio', 0.5)
            main_inflow = capital.get('main_net_inflow', 0.0)

        # ── 价格位置与趋势（从K线计算）───
        price_pos_30d = 50.0
        kline_pos_20d = 0.5
        change_5d = 0.0
        prev_day_change = 0.0
        if kline is not None and hasattr(kline, '__len__') and len(kline) >= 5:
            try:
                price_pos_30d = self._calc_price_position(last_price, kline, days=30)
                kline_pos_20d = self._calc_kline_position(last_price, kline, days=20)
                change_5d = self._calc_change_nd(kline, days=5)
                prev_day_change = self._calc_prev_day_change(kline)
            except Exception as e:
                logger.debug(f"K线计算失败 {code}: {e}")

        # ── 板块信息 ──────────────────────
        p_strength = 0.0
        p_rank = 999
        plates_tuple = ()
        if plate:
            p_strength = plate.get('strength_score', 0.0)
            p_rank = plate.get('rank', 999)
        # plates 从 quote 或独立数据获取
        raw_plates = quote.get('plates', [])
        if isinstance(raw_plates, (list, tuple)):
            plates_tuple = tuple(raw_plates)

        # ── 成交分析 ───────��──────────────
        t_score = None
        t_ratio = None
        t_big_pct = None
        t_signal = None
        if ticker:
            t_score = ticker.get('score') or ticker.get('combined_score')
            t_ratio = ticker.get('buy_sell_ratio')
            t_big_pct = ticker.get('big_order_pct')
            t_signal = ticker.get('signal')

        # ── 流动性 ────────────────────────
        liq_score = None
        liq_level = None
        vol_anomaly = False
        if liquidity:
            liq_score = liquidity.get('liquidity_score')
            liq_level = liquidity.get('liquidity_level')
            vol_anomaly = liquidity.get('is_volume_anomaly', False)

        return StockSnapshot(
            code=code,
            name=quote.get('name', ''),
            market=market,
            timestamp=datetime.now(),
            # 行情
            last_price=last_price,
            change_rate=change_rate,
            prev_close=quote.get('prev_close_price') or quote.get('prev_close', 0),
            open_price=quote.get('open_price', 0),
            high_price=quote.get('high_price', 0),
            low_price=quote.get('low_price', 0),
            amplitude=quote.get('amplitude', 0),
            # 量能
            volume=quote.get('volume', 0),
            turnover=quote.get('turnover', 0),
            turnover_rate=quote.get('turnover_rate', 0),
            volume_ratio=quote.get('volume_ratio', 0),
            # 资金
            capital_score=cap_score,
            net_inflow_ratio=net_inflow,
            big_order_buy_ratio=big_ratio,
            main_net_inflow=main_inflow,
            # 位置
            price_position_30d=price_pos_30d,
            kline_position_20d=kline_pos_20d,
            change_5d=change_5d,
            prev_day_change=prev_day_change,
            # 板块
            plate_strength=p_strength,
            plate_rank=p_rank,
            plates=plates_tuple,
            # 成交
            ticker_score=t_score,
            ticker_buy_sell_ratio=t_ratio,
            ticker_big_order_pct=t_big_pct,
            ticker_signal=t_signal,
            # 流动性
            liquidity_score=liq_score,
            liquidity_level=liq_level,
            is_volume_anomaly=vol_anomaly,
            # 标签
            is_position=is_position,
            stock_tag=stock_tag,
        )

    # ── 内部计算方法 ─────────────────────

    @staticmethod
    def _calc_price_position(current_price: float, kline, days: int = 30) -> float:
        """计算N日价格位置 (0-100%)"""
        try:
            recent = kline.tail(days) if hasattr(kline, 'tail') else kline[-days:]
            if hasattr(recent, 'max'):
                high = recent['high'].max()
                low = recent['low'].min()
            else:
                high = max(k.get('high_price', k.get('high', 0)) for k in recent)
                low = min(k.get('low_price', k.get('low', 0)) for k in recent)
            if high == low:
                return 50.0
            return round((current_price - low) / (high - low) * 100, 2)
        except Exception:
            return 50.0

    @staticmethod
    def _calc_kline_position(current_price: float, kline, days: int = 20) -> float:
        """计算K线位置 (0-1+)"""
        try:
            recent = kline.tail(days) if hasattr(kline, 'tail') else kline[-days:]
            if hasattr(recent, 'max'):
                high = recent['high'].max()
                low = recent['low'].min()
            else:
                high = max(k.get('high_price', k.get('high', 0)) for k in recent)
                low = min(k.get('low_price', k.get('low', 0)) for k in recent)
            if high == low:
                return 0.5
            return round((current_price - low) / (high - low), 4)
        except Exception:
            return 0.5

    @staticmethod
    def _calc_change_nd(kline, days: int = 5) -> float:
        """计算N日累计涨幅"""
        try:
            if hasattr(kline, 'iloc'):
                if len(kline) < days + 1:
                    return 0.0
                close_now = kline['close'].iloc[-1]
                close_nd = kline['close'].iloc[-(days + 1)]
            else:
                if len(kline) < days + 1:
                    return 0.0
                close_now = kline[-1].get('close_price', kline[-1].get('close', 0))
                close_nd = kline[-(days + 1)].get('close_price', kline[-(days + 1)].get('close', 0))
            if close_nd == 0:
                return 0.0
            return round((close_now - close_nd) / close_nd * 100, 2)
        except Exception:
            return 0.0

    @staticmethod
    def _calc_prev_day_change(kline) -> float:
        """计算前日涨幅"""
        try:
            if hasattr(kline, 'iloc'):
                if len(kline) < 2:
                    return 0.0
                close_prev = kline['close'].iloc[-2]
                close_prev2 = kline['close'].iloc[-3] if len(kline) >= 3 else close_prev
            else:
                if len(kline) < 2:
                    return 0.0
                close_prev = kline[-2].get('close_price', kline[-2].get('close', 0))
                close_prev2 = kline[-3].get('close_price', kline[-3].get('close', 0)) if len(kline) >= 3 else close_prev
            if close_prev2 == 0:
                return 0.0
            return round((close_prev - close_prev2) / close_prev2 * 100, 2)
        except Exception:
            return 0.0
