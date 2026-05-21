#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动量引擎 (MomentumEngine)

实时监听逐笔成交数据，通过BSR和Delta分析产出买卖信号。

架构:
  Ticker推送 → TickerAggregator(1分钟聚合) → BSRMonitor + DeltaDetector → SignalPublisher
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Set

from .ticker_aggregator import TickerAggregator, AggregatedBar
from .bsr_monitor import BSRMonitor, MomentumSignal
from .delta_detector import DeltaDetector, DeltaSignal
from .signal_publisher import SignalPublisher

logger = logging.getLogger(__name__)

# 港股交易时间 (HKT = UTC+8)
HK_TZ = timezone(timedelta(hours=8))
MORNING_START = (9, 30)
MORNING_END = (12, 0)
AFTERNOON_START = (13, 0)
AFTERNOON_END = (16, 0)


class MomentumEngine:
    """
    动量引擎 — 实时监听逐笔数据，检测买卖动量信号

    Usage:
        engine = MomentumEngine(container)
        await engine.start()

    集成方式:
        在 app.py lifespan 中启动，注册到 ScalpingEngine 的 ticker 回调
    """

    def __init__(self, container):
        self.container = container

        # 核心组件
        self.aggregator = TickerAggregator()
        self.bsr_monitor = BSRMonitor()
        self.delta_detector = DeltaDetector()
        self.publisher = SignalPublisher(container)

        # 监控的股票集合
        self._monitored: Set[str] = set()

        # 运行状态
        self._running = False
        self._bars_processed = 0
        self._signals_emitted = 0
        self._last_daily_reset: Optional[str] = None

    async def start(self):
        """启动动量引擎"""
        self._running = True
        self._sync_monitored_stocks()
        self._daily_reset()

        logger.info(
            f"[MomentumEngine] 启动成功，监控 {len(self._monitored)} 只股票"
        )

        # 启动后台维护任务
        asyncio.create_task(self._maintenance_loop())

    async def stop(self):
        """停止动量引擎"""
        self._running = False
        logger.info("[MomentumEngine] 已停止")

    def on_ticker(self, stock_code: str, ticker_data: dict):
        """
        逐笔数据回调入口（同步，由Scalping/QuotePipeline调用）

        ticker_data 格式:
        {
            'price': float,
            'volume': int,
            'turnover': float,
            'ticker_direction': str,  # 'BUY'/'SELL'/'NEUTRAL'
            'timestamp': int (ms),    # 或 'time' str
        }
        """
        if not self._running:
            return

        if stock_code not in self._monitored:
            return

        # 检查交易时间
        if not self._is_trading_time():
            return

        # 提取字段
        price = ticker_data.get('price', 0)
        volume = ticker_data.get('volume', 0)
        turnover = ticker_data.get('turnover', 0)
        direction = ticker_data.get('ticker_direction',
                    ticker_data.get('direction', 'NEUTRAL'))
        timestamp_ms = ticker_data.get('timestamp', int(time.time() * 1000))

        if not price or not volume:
            return

        # 送入聚合器
        completed_bar = self.aggregator.on_tick(
            stock_code, price, volume, turnover, direction, timestamp_ms
        )

        # 如果有完成的bar，进行信号分析
        if completed_bar:
            # 使用 fire-and-forget 方式处理（避免阻塞ticker回调）
            asyncio.get_event_loop().create_task(
                self._process_bar(completed_bar)
            )

    async def _process_bar(self, bar: AggregatedBar):
        """处理完成的1分钟bar"""
        self._bars_processed += 1

        try:
            # BSR 分析
            bsr_signal = self.bsr_monitor.update(bar)
            if bsr_signal:
                self._signals_emitted += 1
                await self.publisher.publish(bsr_signal)

            # Delta 分析
            delta_signal = self.delta_detector.update(bar)
            if delta_signal:
                self._signals_emitted += 1
                await self.publisher.publish(delta_signal)

        except Exception as e:
            logger.error(f"[MomentumEngine] 处理bar失败 {bar.stock_code}: {e}")

    def _sync_monitored_stocks(self):
        """同步监控股票列表"""
        try:
            db = self.container.db_manager
            # 获取目标股票池（所有订阅了ticker的股票）
            rows = db.execute_query(
                "SELECT code FROM stocks WHERE stock_priority > 0"
            )
            if rows:
                self._monitored = {r[0] for r in rows}
                logger.info(
                    f"[MomentumEngine] 同步监控列表: {len(self._monitored)} 只"
                )
        except Exception as e:
            logger.error(f"同步监控列表失败: {e}")

    def _daily_reset(self):
        """每日重置（开盘前）"""
        today = datetime.now(HK_TZ).strftime('%Y-%m-%d')
        if self._last_daily_reset == today:
            return

        self.aggregator.reset_daily()
        self.bsr_monitor.reset_daily()
        self.delta_detector.reset_daily()
        self._bars_processed = 0
        self._signals_emitted = 0
        self._last_daily_reset = today
        logger.info(f"[MomentumEngine] 每日重置: {today}")

    def _is_trading_time(self) -> bool:
        """检查是否在港股交易时间"""
        now = datetime.now(HK_TZ)
        h, m = now.hour, now.minute
        t = (h, m)
        return (MORNING_START <= t < MORNING_END
                or AFTERNOON_START <= t < AFTERNOON_END)

    async def _maintenance_loop(self):
        """后台维护循环"""
        while self._running:
            try:
                # 每30分钟同步一次监控列表
                self._sync_monitored_stocks()
                self._daily_reset()

                logger.info(
                    f"[MomentumEngine] 状态: "
                    f"监控={len(self._monitored)}只 "
                    f"已处理={self._bars_processed}bar "
                    f"信号={self._signals_emitted}个"
                )
            except Exception as e:
                logger.error(f"[MomentumEngine] 维护循环错误: {e}")

            await asyncio.sleep(1800)  # 30分钟

    # ==================== API 查询接口 ====================

    def get_status(self) -> dict:
        """获取引擎状态"""
        return {
            "running": self._running,
            "monitored_count": len(self._monitored),
            "bars_processed": self._bars_processed,
            "signals_emitted": self._signals_emitted,
            "last_reset": self._last_daily_reset,
        }

    def get_stock_momentum(self, stock_code: str) -> dict:
        """获取单只股票的动量状态"""
        return {
            "bsr": self.bsr_monitor.get_state(stock_code),
            "monitored": stock_code in self._monitored,
        }

    def get_all_states(self) -> dict:
        """获取所有监控股票的动量状态"""
        result = {}
        for code in self._monitored:
            state = self.bsr_monitor.get_state(code)
            if state.get("current_bsr") is not None:
                result[code] = state
        return result
