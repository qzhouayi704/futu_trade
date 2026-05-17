#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
活跃度重新筛选路由

提供手动触发活跃度重新筛选的 API 端点。
筛选在后台线程中异步执行，通过 WebSocket 推送进度和结果。
"""

import asyncio
import logging
import threading
from datetime import date, datetime
from typing import Dict, List, Any

from fastapi import APIRouter, Depends

from ...core import get_state_manager
from ...core.exceptions import BusinessError
from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...websocket.socket_manager import get_socket_manager

router = APIRouter(prefix="/api/stocks", tags=["活跃度筛选"])
logger = logging.getLogger(__name__)

# 筛选状态锁，防止重复触发
_refilter_lock = threading.Lock()
_is_refiltering = False


def trigger_refilter_async(container):
    """触发异步重新筛选（供其他模块调用）

    Args:
        container: 服务容器

    Returns:
        bool: 是否成功启动筛选任务
    """
    global _is_refiltering

    if _is_refiltering:
        logger.warning("筛选正在进行中，跳过本次触发")
        return False

    try:
        stocks_to_check = _get_stocks_to_recheck(container)

        if not stocks_to_check:
            logger.info("没有需要重新检查的股票")
            return False

        # 启动后台线程执行筛选
        _is_refiltering = True
        thread = threading.Thread(
            target=_run_refilter_in_thread,
            args=(stocks_to_check, container),
            daemon=True,
            name="refilter-activity-async"
        )
        thread.start()

        logger.info(f"已启动异步筛选任务，待检查股票数: {len(stocks_to_check)}")
        return True

    except Exception as e:
        logger.error(f"启动异步筛选失败: {e}", exc_info=True)
        _is_refiltering = False
        return False


@router.post("/refilter-activity")
async def refilter_activity(container=Depends(get_container)):
    """触发重新筛选活跃度（异步执行）

    1. 从数据库获取当前市场的未检查/检查失败股票
    2. 在后台线程中执行活跃度筛选
    3. 通过 WebSocket 推送进度和完成事件

    Returns:
        {success: true, message: "筛选已启动", data: {total_unchecked: N}}
    """
    global _is_refiltering

    if _is_refiltering:
        return APIResponse.ok(
            data={"total_unchecked": 0},
            message="筛选正在进行中，请稍后再试"
        )

    try:
        # 先清空当天的活跃度记录，确保所有股票（包括之前判定为低活跃的）都重新筛选
        today = date.today().strftime('%Y-%m-%d')
        cleared_count = container.db_manager.stock_activity_queries.clear_daily_activity_records(today)
        logger.info(f"已清空当天 {cleared_count} 条活跃度记录，准备重新筛选")

        stocks_to_check = _get_stocks_to_recheck(container)

        if not stocks_to_check:
            return APIResponse.ok(
                data={"total_unchecked": 0, "cleared_count": cleared_count},
                message="股票池为空，无需筛选"
            )

        # 启动后台线程执行筛选
        _is_refiltering = True
        thread = threading.Thread(
            target=_run_refilter_in_thread,
            args=(stocks_to_check, container),
            daemon=True,
            name="refilter-activity"
        )
        thread.start()

        return APIResponse.ok(
            data={"total_unchecked": len(stocks_to_check), "cleared_count": cleared_count},
            message=f"已清空 {cleared_count} 条记录，开始重新筛选 {len(stocks_to_check)} 只股票"
        )

    except Exception as e:
        logger.error(f"启动活跃度重新筛选失败: {e}", exc_info=True)
        raise BusinessError(message=f"启动筛选失败: {str(e)}")


def _get_stocks_to_recheck(container) -> List[Dict[str, Any]]:
    """获取需要重新检查的股票列表（未检查 + 检查失败）

    重新筛选活跃度时，应该对股票池中的所有股票进行筛选，
    而不仅仅是已订阅的股票，这样才能发现新的活跃股票。
    跳过市场限制为 0 的市场（如 US），避免浪费 API 额度。
    """
    today = date.today().strftime('%Y-%m-%d')

    # 获取已检查的股票
    checked_stocks = container.db_manager.stock_activity_queries.get_daily_checked_stocks(today)

    # 获取股票池中的所有股票（而不是已订阅的股票）
    state = get_state_manager()
    pool_data = state.get_stock_pool()
    target_stocks = pool_data.get('stocks', [])

    if not target_stocks:
        logger.warning("股票池为空，无法进行活跃度筛选")
        return []

    # 读取市场限制配置，跳过限制为 0 的市场
    market_limits = getattr(container.config, 'monitor_stocks_limit_by_market', None) or {'HK': 100, 'US': 0}
    skip_markets = {m for m, limit in market_limits.items() if limit == 0}
    if skip_markets:
        logger.info(f"跳过市场限制为0的市场: {skip_markets}")

    # 筛选未检查和检查失败的股票
    stocks_to_check = []
    skipped_market_count = 0
    for stock in target_stocks:
        code = stock.get('code', '')
        if not code:
            continue

        # 跳过限制为 0 的市场
        market = stock.get('market', '') or ('US' if code.startswith('US.') else 'HK' if code.startswith('HK.') else '')
        if market in skip_markets:
            skipped_market_count += 1
            continue

        if code not in checked_stocks:
            # 未检查的股票
            stocks_to_check.append(stock)
        elif checked_stocks[code].get('activity_score') == -1:
            # 检查失败的股票（activity_score == -1）
            stocks_to_check.append(stock)

    if skipped_market_count > 0:
        logger.info(f"已跳过 {skipped_market_count} 只市场限制为0的股票")

    return stocks_to_check


def _run_refilter_in_thread(
    stocks_to_check: List[Dict[str, Any]],
    container
):
    """在后台线程中执行重新筛选"""
    global _is_refiltering
    loop = asyncio.new_event_loop()

    try:
        loop.run_until_complete(
            _execute_refilter(stocks_to_check, container)
        )
    except Exception as e:
        logger.error(f"后台筛选线程异常: {e}", exc_info=True)
        loop.run_until_complete(_emit_error(str(e)))
    finally:
        _is_refiltering = False
        loop.close()


async def _emit_progress(
    batch_num: int, total_batches: int,
    checked_count: int, active_count: int,
    phase: str = "filtering"
):
    """推送筛选进度事件"""
    socket_manager = get_socket_manager()
    await socket_manager.emit_to_all("refilter_progress", {
        "phase": phase,
        "batch_num": batch_num,
        "total_batches": total_batches,
        "checked_count": checked_count,
        "active_count": active_count,
    })


async def _emit_complete(
    total: int, active: int, inactive: int, failed: int
):
    """推送筛选完成事件"""
    socket_manager = get_socket_manager()
    await socket_manager.emit_to_all("refilter_complete", {
        "success": True,
        "total": total,
        "active": active,
        "inactive": inactive,
        "failed": failed,
        "message": f"筛选完成: 共{total}只, 活跃{active}只, 不活跃{inactive}只, 失败{failed}只",
    })


async def _emit_error(message: str):
    """推送筛选错误事件"""
    socket_manager = get_socket_manager()
    await socket_manager.emit_to_all("refilter_error", {
        "message": message,
    })


async def _execute_refilter(
    stocks_to_check: List[Dict[str, Any]],
    container
):
    """执行活跃度重新筛选的核心逻辑"""
    from ...services.market_data.activity_filter import ActivityFilterService
    from ...services.market_data.hot_stock.hot_stock_query_service import HotStockQueryService

    # 创建 ActivityFilterService 实例
    activity_filter = ActivityFilterService(
        subscription_manager=container.subscription_manager,
        quote_service=container.quote_service,
        config=container.config,
        db_manager=container.db_manager,
        container=container,
    )

    # 获取活跃度筛选配置
    activity_config = _get_activity_config(container)
    market_limits = _get_market_limits(container)

    # 获取持仓股票代码，用于跳过活跃度筛选
    query_service = HotStockQueryService(container.db_manager)
    position_codes = query_service.get_position_codes()
    priority_stocks_list = list(position_codes) if position_codes else []

    total = len(stocks_to_check)
    batch_size = 300  # 每批处理数量
    total_batches = (total + batch_size - 1) // batch_size

    active_count = 0
    inactive_count = 0
    failed_count = 0

    await _emit_progress(0, total_batches, 0, 0, phase="starting")

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        batch = stocks_to_check[i:i + batch_size]

        try:
            # 使用 ActivityFilterService 的筛选逻辑
            result = activity_filter.filter_by_realtime_activity(
                stocks=batch,
                market_limits=market_limits,
                activity_config=activity_config,
                priority_stocks=priority_stocks_list,
            )

            batch_active = len(result)
            batch_inactive = len(batch) - batch_active
            active_count += batch_active
            inactive_count += batch_inactive

        except Exception as e:
            logger.error(f"批次 {batch_num} 筛选失败: {e}", exc_info=True)
            failed_count += len(batch)

            # 将失败的股票标记为检查失败状态
            for stock in batch:
                code = stock.get('code', '')
                market = stock.get('market', 'HK')
                if code:
                    activity_filter.calculator.save_activity_cache(
                        code=code,
                        activity_score=-1,
                        market=market,
                        is_active=False,
                        check_failed=True
                    )

        checked = min(i + batch_size, total)
        await _emit_progress(
            batch_num, total_batches, checked, active_count, phase="filtering"
        )

    await _emit_complete(total, active_count, inactive_count, failed_count)

    logger.info(
        f"活跃度重新筛选完成: 总计{total}只, "
        f"活跃{active_count}只, 不活跃{inactive_count}只, 失败{failed_count}只"
    )

    # 筛选完成后，重新订阅股票以应用新的活跃度结果
    try:
        logger.info("开始重新订阅股票以应用新的活跃度结果...")
        from ...utils.market_helper import MarketTimeHelper

        # 获取当前活跃市场
        current_markets = MarketTimeHelper.get_current_active_markets()

        # 调用 subscription_helper 重新订阅
        subscription_helper = container.subscription_helper
        subscription_result = subscription_helper.subscribe_target_stocks(current_markets)

        if subscription_result.get('success'):
            subscribed_count = subscription_result.get('subscribed_count', 0)
            logger.info(f"重新订阅完成: 成功订阅 {subscribed_count} 只股票")

            # 推送订阅更新完成事件
            socket_manager = get_socket_manager()
            await socket_manager.emit_to_all("refilter_subscription_updated", {
                "success": True,
                "subscribed_count": subscribed_count,
                "message": f"已重新订阅 {subscribed_count} 只活跃股票"
            })
        else:
            logger.warning(f"重新订阅失败: {subscription_result.get('message', '未知错误')}")

    except Exception as e:
        logger.error(f"重新订阅股票失败: {e}", exc_info=True)


def _get_activity_config(container) -> Dict[str, Any]:
    """获取活跃度筛选配置"""
    config = container.config
    if config and hasattr(config, 'get'):
        return {
            'min_turnover_rate': config.get(
                'activity_filter.min_turnover_rate', {'HK': 0.1, 'US': 0.5}
            ),
            'min_turnover_amount': config.get(
                'activity_filter.min_turnover_amount', 5000000
            ),
            'min_volume': config.get(
                'activity_filter.min_volume', {'HK': 500000, 'US': 3000000}
            ),
        }
    return {
        'min_turnover_rate': {'HK': 0.1, 'US': 0.5},
        'min_turnover_amount': 5000000,
        'min_volume': {'HK': 500000, 'US': 3000000},
    }


def _get_market_limits(container) -> Dict[str, int]:
    """获取市场限制配置"""
    config = container.config
    if config and hasattr(config, 'get'):
        return {
            'HK': config.get('subscription.market_limits.HK', 200),
            'US': config.get('subscription.market_limits.US', 200),
        }
    return {'HK': 200, 'US': 200}
