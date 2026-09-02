#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日K线自动更新任务

收盘后自动更新所有已订阅股票的K线数据，确保次日分析使用最新数据。
由 app.py lifespan 启动为后台 asyncio 任务。
"""

import asyncio
import logging
import time
from datetime import datetime

from ....utils.market_helper import MarketTimeHelper
from ....utils.logger import print_status
from . import akshare_kline_fetcher

logger = logging.getLogger("daily_kline_updater")


class DailyKlineUpdater:
    """每日K线自动更新器"""

    # 触发时间：16:30（港股收盘后30分钟，确保当日K线已完结）
    TRIGGER_HOUR = 16
    TRIGGER_MINUTE = 30
    # 每只股票下载间隔（秒），避免 API 限流
    REQUEST_DELAY = 3.0
    # 下载天数
    DOWNLOAD_DAYS = 30

    def __init__(self, container):
        self._container = container
        self._last_run_date: str = ""
        self._running = False

    async def start(self):
        """启动每日检查循环"""
        logger.info("[每日K线] 自动更新任务已启动，将在每日 16:30 执行")

        # 等待订阅就绪（最多等60秒）
        for _ in range(12):
            sub_mgr = getattr(self._container, 'subscription_manager', None)
            if sub_mgr and sub_mgr.subscribed_count >= 10:
                logger.info(f"[每日K线] 订阅已就绪: {sub_mgr.subscribed_count} 只股票")
                break
            await asyncio.sleep(5)

        while True:
            try:
                await self._check_and_run()
            except asyncio.CancelledError:
                logger.info("[每日K线] 任务已取消")
                break
            except Exception as e:
                logger.error(f"[每日K线] 检查循环异常: {e}")
            # 每 5 分钟检查一次
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

        # 执行更新
        success = await self._run_update()
        if success:
            self._last_run_date = today
            # K线更新完成后，自动触发盘后优选评分
            await self._auto_run_overnight_screen()
            # 盘后优选完成后，生成持仓操作建议
            await self._auto_run_position_advice()

    async def _run_update(self) -> bool:
        """执行K线更新，返回是否成功执行"""
        if self._running:
            logger.warning("[每日K线] 上一次更新仍在运行，跳过")
            return False

        self._running = True
        start_time = time.time()

        try:
            kline_service = getattr(self._container, 'kline_service', None)
            if not kline_service:
                logger.warning("[每日K线] kline_service 不可用，跳过")
                return False

            # 获取需要更新的股票列表
            stock_codes = self._get_target_codes()
            if not stock_codes:
                logger.info("[每日K线] 无目标股票，跳过")
                return False

            # 获取已占用K线额度的股票集合（额度耗尽后仍可下载）
            subscribed_stocks = set()
            try:
                quota_detail = kline_service.futu_client.get_kline_quota_detail()
                if quota_detail.get('success'):
                    subscribed_stocks = quota_detail.get('kline_stocks', set())
                    logger.info(f"[每日K线] 已订阅K线额度的股票: {len(subscribed_stocks)} 只")
            except Exception:
                pass

            print_status(f"【每日K线】开始更新 {len(stock_codes)} 只股票", "info")
            logger.info(f"[每日K线] 开始更新 {len(stock_codes)} 只股票的K线数据")

            updated = 0
            skipped = 0
            failed = 0
            skipped_by_quota = 0
            akshare_count = 0
            futu_count = 0
            quota_exhausted = False
            loop = asyncio.get_running_loop()

            # 检查 AkShare 是否可用
            use_akshare = akshare_kline_fetcher.is_available()
            if use_akshare:
                print_status("【每日K线】AkShare 数据源可用，优先使用免费数据源", "info")
            else:
                print_status("【每日K线】AkShare 不可用，使用富途API（建议安装: pip install akshare）", "warn")

            for i, code in enumerate(stock_codes):
                try:
                    # 额度受限模式：跳过未订阅的股票
                    if quota_exhausted and code not in subscribed_stocks:
                        skipped_by_quota += 1
                        continue

                    # 检查今天的K线是否已入库
                    has_today = await loop.run_in_executor(
                        None, self._has_today_kline, kline_service, code
                    )
                    if has_today:
                        skipped += 1
                        continue

                    # 策略：优先 AkShare，失败则 fallback 到富途
                    kline_data = None
                    source = "unknown"

                    if use_akshare:
                        try:
                            kline_data = await loop.run_in_executor(
                                None,
                                akshare_kline_fetcher.fetch_daily_kline,
                                code, self.DOWNLOAD_DAYS, "qfq"
                            )
                            if kline_data:
                                source = "akshare"
                                akshare_count += 1
                        except Exception as e:
                            logger.debug(f"[每日K线] AkShare {code} 失败: {e}")

                    # AkShare 失败，fallback 到富途 API
                    if not kline_data:
                        if quota_exhausted and code not in subscribed_stocks:
                            skipped_by_quota += 1
                            continue
                        kline_data = await loop.run_in_executor(
                            None,
                            kline_service.fetcher.fetch_kline_data_with_limit,
                            code, self.DOWNLOAD_DAYS, self.DOWNLOAD_DAYS
                        )
                        if kline_data:
                            source = "futu"
                            futu_count += 1

                    if kline_data:
                        # 收盘后执行，当天K线已完整，无需过滤
                        saved = kline_service.storage.save_kline_batch(code, kline_data)
                        if saved > 0:
                            updated += 1
                        else:
                            failed += 1
                    else:
                        failed += 1

                    # 每10只股票记录一次进度
                    if (i + 1) % 10 == 0:
                        msg = (f"【每日K线】进度 {i+1}/{len(stock_codes)}: "
                               f"更新={updated} 跳过={skipped} 失败={failed}"
                               f" AkShare={akshare_count} 富途={futu_count}"
                               f"{f' 额度跳过={skipped_by_quota}' if skipped_by_quota else ''}")
                        print_status(msg, "info")
                        logger.info(f"[每日K线] {msg}")

                    # 请求间隔（AkShare 需要更短延迟）
                    await asyncio.sleep(0.5 if source == "akshare" else self.REQUEST_DELAY)

                except Exception as e:
                    failed += 1
                    error_msg = str(e).lower()
                    # 额度耗尽：进入受限模式，跳过未订阅股票，继续已订阅股票
                    if any(kw in error_msg for kw in ['quota', '额度', 'limit exceeded']):
                        if not quota_exhausted:
                            quota_exhausted = True
                            logger.warning(
                                f"[每日K线] API额度耗尽，进入受限模式。"
                                f"已订阅 {len(subscribed_stocks)} 只股票可继续下载"
                            )
                            if not subscribed_stocks:
                                logger.warning("[每日K线] 无已订阅股票，终止更新")
                                break
                    else:
                        logger.debug(f"[每日K线] {code} 更新失败: {e}")

            elapsed = round(time.time() - start_time, 1)
            msg = (f"总计={len(stock_codes)}, 更新={updated}, 跳过={skipped}, "
                   f"失败={failed}, AkShare={akshare_count}, 富途={futu_count}, "
                   f"额度跳过={skipped_by_quota}, 耗时={elapsed}s")
            print_status(f"【每日K线】完成 — {msg}", "ok")
            logger.info(f"[每日K线] 更新完成 — {msg}")
            return True

        except Exception as e:
            logger.error(f"[每日K线] 更新异常: {e}", exc_info=True)
            return False
        finally:
            self._running = False

    async def _auto_run_overnight_screen(self):
        """K线更新完成后自动触发盘后优选评分"""
        try:
            from ....routers.data.overnight import auto_trigger_screen
            logger.info("[每日K线] K线更新完成，自动触发盘后优选评分")
            await auto_trigger_screen(self._container)
            logger.info("[每日K线] 盘后优选评分已完成")
        except Exception as e:
            logger.error(f"[每日K线] 自动触发盘后优选失败: {e}", exc_info=True)

    async def _auto_run_position_advice(self):
        """盘后生成持仓操作建议"""
        try:
            trade_svc = getattr(self._container, 'futu_trade_service', None)
            if not trade_svc:
                logger.warning("[每日K线] 交易服务不可用，跳过持仓建议")
                return

            result = trade_svc.get_positions()
            if not result.get('success') or not result.get('positions'):
                logger.info("[每日K线] 无持仓数据，跳过持仓建议")
                return

            from ...analysis.position_advisor import PositionAdvisor
            advisor = PositionAdvisor(self._container.db_manager, self._container)
            advices = await advisor.generate_all_advice(result['positions'])

            if advices:
                await advisor.push_wechat_alerts(advices)
                logger.info(f"[每日K线] 持仓操作建议已生成: {len(advices)} 只")
            else:
                logger.info("[每日K线] 持仓建议生成为空")

        except Exception as e:
            logger.error(f"[每日K线] 持仓建议生成失败: {e}", exc_info=True)

    @staticmethod
    def _has_today_kline(kline_service, stock_code: str) -> bool:
        """检查今天的K线是否已入库"""
        try:
            market = MarketTimeHelper.get_market_from_code(stock_code)
            today_str = MarketTimeHelper.get_market_today(market)
            result = kline_service.db_manager.execute_query(
                "SELECT 1 FROM kline_data WHERE stock_code = ? AND time_key >= ?",
                (stock_code, today_str)
            )
            return bool(result)
        except Exception:
            return False

    def _get_target_codes(self) -> list:
        """获取需要更新K线的股票代码列表

        数据来源：市场扫描已订阅股票 + 持仓 + 市场扫描报价快照
        """
        codes = set()
        priority_codes = set()

        # 市场扫描中的已订阅股票
        sub_mgr = getattr(self._container, 'subscription_manager', None)
        if sub_mgr:
            subscribed = sub_mgr.subscribed_stocks
            codes.update(subscribed)
            logger.info(f"[每日K线] 市场扫描已订阅 {len(subscribed)} 只股票")

        # 持仓股票
        try:
            trade_svc = getattr(self._container, 'futu_trade_service', None)
            if trade_svc:
                result = trade_svc.get_positions()
                if result.get('success'):
                    for pos in result.get('positions', []):
                        if pos.get('qty', 0) > 0:
                            stock_code = pos['stock_code']
                            codes.add(stock_code)
                            priority_codes.add(stock_code)
        except Exception:
            pass

        # 当天 V2 候选是复盘和次日跟踪的核心样本，必须先于全市场扩展池更新。
        try:
            db_mgr = getattr(self._container, 'db_manager', None)
            if db_mgr:
                today = datetime.now().strftime("%Y-%m-%d")
                rows = db_mgr.execute_query(
                    "SELECT DISTINCT stock_code FROM v2_decision_events "
                    "WHERE substr(exchange_time,1,10)=? "
                    "AND event_type IN "
                    "('CANDIDATE_ENTERED','CANDIDATE_UPDATED','BUY_CONFIRMED') "
                    "AND new_state IN ('SETUP','WATCHING','CONFIRMED')",
                    (today,),
                )
                candidate_codes = {str(row[0]) for row in rows if row[0]}
                codes.update(candidate_codes)
                priority_codes.update(candidate_codes)
                if candidate_codes:
                    logger.info(
                        f"[每日K线] 优先更新当天 V2 候选 {len(candidate_codes)} 只"
                    )
        except Exception as e:
            logger.warning(f"[每日K线] 读取当天 V2 候选失败: {e}")

        # 市场扫描报价快照中的股票（确保盘后优选的评分池全覆盖）
        try:
            state_mgr = getattr(self._container, 'state_manager', None)
            if state_mgr:
                last_quotes = state_mgr.quote_cache.get_last_quotes()
                if last_quotes:
                    quote_codes = {q.get('code', q.get('stock_code', '')) for q in last_quotes if q.get('code') or q.get('stock_code')}
                    added = quote_codes - codes
                    codes.update(quote_codes)
                    if added:
                        logger.info(f"[每日K线] 报价快照补充 {len(added)} 只股票")
        except Exception:
            pass

        # === 方案一：全市场快照预筛（放量突破候选股） ===
        try:
            db_mgr = getattr(self._container, 'db_manager', None)
            futu_client = getattr(self._container, 'futu_client', None)
            if db_mgr and futu_client:
                # 1. 获取库中所有股票
                rows = db_mgr.execute_query("SELECT code FROM stocks WHERE market IN ('HK', 'US', 'SH', 'SZ')")
                all_codes = [r[0] for r in rows if r[0]]
                # 2. 找出未在待下载列表中的股票
                untracked = [c for c in all_codes if c not in codes]
                
                if untracked:
                    logger.info(f"[每日K线] 开始通过快照预筛 {len(untracked)} 只全市场股票...")
                    filtered_add = []
                    batch_size = 400
                    for i in range(0, len(untracked), batch_size):
                        batch = untracked[i:i + batch_size]
                        ret, data = futu_client.get_market_snapshot(batch)
                        if ret == 0 and data is not None and not data.empty:
                            for _, row in data.iterrows():
                                code = row.get('code')
                                change = row.get('change_rate', 0)
                                vr = row.get('volume_ratio', 0)
                                # 突破潜质初筛条件：涨幅 > 5% 且 量比 > 2
                                if change > 5.0 and vr > 2.0:
                                    filtered_add.append(code)
                        time.sleep(0.5)  # 防止快照限频
                        
                    if filtered_add:
                        logger.info(f"[每日K线] 快照预筛发现 {len(filtered_add)} 只潜在突破股，加入K线更新队列")
                        codes.update(filtered_add)
        except Exception as e:
            logger.error(f"[每日K线] 快照预筛异常: {e}", exc_info=True)

        # 冷启动保护：订阅还未重建完成时跳过，等下一个周期
        if len(codes) < 3:
            logger.warning(
                f"[每日K线] 目标股票仅 {len(codes)} 只，"
                f"可能订阅尚未重建，等待下一周期"
            )
            return []

        return self._sort_target_codes(codes, priority_codes)

    @staticmethod
    def _sort_target_codes(codes: set, priority_codes: set) -> list:
        market_rank = {"HK": 0, "SH": 1, "SZ": 1, "US": 2}

        def sort_key(code: str) -> tuple:
            market = str(code).split(".", 1)[0]
            return (
                0 if code in priority_codes else 1,
                market_rank.get(market, 3),
                str(code),
            )

        return sorted(codes, key=sort_key)
