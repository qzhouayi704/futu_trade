#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scalping 引擎自动启动模块

负责在系统启动后自动启动 Scalping 引擎，包括：
1. 等待行情推送服务完成首次报价
2. 等待报价缓存就绪
3. 构建活跃个股列表
4. 启动 ScalpingEngine

拆分自 app.py
"""

import asyncio
import logging

from ...core.container.service_container import ServiceContainer


def build_stock_list_for_scalping(
    cached_quotes: list[dict],
    stock_limit: int,
    min_price_map: dict[str, float],
) -> tuple[list[str], dict[str, float]]:
    """从报价缓存构建 Scalping 引擎的活跃个股列表

    纯函数，无副作用。按换手率降序排序，过滤低价股，取前 stock_limit 只。

    Args:
        cached_quotes: 报价数据列表，每个 dict 包含 code, turnover_rate, last_price 等字段
        stock_limit: 返回的最大股票数量
        min_price_map: 市场 -> 最低价格映射，如 {"HK": 1.0, "US": 0}

    Returns:
        (stock_codes, turnover_rates) 元组
        - stock_codes: 按换手率降序排列的股票代码列表
        - turnover_rates: {code: turnover_rate} 字典
    """
    filtered: list[dict] = []
    for q in cached_quotes:
        code = q.get("code", "")
        last_price = q.get("last_price", 0)
        turnover_rate = q.get("turnover_rate", 0)

        if not code or turnover_rate <= 0:
            continue

        # 检测市场并获取最低价格阈值
        min_price = 0.0
        for prefix, price in min_price_map.items():
            if code.startswith(f"{prefix}."):
                min_price = price
                break

        # 过滤低价股：last_price > 0 且 last_price >= min_price
        if last_price > 0 and last_price < min_price:
            continue

        filtered.append(q)

    # 按换手率降序排序
    filtered.sort(key=lambda x: x.get("turnover_rate", 0), reverse=True)

    # 取前 stock_limit 只
    top = filtered[:stock_limit]

    stock_codes = [q["code"] for q in top]
    turnover_rates = {q["code"]: q.get("turnover_rate", 0) for q in top}

    return stock_codes, turnover_rates


async def auto_start_scalping(
    container: ServiceContainer,
    state_manager,
    quote_pusher,
    socket_manager=None,
) -> None:
    """后台自动启动 Scalping 引擎

    等待行情推送服务完成首次报价，然后构建活跃个股列表并启动 ScalpingEngine。
    """
    PUSHER_WAIT_TIMEOUT = 300  # 等待行情推送服务启动的超时时间（5分钟）
    CACHE_WAIT_TIMEOUT = 30    # 等待缓存就绪的超时时间（缩短到30秒）
    CACHE_POLL_INTERVAL = 2
    # 不再硬编码上限，使用全部订阅股票（引擎自身有 MAX_STOCKS 上限保护）

    # 1. 等待 AsyncQuotePusher 完成首次报价
    logging.info("Scalping 自动启动：等待行情推送服务完成首次报价...")
    try:
        await asyncio.wait_for(
            quote_pusher.first_quote_ready.wait(),
            timeout=PUSHER_WAIT_TIMEOUT
        )
        logging.info("Scalping 自动启动：行情推送服务首次报价已完成")
    except asyncio.TimeoutError:
        logging.warning(
            f"Scalping 自动启动：等待行情推送服务超时（{PUSHER_WAIT_TIMEOUT}秒），放弃启动"
        )
        return

    # 2. 轮询等待缓存就绪（缩短超时时间，因为首次报价已完成）
    elapsed = 0.0
    while elapsed < CACHE_WAIT_TIMEOUT:
        if state_manager.is_quotes_cache_valid():
            break
        await asyncio.sleep(CACHE_POLL_INTERVAL)
        elapsed += CACHE_POLL_INTERVAL
    else:
        logging.warning(
            f"Scalping 自动启动：报价缓存超时未就绪（{CACHE_WAIT_TIMEOUT}秒），放弃启动"
        )
        return

    # 3. 获取缓存数据
    cached_quotes = state_manager.get_cached_quotes()
    if not cached_quotes:
        logging.warning("Scalping 自动启动：报价缓存为空，放弃启动")
        return

    # 4. 检查引擎是否可用
    scalping_engine = container.scalping_engine
    if scalping_engine is None:
        logging.warning("Scalping 自动启动：ScalpingEngine 未初始化，跳过")
        return

    # 5. 构建股票列表
    min_price_map = getattr(container.config, "min_stock_price", None) or {
        "HK": 1.0, "US": 0
    }
    stock_codes, turnover_rates = build_stock_list_for_scalping(
        cached_quotes, len(cached_quotes), min_price_map
    )

    if not stock_codes:
        logging.info("Scalping 自动启动：筛选后无有效股票")
        return

    # 6. 进程模式：确保 spawn 在 start 之前完成（消除竞态）
    from .scalping_process_manager import ScalpingProcessManager
    if isinstance(scalping_engine, ScalpingProcessManager):
        try:
            await scalping_engine.spawn(socket_manager)
            logging.info("Scalping 自动启动：子进程 spawn 完成")
        except Exception as e:
            logging.error(f"Scalping 子进程 spawn 失败: {e}", exc_info=True)
            return

    # 7. 启动引擎
    try:
        result = await scalping_engine.start(stock_codes, turnover_rates)
        logging.info(
            f"Scalping 自动启动完成：新增 {len(result.added)} 只，"
            f"已存在 {len(result.existing)} 只，过滤 {len(result.filtered)} 只"
        )
    except Exception as e:
        logging.error(f"Scalping 自动启动失败: {e}", exc_info=True)
