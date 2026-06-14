#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日板块成分股自动更新任务

每天收盘后强制从富途 API 重新拉取所有目标板块的成分股，
将新上市/新纳入的股票补进 stocks + stock_plates 表，使其能进入
监控池被订阅、扫描、产生信号。

背景：StockPoolService.add_plate / PlateManager.get_plate_stocks 走
"DB 优先"策略，板块一旦有成分股就不再请求 API，导致新股永远进不了池。
本任务绕过该缓存，直接走 API 重拉并增量入库（INSERT OR IGNORE，不删旧股）。

由 app.py lifespan 启动为后台 asyncio 任务，模式与 DailyKlineUpdater 一致。
"""

import asyncio
import logging
import time
from datetime import datetime

from ....utils.logger import print_status

logger = logging.getLogger("daily_plate_updater")


class DailyPlateUpdater:
    """每日板块成分股自动更新器"""

    # 触发时间：16:40（港股收盘后，且晚于每日K线 16:30，避开 API 争用高峰）
    TRIGGER_HOUR = 16
    TRIGGER_MINUTE = 40
    # 每个板块拉取后的间隔（秒），避免富途 API 限流
    REQUEST_DELAY = 1.5
    # 每个板块最多纳入的成分股数量（与 PlateStockManager.MAX_STOCKS_PER_PLATE 对齐）
    MAX_STOCKS_PER_PLATE = 50

    def __init__(self, container):
        self._container = container
        self._last_run_date: str = ""
        self._running = False

    async def start(self):
        """启动每日检查循环"""
        logger.info(
            f"[每日板块] 自动更新任务已启动，将在每日 "
            f"{self.TRIGGER_HOUR:02d}:{self.TRIGGER_MINUTE:02d} 执行"
        )

        while True:
            try:
                await self._check_and_run()
            except asyncio.CancelledError:
                logger.info("[每日板块] 任务已取消")
                break
            except Exception as e:
                logger.error(f"[每日板块] 检查循环异常: {e}")
            # 每 5 分钟检查一次触发条件
            await asyncio.sleep(300)

    async def _check_and_run(self):
        """检查是否到触发时间"""
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # 今天已执行过，跳过
        if today == self._last_run_date:
            return

        # 未到触发时间
        if now.hour < self.TRIGGER_HOUR:
            return
        if now.hour == self.TRIGGER_HOUR and now.minute < self.TRIGGER_MINUTE:
            return

        # 周末不执行（周六=5，周日=6）
        if now.weekday() >= 5:
            return

        success = await self._run_update()
        if success:
            self._last_run_date = today

    async def _run_update(self) -> bool:
        """执行板块成分股更新，返回是否成功执行"""
        if self._running:
            logger.warning("[每日板块] 上一次更新仍在运行，跳过")
            return False

        self._running = True
        start_time = time.time()

        try:
            plate_manager = getattr(self._container, 'plate_manager', None)
            db_manager = getattr(self._container, 'db_manager', None)
            if not plate_manager or not db_manager:
                logger.warning("[每日板块] plate_manager / db_manager 不可用，跳过")
                return False

            futu_client = getattr(plate_manager.stock_manager, 'futu_client', None)
            if not futu_client or not futu_client.is_available():
                logger.warning("[每日板块] 富途 API 不可用，跳过本次更新")
                return False

            # 获取所有目标板块
            result = plate_manager.get_target_plates(from_db=True)
            plates = result.get('plates', []) if result.get('success') else []
            if not plates:
                logger.info("[每日板块] 无目标板块，跳过")
                return False

            print_status(f"【每日板块】开始更新 {len(plates)} 个目标板块的成分股", "info")
            logger.info(f"[每日板块] 开始更新 {len(plates)} 个目标板块的成分股")

            loop = asyncio.get_running_loop()
            total_new_stocks = 0
            plate_ok = 0
            plate_fail = 0

            for plate in plates:
                plate_code = plate.get('plate_code') or plate.get('code')
                plate_id = plate.get('id')
                plate_name = plate.get('plate_name') or plate.get('name') or plate_code
                if not plate_code or plate_id is None:
                    continue

                try:
                    # 强制走 API 重新拉取成分股（绕过 DB 优先缓存）
                    stocks = await loop.run_in_executor(
                        None,
                        plate_manager.stock_manager._fetch_plate_stocks_from_api,
                        plate_code, self.MAX_STOCKS_PER_PLATE,
                    )
                    if not stocks:
                        logger.debug(f"[每日板块] {plate_name}({plate_code}) API 返回空，跳过")
                        plate_fail += 1
                        await asyncio.sleep(self.REQUEST_DELAY)
                        continue

                    new_count = await loop.run_in_executor(
                        None, self._upsert_plate_stocks, db_manager, stocks, plate_id
                    )
                    total_new_stocks += new_count
                    plate_ok += 1
                    if new_count > 0:
                        logger.info(
                            f"[每日板块] {plate_name}({plate_code}) 新增 {new_count} 只新股"
                        )
                except Exception as e:
                    plate_fail += 1
                    logger.warning(f"[每日板块] {plate_name}({plate_code}) 更新失败: {e}")

                # 板块间隔，避免 API 限流
                await asyncio.sleep(self.REQUEST_DELAY)

            elapsed = round(time.time() - start_time, 1)
            msg = (f"板块成功={plate_ok}, 失败={plate_fail}, "
                   f"新增股票={total_new_stocks}, 耗时={elapsed}s")
            print_status(f"【每日板块】完成 — {msg}", "ok")
            logger.info(f"[每日板块] 更新完成 — {msg}")
            return True

        except Exception as e:
            logger.error(f"[每日板块] 更新异常: {e}", exc_info=True)
            return False
        finally:
            self._running = False

    @staticmethod
    def _upsert_plate_stocks(db_manager, stocks: list, plate_id: int) -> int:
        """增量写入板块成分股，返回本次真正新增（此前不在库）的股票数。

        使用 INSERT OR IGNORE，不覆盖、不删除已有股票与关联。
        """
        new_count = 0
        for stock in stocks:
            code = stock.get('code')
            name = stock.get('name', '')
            market = stock.get('market', '')
            if not code:
                continue
            try:
                # 判断该股票此前是否已存在（用于统计真实新增数）
                existed = db_manager.execute_query(
                    'SELECT id FROM stocks WHERE code = ?', (code,)
                )
                if existed:
                    stock_id = existed[0][0]
                else:
                    db_manager.execute_update(
                        'INSERT OR IGNORE INTO stocks (code, name, market) VALUES (?, ?, ?)',
                        (code, name, market)
                    )
                    row = db_manager.execute_query(
                        'SELECT id FROM stocks WHERE code = ?', (code,)
                    )
                    if not row:
                        continue
                    stock_id = row[0][0]
                    new_count += 1

                # 补建板块关联（已存在则忽略）
                db_manager.execute_update(
                    'INSERT OR IGNORE INTO stock_plates (stock_id, plate_id) VALUES (?, ?)',
                    (stock_id, plate_id)
                )
            except Exception as e:
                logger.warning(f"[每日板块] 写入股票 {code} 失败: {e}")

        return new_count
