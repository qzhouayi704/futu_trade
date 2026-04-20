#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步行情推送服务 - 系统唯一的 Pipeline 驱动器

职责：
1. 系统启动时自动订阅目标股票
2. 管理推送循环的启动/停止生命周期
3. 驱动报价获取周期（run_quote_cycle）
4. 根据监控状态条件性驱动监控周期（run_monitoring_cycle）
5. 检测并处理市场切换
"""

import logging
import asyncio
from typing import Optional, Dict, Any, List

from ...utils.logger import print_status, get_flow_logger
from ...utils.market_helper import MarketTimeHelper


class AsyncQuotePusher:
    """异步行情推送服务 - 管理推送生命周期，处理逻辑委托给 QuotePipeline"""

    def __init__(self, container, socket_manager, state_manager, quote_pipeline):
        """初始化异步行情推送服务

        Args:
            container: 服务容器
            socket_manager: SocketManager实例（AsyncServer）
            state_manager: 状态管理器
            quote_pipeline: 统一行情处理管道
        """
        self.container = container
        self.socket_manager = socket_manager
        self.state_manager = state_manager
        self.quote_pipeline = quote_pipeline

        self.is_running = False
        self.push_task: Optional[asyncio.Task] = None
        self.push_interval = 5  # 推送间隔（秒）
        # 第一层防御：构造时即获取当前市场，避免首轮推送循环误判市场切换
        self.last_active_markets: List[str] = MarketTimeHelper.get_current_active_markets() or []
        self.first_quote_ready = asyncio.Event()  # 首次报价就绪事件

        # 从配置获取推送间隔
        if container.config:
            self.push_interval = getattr(container.config, 'quote_push_interval', 5)

    async def start(self) -> Dict[str, Any]:
        """启动行情推送服务

        Returns:
            启动结果
        """
        result = {
            'success': False,
            'message': '',
            'subscribed_count': 0
        }

        if self.is_running:
            result['message'] = '行情推送服务已在运行中'
            result['success'] = True
            result['subscribed_count'] = self.container.subscription_manager.subscribed_count
            return result

        # 检查富途API是否可用
        if not self.container.futu_client.is_available():
            result['message'] = '富途API不可用，行情推送服务启动失败'
            logging.warning(result['message'])
            return result

        try:
            flow = get_flow_logger("行情推送启动")

            # 检查是否已有订阅
            subscribed_count = self.container.subscription_manager.subscribed_count
            if subscribed_count > 0:
                flow.step("已有订阅", count=subscribed_count)
            else:
                # 没有订阅，通过 subscription_helper 订阅目标股票
                flow.step("开始订阅")
                from ...utils.market_helper import MarketTimeHelper
                current_markets = MarketTimeHelper.get_current_active_markets()
                if not current_markets:
                    current_markets = [MarketTimeHelper.get_primary_market()]

                loop = asyncio.get_running_loop()
                subscription_result = await loop.run_in_executor(
                    None,
                    self.container.subscription_helper.subscribe_target_stocks,
                    current_markets
                )

                if not subscription_result['success']:
                    flow.error("订阅失败", reason=subscription_result['message'])
                    result['message'] = f"股票订阅失败: {subscription_result['message']}"
                    flow.end(success=False)
                    return result

                subscribed_count = subscription_result.get('subscribed_count', 0)
                flow.step("订阅完成", count=subscribed_count,
                          markets=','.join(current_markets))

            # 启动推送任务
            self.is_running = True
            # 第二层防御：订阅完成后同步当前市场状态
            init_markets = MarketTimeHelper.get_current_active_markets()
            if init_markets:
                self.last_active_markets = init_markets
            self.push_task = asyncio.create_task(self._push_loop())

            result['success'] = True
            result['message'] = f"行情推送服务已启动，订阅 {subscribed_count} 只股票"
            result['subscribed_count'] = subscribed_count
            flow.end(success=True, subscribed=subscribed_count)

        except Exception as e:
            result['message'] = f"行情推送服务启动异常: {str(e)}"
            logging.error(result['message'], exc_info=True)

        return result

    async def stop(self):
        """停止行情推送服务"""
        if not self.is_running:
            return

        self.is_running = False

        if self.push_task and not self.push_task.done():
            self.push_task.cancel()
            try:
                await asyncio.gather(self.push_task, return_exceptions=True)
                logging.info("行情推送任务已成功取消")
            except asyncio.CancelledError:
                logging.info("行情推送任务已取消")
            except asyncio.TimeoutError:
                logging.warning("行情推送任务取消超时")
            except Exception as e:
                logging.error(f"停止行情推送任务时出错: {e}", exc_info=True)

        print_status("行情推送服务已停止", "info")


    async def _push_loop(self):
        """推送循环 - 报价获取 + 条件性监控"""
        print_status("【行情推送】推送循环开始", "info")

        first_quote_fetched = False
        first_quote_timeout = 60  # 60 秒超时
        start_time = asyncio.get_running_loop().time()
        consecutive_failures = 0  # 连续失败计数器

        while self.is_running:
            try:
                # 1. 始终执行报价获取周期
                quotes = await self.quote_pipeline.run_quote_cycle()

                # 首次报价成功后设置事件
                if not first_quote_fetched and quotes:
                    first_quote_fetched = True
                    self.first_quote_ready.set()
                    print_status("【行情推送】首次报价获取成功，通知 Scalping 引擎", "ok")

                # 检查首次报价超时
                if not first_quote_fetched:
                    elapsed = asyncio.get_running_loop().time() - start_time
                    if elapsed > first_quote_timeout:
                        logging.error(f"首次报价获取超时（{first_quote_timeout}秒），设置事件避免阻塞")
                        self.first_quote_ready.set()
                        first_quote_fetched = True  # 防止重复设置

                # 2. 仅在监控启动时执行监控周期
                if self.state_manager.is_running() and quotes:
                    try:
                        await self.quote_pipeline.run_monitoring_cycle(quotes)
                    except Exception as e:
                        logging.error(f"监控周期异常（不影响报价获取）: {e}", exc_info=True)

                # 3. 仅在监控运行时检查市场切换
                if self.state_manager.is_running():
                    await self._check_market_switch()

                # 成功时重置连续失败计数器
                consecutive_failures = 0
                await asyncio.sleep(self.push_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                backoff = min(self.push_interval * (2 ** consecutive_failures), 60)
                logging.error(
                    f"推送循环异常(连续{consecutive_failures}次): {e}",
                    exc_info=(consecutive_failures <= 3)
                )
                await asyncio.sleep(backoff)

        print_status("【行情推送】推送循环结束", "info")

    async def _check_market_switch(self):
        """检查并处理市场切换"""
        current_markets = MarketTimeHelper.get_current_active_markets()
        if not current_markets:
            current_markets = [MarketTimeHelper.get_primary_market()]

        # 第三层防御：空列表守卫，初始状态不触发切换
        if not self.last_active_markets:
            self.last_active_markets = current_markets
            return

        if set(current_markets) != set(self.last_active_markets):
            await self._handle_market_switch(current_markets)

    async def _handle_market_switch(self, current_markets: List[str]):
        """处理市场切换 - 重新订阅新市场股票（含重试和竞态保护）"""
        old_markets = self.last_active_markets
        print_status(
            f"【行情推送】市场切换: {old_markets} -> {current_markets}",
            "info"
        )

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.container.subscription_helper.unsubscribe_all
                )

                self.state_manager.invalidate_quotes_cache()
                self.state_manager.clear_trading_conditions()

                result = await asyncio.get_event_loop().run_in_executor(
                    None, self.container.subscription_helper.subscribe_target_stocks, current_markets
                )

                if result['success']:
                    # 订阅成功后才更新 last_active_markets
                    self.last_active_markets = current_markets
                    print_status(f"市场切换完成: {result.get('subscribed_count', 0)} 只股票已订阅", "ok")
                    return
                else:
                    logging.warning(
                        f"市场切换订阅失败(第{attempt}次): {result.get('message', '')}"
                    )
            except Exception as e:
                logging.error(f"市场切换异常(第{attempt}次): {e}")

            if attempt < max_retries:
                backoff = 2 ** attempt
                logging.info(f"市场切换重试，{backoff}秒后再试...")
                await asyncio.sleep(backoff)

        # 所有重试失败，不更新 last_active_markets，下次循环会重新尝试
        logging.error(
            f"市场切换失败（{max_retries}次重试均失败），"
            f"保留 last_active_markets={old_markets}"
        )

    def get_status(self) -> Dict[str, Any]:
        """获取行情推送服务状态

        Returns:
            服务状态信息
        """
        return {
            'is_running': self.is_running,
            'push_interval': self.push_interval,
            'subscribed_count': self.container.subscription_manager.subscribed_count,
            'subscribed_stocks': list(self.container.subscription_manager.subscribed_stocks)[:10],
            'task_alive': self.push_task and not self.push_task.done() if self.push_task else False
        }
