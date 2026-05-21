#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动量引擎 (MomentumEngine)

实时监听逐笔成交数据，通过7维度分析产出买卖信号:
  1. BSR买卖力量  2. Delta累积净力  3. 成交速度  4. 大单聚集
  5. VWAP偏离     6. 吸筹/派发     7. 多维共振

架构:
  Ticker推送 → TickerAggregator(1分钟聚合) → 7个Detector → ResonanceDetector → SignalPublisher
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Set

from .ticker_aggregator import TickerAggregator, AggregatedBar
from .bsr_monitor import BSRMonitor
from .delta_detector import DeltaDetector
from .velocity_detector import VelocityDetector
from .big_order_detector import BigOrderDetector
from .vwap_detector import VWAPDetector
from .absorption_detector import AbsorptionDetector
from .resonance_detector import ResonanceDetector
from .signal_publisher import SignalPublisher

logger = logging.getLogger(__name__)

HK_TZ = timezone(timedelta(hours=8))
MORNING_START = (9, 30)
MORNING_END = (12, 0)
AFTERNOON_START = (13, 0)
AFTERNOON_END = (16, 0)


class MomentumEngine:
    """动量引擎 — 7维度实时信号检测"""

    def __init__(self, container):
        self.container = container

        # 数据聚合
        self.aggregator = TickerAggregator()

        # 7个检测器
        self.bsr_monitor = BSRMonitor()
        self.delta_detector = DeltaDetector()
        self.velocity_detector = VelocityDetector()
        self.big_order_detector = BigOrderDetector()
        self.vwap_detector = VWAPDetector()
        self.absorption_detector = AbsorptionDetector()
        self.resonance_detector = ResonanceDetector()

        # 信号发布
        self.publisher = SignalPublisher(container)

        # 状态
        self._monitored: Set[str] = set()
        self._running = False
        self._bars_processed = 0
        self._signals_emitted = 0
        self._resonance_count = 0
        self._last_daily_reset: Optional[str] = None

    async def start(self):
        self._running = True
        self._sync_monitored_stocks()
        self._daily_reset()
        logger.info(f"[MomentumEngine] 启动成功(7维度), 监控 {len(self._monitored)} 只")
        asyncio.create_task(self._maintenance_loop())

    async def stop(self):
        self._running = False
        logger.info("[MomentumEngine] 已停止")

    def on_ticker(self, stock_code: str, ticker_data: dict):
        """逐笔数据回调入口"""
        if not self._running:
            return

        # 自动将收到数据的股票加入监控
        if stock_code not in self._monitored:
            self._monitored.add(stock_code)

        if not self._is_trading_time():
            return

        price = ticker_data.get('price', 0)
        volume = ticker_data.get('volume', 0)
        turnover = ticker_data.get('turnover', 0)
        direction = ticker_data.get('ticker_direction',
                    ticker_data.get('direction', 'NEUTRAL'))
        timestamp_ms = ticker_data.get('timestamp', int(time.time() * 1000))

        if not price or not volume:
            return

        completed_bar = self.aggregator.on_tick(
            stock_code, price, volume, turnover, direction, timestamp_ms
        )

        if completed_bar:
            asyncio.get_event_loop().create_task(
                self._process_bar(completed_bar)
            )

    async def _process_bar(self, bar: AggregatedBar):
        """处理完成的1分钟bar — 通过7个检测器"""
        self._bars_processed += 1

        try:
            signals = []

            # 1. BSR
            s = self.bsr_monitor.update(bar)
            if s:
                signals.append(s)

            # 2. Delta
            s = self.delta_detector.update(bar)
            if s:
                signals.append(s)

            # 3. 成交速度
            s = self.velocity_detector.update(bar)
            if s:
                signals.append(s)

            # 4. 大单聚集
            s = self.big_order_detector.update(bar)
            if s:
                signals.append(s)

            # 5. VWAP偏离
            s = self.vwap_detector.update(bar)
            if s:
                signals.append(s)

            # 6. 吸筹/派发
            s = self.absorption_detector.update(bar)
            if s:
                signals.append(s)

            # 发布各维度信号 + 收集到共振器
            for sig in signals:
                self._signals_emitted += 1
                await self.publisher.publish(sig)
                self.resonance_detector.collect_signal(
                    bar.stock_code, sig, bar.timestamp
                )

            # 7. 多维共振检查
            resonance = self.resonance_detector.check_resonance(
                bar.stock_code, bar.close_price, bar.timestamp
            )
            if resonance:
                self._resonance_count += 1
                self._signals_emitted += 1
                await self.publisher.publish(resonance)

        except Exception as e:
            logger.error(f"[MomentumEngine] 处理bar失败 {bar.stock_code}: {e}")

    def _sync_monitored_stocks(self):
        """同步监控股票列表 — 从已订阅ticker的股票获取"""
        try:
            sub_mgr = getattr(self.container, 'subscription_manager', None)
            if sub_mgr and hasattr(sub_mgr, 'ticker_subscribed_stocks'):
                subscribed = sub_mgr.ticker_subscribed_stocks
                if subscribed:
                    self._monitored = set(subscribed)
                    logger.info(f"[MomentumEngine] 从订阅列表同步: {len(self._monitored)} 只")
                    return

            db = self.container.db_manager
            today = datetime.now(HK_TZ).strftime('%Y-%m-%d')
            rows = db.execute_query(
                "SELECT DISTINCT stock_code FROM ticker_data WHERE trade_date=?",
                (today,)
            )
            if rows:
                self._monitored = {r[0] for r in rows}
                logger.info(f"[MomentumEngine] 从DB同步: {len(self._monitored)} 只")
        except Exception as e:
            logger.error(f"同步监控列表失败: {e}")

    def _daily_reset(self):
        today = datetime.now(HK_TZ).strftime('%Y-%m-%d')
        if self._last_daily_reset == today:
            return

        self.aggregator.reset_daily()
        self.bsr_monitor.reset_daily()
        self.delta_detector.reset_daily()
        self.velocity_detector.reset_daily()
        self.big_order_detector.reset_daily()
        self.vwap_detector.reset_daily()
        self.absorption_detector.reset_daily()
        self.resonance_detector.reset_daily()
        self._bars_processed = 0
        self._signals_emitted = 0
        self._resonance_count = 0
        self._last_daily_reset = today
        logger.info(f"[MomentumEngine] 每日重置: {today}")

    def _is_trading_time(self) -> bool:
        now = datetime.now(HK_TZ)
        t = (now.hour, now.minute)
        return (MORNING_START <= t < MORNING_END
                or AFTERNOON_START <= t < AFTERNOON_END)

    async def _maintenance_loop(self):
        while self._running:
            try:
                self._sync_monitored_stocks()
                self._daily_reset()
                logger.info(
                    f"[MomentumEngine] 监控={len(self._monitored)}只 "
                    f"bar={self._bars_processed} 信号={self._signals_emitted} "
                    f"共振={self._resonance_count}"
                )
            except Exception as e:
                logger.error(f"[MomentumEngine] 维护错误: {e}")
            await asyncio.sleep(1800)

    # ==================== API ====================

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "monitored_count": len(self._monitored),
            "bars_processed": self._bars_processed,
            "signals_emitted": self._signals_emitted,
            "resonance_count": self._resonance_count,
            "last_reset": self._last_daily_reset,
            "detectors": [
                "BSR", "Delta", "Velocity",
                "BigOrder", "VWAP", "Absorption", "Resonance"
            ],
        }

    def get_stock_momentum(self, stock_code: str) -> dict:
        return {
            "bsr": self.bsr_monitor.get_state(stock_code),
            "monitored": stock_code in self._monitored,
        }

    def get_all_states(self) -> dict:
        result = {}
        for code in self._monitored:
            state = self.bsr_monitor.get_state(code)
            if state.get("current_bsr") is not None:
                result[code] = state
        return result
