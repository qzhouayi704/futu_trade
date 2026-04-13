#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业微信群机器人告警服务

通过企业微信群机器人 Webhook 推送系统告警通知。
支持三级告警（紧急/警告/通知）、防抖去重、异步发送。
"""

import logging
import os
import time
from datetime import datetime
from enum import Enum
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """告警级别"""
    CRITICAL = "🔴 紧急"
    WARNING = "🟡 警告"
    INFO = "🟢 通知"


class WeChatAlertService:
    """
    企业微信群机器人告警服务

    功能：
    - 通过企业微信群机器人 Webhook 推送 Markdown 格式告警
    - 防抖去重：相同告警在冷却期内不重复发送
    - 异步 HTTP 调用，不阻塞主业务逻辑
    """

    WEBHOOK_API = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"

    def __init__(
        self,
        webhook_key: Optional[str] = None,
        cooldown_seconds: int = 300,
        enabled: bool = True,
    ):
        self.webhook_key = webhook_key or os.environ.get("WECHAT_WEBHOOK_KEY", "")
        self.enabled = enabled and bool(self.webhook_key)
        self._cooldown = cooldown_seconds
        self._sent_cache: dict[str, float] = {}
        self._session: Optional[aiohttp.ClientSession] = None

        if self.enabled:
            logger.info("企业微信群机器人告警服务已启用")
        else:
            logger.info("企业微信群机器人告警服务未启用（缺少 WECHAT_WEBHOOK_KEY）")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 HTTP 会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
        return self._session

    def _check_cooldown(self, cache_key: str) -> bool:
        """检查防抖冷却期，返回 True 表示可以发送"""
        now = time.time()
        if cache_key in self._sent_cache:
            elapsed = now - self._sent_cache[cache_key]
            if elapsed < self._cooldown:
                logger.debug(f"告警被防抖抑制: {cache_key} (剩余 {self._cooldown - elapsed:.0f}s)")
                return False
        self._sent_cache[cache_key] = now
        return True

    async def send(
        self,
        level: AlertLevel,
        title: str,
        content: str,
        dedup_key: Optional[str] = None,
    ) -> bool:
        """
        发送告警消息

        Args:
            level: 告警级别
            title: 告警标题
            content: 告警详情（支持企业微信 Markdown 子集）
            dedup_key: 去重键（为空则用 level+title）

        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False

        # 防抖检查
        cache_key = dedup_key or f"{level.name}:{title}"
        if not self._check_cooldown(cache_key):
            return False

        # 构建企业微信 Markdown 消息体
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        markdown_content = (
            f"## {level.value} {title}\n"
            f"{content}\n"
            f"> 时间：{timestamp}"
        )

        url = f"{self.WEBHOOK_API}?key={self.webhook_key}"
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": markdown_content,
            },
        }

        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("errcode") == 0:
                        logger.info(f"告警已发送: [{level.name}] {title}")
                        return True
                    else:
                        logger.error(f"企业微信 API 返回错误: {data}")
                else:
                    logger.error(f"企业微信 HTTP 错误: {resp.status}")
        except Exception as e:
            logger.error(f"企业微信告警发送异常: {e}")

        return False

    # ========== 便捷方法 ==========

    async def critical(self, title: str, content: str, dedup_key: Optional[str] = None):
        """发送紧急告警"""
        await self.send(AlertLevel.CRITICAL, title, content, dedup_key)

    async def warning(self, title: str, content: str, dedup_key: Optional[str] = None):
        """发送警告"""
        await self.send(AlertLevel.WARNING, title, content, dedup_key)

    async def info(self, title: str, content: str, dedup_key: Optional[str] = None):
        """发送通知"""
        await self.send(AlertLevel.INFO, title, content, dedup_key)

    # ========== 预定义告警场景 ==========

    async def alert_system_started(self):
        """系统启动成功"""
        await self.info("系统启动", "富途交易系统后端已成功启动，所有服务就绪。")

    async def alert_system_failed(self, error: str):
        """系统启动失败"""
        await self.critical("系统启动失败", f"后端启动异常：\n> {error}")

    async def alert_futu_disconnected(self, error: str):
        """FutuOpenD 断连"""
        await self.critical("FutuOpenD 断连", f"与 FutuOpenD 的连接已断开：\n> {error}")

    async def alert_trade_signal(self, stock_code: str, signal_type: str,
                                  price: float, reason: str):
        """交易信号触发"""
        color = "info" if signal_type == "BUY" else "warning"
        type_text = "买入" if signal_type == "BUY" else "卖出"
        await self.info(
            f"交易信号 - {stock_code}",
            f"- 类型：<font color=\"{color}\">**{type_text}**</font>\n"
            f"- 价格：**{price:.2f}**\n"
            f"- 原因：{reason}",
        )

    async def alert_trade_failed(self, stock_code: str, error: str):
        """交易执行失败"""
        await self.critical(
            f"交易执行失败 - {stock_code}",
            f"订单执行异常：\n> {error}",
        )

    async def alert_quote_interrupted(self):
        """行情推送中断"""
        await self.warning("行情推送中断", "实时行情推送服务已停止，请检查连接状态。")

    async def alert_risk_triggered(self, stock_code: str, rule: str):
        """风控规则触发"""
        await self.warning(
            f"风控触发 - {stock_code}",
            f"触发风控规则：**{rule}**",
        )

    # ========== 生命周期 ==========

    async def close(self):
        """关闭 HTTP 会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
