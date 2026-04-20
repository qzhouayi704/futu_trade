#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置分析服务

提供股票K线数据检查/下载 + 价格位置回测分析的完整流程。
支持异步任务执行和进度跟踪。
"""

import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from ...backtest.strategies.price_position.constants import (
    ZONE_NAMES,
    OPEN_TYPE_GAP_UP, OPEN_TYPE_FLAT, OPEN_TYPE_GAP_DOWN, DEFAULT_GAP_THRESHOLD,
)
from ...backtest.strategies.price_position.grid_optimizer import (
    optimize_params_grid as new_optimize_params_grid,
    optimize_zone_open_type_grid,
)
from ...backtest.strategies.price_position.trade_simulator import (
    simulate_trades as sim_trades,
)
from ...backtest.core.fee_calculator import FeeCalculator
from .result_builder import (
    build_params_from_grid,
    build_open_type_stats,
    build_open_type_params,
    evaluate_gap_down,
    build_trade_summary,
    build_open_type_response,
)


# 固定交易金额
DEFAULT_TRADE_AMOUNT = 60000.0


class AnalysisService:
    """价格位置分析服务"""

    def __init__(self, db_manager, kline_service, futu_client):
        self.db_manager = db_manager
        self.kline_service = kline_service
        self.futu_client = futu_client
        self.tasks: Dict[str, Dict[str, Any]] = {}

    def start_analysis(self, stock_code: str) -> str:
        """启动分析任务（同步入口，创建后台任务）"""
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {
            'task_id': task_id,
            'stock_code': stock_code,
            'status': 'started',
            'progress': '初始化中...',
            'result': None,
            'error': None,
        }
        # 启动后台协程
        asyncio.ensure_future(self._run_analysis(task_id, stock_code))
        return task_id

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询任务状态"""
        return self.tasks.get(task_id)

    async def _run_analysis(self, task_id: str, stock_code: str):
        """后台执行分析流程"""
        task = self.tasks[task_id]
        try:
            # 1. 检查/下载K线数据
            task['status'] = 'downloading'
            task['progress'] = '检查K线数据...'
            kline_data = await self._ensure_kline_data(stock_code)
            if not kline_data:
                task['status'] = 'error'
                task['error'] = f'无法获取 {stock_code} 的K线数据'
                return

            task['progress'] = f'已加载 {len(kline_data)} 条K线数据'

            # 2. 计算指标
            task['status'] = 'analyzing'
            task['progress'] = '计算每日指标...'
            # 延迟导入，避免循环依赖
            from ...backtest.strategies.price_position_strategy import PricePositionStrategy
            strategy = PricePositionStrategy()
            fee_calculator = FeeCalculator()

            # 添加 stock_code 到每条K线
            for k in kline_data:
                k['stock_code'] = stock_code

            metrics = strategy.calculate_daily_metrics(kline_data)
            if not metrics:
                task['status'] = 'error'
                task['error'] = '指标数据为空，K线数据可能不足'
                return

            task['progress'] = f'生成 {len(metrics)} 条指标数据'

            # 3. 区间统计
            zone_stats = strategy.compute_zone_statistics(metrics)

            # 4. 网格搜索优化（使用新的 grid_optimizer 模块）
            task['status'] = 'optimizing'
            task['progress'] = '网格搜索优化中（可能需要30秒）...'

            loop = asyncio.get_event_loop()
            grid_results = await loop.run_in_executor(
                None,
                lambda: new_optimize_params_grid(
                    strategy, metrics, zone_stats,
                    fee_calculator=fee_calculator,
                    trade_amount=DEFAULT_TRADE_AMOUNT,
                )
            )

            # 5. 从 GridSearchResult 构建交易参数和前端输出
            task['progress'] = '运行模拟交易...'
            trade_params, best_params_output = build_params_from_grid(grid_results)

            # 5.5 Zone×OpenType 交叉参数优化
            task['progress'] = '开盘类型参数优化中...'
            gap_threshold = DEFAULT_GAP_THRESHOLD
            total_metrics = len(metrics)

            open_type_stats = build_open_type_stats(metrics, total_metrics)

            ot_grid = await loop.run_in_executor(
                None,
                lambda: optimize_zone_open_type_grid(
                    strategy, metrics, zone_stats, grid_results,
                    fee_calculator=fee_calculator,
                    trade_amount=DEFAULT_TRADE_AMOUNT,
                )
            )

            open_type_params, enable_open_type_anchor = build_open_type_params(ot_grid)

            # 低开日评估
            skip_gap_down, gap_down_recommendation = evaluate_gap_down(
                open_type_params, metrics, trade_params, strategy,
                fee_calculator, DEFAULT_TRADE_AMOUNT,
            )

            # 最终模拟交易
            trades = sim_trades(
                strategy, metrics, trade_params,
                trade_amount=DEFAULT_TRADE_AMOUNT,
                fee_calculator=fee_calculator,
                enable_open_type_anchor=enable_open_type_anchor,
                open_type_params=open_type_params if enable_open_type_anchor else None,
                skip_gap_down=skip_gap_down,
            )

            # 6. 汇总结果
            trade_summary = build_trade_summary(trades)

            # 序列化 zone_stats（numpy 值转 float）
            zone_stats_serializable = {}
            for zn, stats in zone_stats.items():
                zone_stats_serializable[zn] = {
                    'count': stats['count'],
                    'frequency_pct': float(stats['frequency_pct']),
                    'rise_stats': {k: float(v) for k, v in stats['rise_stats'].items()},
                    'drop_stats': {k: float(v) for k, v in stats['drop_stats'].items()},
                }

            # 提取最后一个交易日的信息（用于前端默认值）
            last_day = metrics[-1] if metrics else {}
            last_day_info = {
                'date': last_day.get('date', ''),
                'prev_close': round(last_day.get('prev_close', 0), 3),
                'open_price': round(last_day.get('open_price', 0), 3),
                'high_price': round(last_day.get('high_price', 0), 3),
                'low_price': round(last_day.get('low_price', 0), 3),
                'close_price': round(last_day.get('close_price', 0), 3),
                'zone': last_day.get('zone', ''),
                'price_position': round(last_day.get('price_position', 0), 2),
                'open_type': last_day.get('open_type', ''),
                'open_gap_pct': round(last_day.get('open_gap_pct', 0), 4),
            }

            task['status'] = 'completed'
            task['progress'] = '分析完成'
            task['result'] = {
                'stock_code': stock_code,
                'metrics_count': len(metrics),
                'zone_stats': zone_stats_serializable,
                'best_params': best_params_output,
                'trade_summary': trade_summary,
                'last_day_info': last_day_info,
                'open_type_stats': open_type_stats,
                'open_type_params': build_open_type_response(
                    open_type_params, gap_down_recommendation,
                ),
                'gap_threshold': gap_threshold,
            }

        except Exception as e:
            logging.error(f"分析任务 {task_id} 失败: {e}", exc_info=True)
            task['status'] = 'error'
            task['error'] = str(e)

    async def _ensure_kline_data(self, stock_code: str) -> list:
        """确保有近2年的K线数据，并补充下载最新数据，返回K线列表

        注意：数据库查询和富途API调用都是同步阻塞操作，
        必须通过 run_in_executor 在线程池中执行，避免阻塞事件循环。
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=730)  # 约2年
        loop = asyncio.get_event_loop()

        db_kline = []
        # 先从数据库查询（同步操作，放到线程池）
        try:
            kline_df = await loop.run_in_executor(
                None,
                lambda: self.db_manager.execute_query(
                    '''SELECT time_key, open_price, high_price, low_price, close_price, volume
                       FROM kline_data
                       WHERE stock_code = ? AND time_key >= ? AND time_key <= ?
                       ORDER BY time_key ASC''',
                    (stock_code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
                )
            )

            if kline_df and len(kline_df) >= 200:
                db_kline = [
                    {
                        'time_key': row[0],
                        'open_price': float(row[1]) if row[1] else 0,
                        'high_price': float(row[2]) if row[2] else 0,
                        'low_price': float(row[3]) if row[3] else 0,
                        'close_price': float(row[4]) if row[4] else 0,
                        'volume': int(row[5]) if row[5] else 0,
                    }
                    for row in kline_df
                ]
                logging.info(f"{stock_code}: 数据库已有 {len(db_kline)} 条K线数据")
        except Exception as e:
            logging.warning(f"查询数据库K线失败: {e}")

        # 无论数据库是否有数据，都尝试补充下载最新K线
        # 但如果数据库数据足够新（上一交易日以内），跳过补充下载以减少 OpenD 竞争
        need_supplement = True
        if db_kline and len(db_kline) >= 200:
            latest_date_str = db_kline[-1].get('time_key', '')[:10]
            if latest_date_str:
                try:
                    latest_date = datetime.strptime(latest_date_str, '%Y-%m-%d')
                    days_old = (end_date - latest_date).days
                    if days_old <= 2:
                        logging.info(
                            f"{stock_code}: 数据库K线数据较新（最后日期: {latest_date_str}，"
                            f"距今{days_old}天），跳过补充下载"
                        )
                        need_supplement = False
                except (ValueError, TypeError):
                    pass

        if need_supplement and self.futu_client and self.futu_client.is_available():
            try:
                # 补充下载最近30天的数据，确保上一交易日数据准确
                supplement_days = 30
                logging.info(f"{stock_code}: 补充下载最近{supplement_days}天K线数据...")
                new_kline = await loop.run_in_executor(
                    None,
                    self.kline_service.fetcher.fetch_kline_data,
                    stock_code, supplement_days
                )

                if new_kline and len(new_kline) > 0:
                    # 保存到数据库
                    saved = await loop.run_in_executor(
                        None,
                        self.kline_service.storage.save_kline_batch,
                        stock_code, new_kline
                    )
                    logging.info(f"{stock_code}: 补充保存 {saved} 条最新K线数据")

                    if db_kline:
                        # 合并：用新数据覆盖旧数据中相同日期的记录
                        existing_dates = {k['time_key'][:10] for k in db_kline}
                        merged = [k for k in db_kline
                                  if k['time_key'][:10] not in
                                  {nk['time_key'][:10] for nk in new_kline}]
                        merged.extend(new_kline)
                        merged.sort(key=lambda x: x['time_key'])
                        logging.info(f"{stock_code}: 合并后共 {len(merged)} 条K线数据")
                        return merged
                    elif len(new_kline) >= 200:
                        return new_kline
            except Exception as e:
                logging.warning(f"{stock_code}: 补充下载K线失败: {e}")

        # 如果数据库有足够数据（即使补充下载失败），仍然返回
        if db_kline:
            return db_kline

        # 数据库数据不足且无法补充，尝试全量下载
        if not self.futu_client or not self.futu_client.is_available():
            logging.error("富途客户端不可用，无法下载K线数据")
            return []

        logging.info(f"{stock_code}: 数据库数据不足，开始下载近2年K线...")
        try:
            kline_list = await loop.run_in_executor(
                None,
                self.kline_service.fetcher.fetch_kline_data,
                stock_code, 730
            )

            if kline_list and len(kline_list) > 0:
                saved = await loop.run_in_executor(
                    None,
                    self.kline_service.storage.save_kline_batch,
                    stock_code, kline_list
                )
                logging.info(f"{stock_code}: 下载并保存 {saved} 条K线数据")
                return kline_list
            else:
                logging.warning(
                    f"{stock_code}: 下载K线数据为空, "
                    f"API可用={self.futu_client.is_available()}, "
                    f"可能OpenD过载或股票无数据"
                )
                return []
        except Exception as e:
            logging.error(f"{stock_code}: 下载K线数据失败: {e}")
            return []
