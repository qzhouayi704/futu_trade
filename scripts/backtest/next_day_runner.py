"""
隔日交易对比分析运行器

对比当日买卖（日内交易）与当日买入次日卖出（隔日交易）的表现差异。
每只股票独立优化参数，分别运行两种模式，生成对比报告。
"""

import json
import pandas as pd
from datetime import datetime
from pathlib import Path

from .base_runner import BaseBacktestRunner
from simple_trade.backtest.strategies.price_position_strategy import (
    PricePositionStrategy, TARGET_STOCKS, ZONE_NAMES,
    SENTIMENT_ETF_CODE, SENTIMENT_BEARISH, SENTIMENT_NEUTRAL, SENTIMENT_BULLISH,
    DEFAULT_SENTIMENT_ADJUSTMENTS,
    OPEN_TYPE_GAP_UP, OPEN_TYPE_FLAT, OPEN_TYPE_GAP_DOWN, DEFAULT_GAP_THRESHOLD,
)
from simple_trade.backtest.core.loaders.backtest_only_loader import BacktestOnlyDataLoader
from simple_trade.backtest.core.fee_calculator import FeeCalculator

DEFAULT_TRADE_AMOUNT = 60000.0


class NextDayRunner(BaseBacktestRunner):
    """隔日交易对比分析运行器"""

    def get_strategy_name(self) -> str:
        return "隔日交易对比分析"

    def get_log_name(self) -> str:
        return 'next_day_backtest'

    def create_strategy(self):
        return PricePositionStrategy()

    def create_data_loader(self) -> BacktestOnlyDataLoader:
        return BacktestOnlyDataLoader(
            self.db_manager,
            market='HK',
            use_stock_pool_only=False,
            only_stocks_with_kline=False,
            min_kline_days=15
        )

    def run_baseline(self):
        """对比日内交易 vs 隔日交易"""
        strategy = self.create_strategy()
        fee_calculator = FeeCalculator()

        self.logger.info(f"策略: {strategy.get_strategy_name()}")
        self.logger.info(f"目标股票: {len(TARGET_STOCKS)}只")
        self.logger.info(f"回测时间: {self.args.start} 至 {self.args.end}")
        self.logger.info(f"交易金额: {DEFAULT_TRADE_AMOUNT:.0f} 港币/笔")
        self.logger.info("模式: 日内交易 vs 隔日交易 对比分析")

        breakeven = fee_calculator.estimate_breakeven_profit('HK', DEFAULT_TRADE_AMOUNT)
        self.logger.info(f"盈亏平衡收益率: {breakeven:.4f}%")

        start_dt = datetime.strptime(self.args.start, '%Y-%m-%d')
        end_dt = datetime.strptime(self.args.end, '%Y-%m-%d')

        # 加载情绪数据
        self.logger.info(f"\n加载大盘情绪数据: {SENTIMENT_ETF_CODE}")
        etf_kline_df = self.data_loader.load_kline_data(
            stock_code=SENTIMENT_ETF_CODE, start_date=start_dt, end_date=end_dt
        )
        sentiment_map = {}
        if etf_kline_df is not None and not etf_kline_df.empty:
            etf_kline_list = etf_kline_df.to_dict('records')
            sentiment_map = strategy.build_sentiment_map(etf_kline_list)
            self.logger.info(f"情绪映射表: {len(sentiment_map)} 个交易日")
        use_sentiment = len(sentiment_map) > 0

        stock_results = []
        all_intraday_trades = []
        all_nextday_trades = []

        for stock_code in TARGET_STOCKS:
            self.logger.info("")
            self.logger.info(f"{'='*60}")
            self.logger.info(f"分析 {stock_code}")
            self.logger.info(f"{'='*60}")

            kline_df = self.data_loader.load_kline_data(
                stock_code=stock_code, start_date=start_dt, end_date=end_dt
            )
            if kline_df is None or kline_df.empty:
                self.logger.warning(f"{stock_code}: 无K线数据，跳过")
                continue

            self.logger.info(f"加载 {len(kline_df)} 条K线数据")
            kline_list = kline_df.to_dict('records')
            for k in kline_list:
                k['stock_code'] = stock_code

            metrics = strategy.calculate_daily_metrics(
                kline_list, sentiment_map=sentiment_map if use_sentiment else None
            )
            if not metrics:
                self.logger.warning(f"{stock_code}: 指标数据为空，跳过")
                continue

            self.logger.info(f"生成 {len(metrics)} 条指标数据")

            # 区间统计 + 网格搜索最优参数（共用）
            zone_stats = strategy.compute_zone_statistics(metrics)
            grid_results = strategy.optimize_params_grid(
                metrics, zone_stats,
                fee_calculator=fee_calculator,
                trade_amount=DEFAULT_TRADE_AMOUNT,
            )

            trade_params = {}
            for zn in ZONE_NAMES:
                gr = grid_results.get(zn, {})
                best = gr.get('best_params', {})
                if best.get('buy_dip_pct', 0) > 0:
                    trade_params[zn] = {
                        'buy_dip_pct': best['buy_dip_pct'],
                        'sell_rise_pct': best['sell_rise_pct'],
                        'stop_loss_pct': best['stop_loss_pct'],
                    }
                else:
                    trade_params[zn] = {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}

            # 开盘类型参数优化（共用）
            open_type_params, enable_open_type_anchor, skip_gap_down = \
                self._optimize_open_type(strategy, metrics, trade_params, fee_calculator)

            sim_kwargs = dict(
                trade_params=trade_params,
                trade_amount=DEFAULT_TRADE_AMOUNT,
                fee_calculator=fee_calculator,
                use_sentiment=use_sentiment,
                sentiment_adjustments=DEFAULT_SENTIMENT_ADJUSTMENTS if use_sentiment else None,
                enable_open_type_anchor=enable_open_type_anchor,
                open_type_params=open_type_params if enable_open_type_anchor else None,
                skip_gap_down=skip_gap_down,
            )

            # ===== 日内交易 =====
            intraday_trades = strategy.simulate_trades(metrics, **sim_kwargs)
            self.logger.info(f"日内交易: {len(intraday_trades)} 笔")

            # ===== 隔日交易（次日卖出） =====
            # 隔日模式独立网格搜索卖出参数
            nd_trade_params, nd_ot_params, nd_enable_ot, nd_skip_gd = \
                self._optimize_next_day_params(strategy, metrics, zone_stats, fee_calculator, use_sentiment)

            nd_sim_kwargs = dict(
                trade_params=nd_trade_params,
                trade_amount=DEFAULT_TRADE_AMOUNT,
                fee_calculator=fee_calculator,
                use_sentiment=use_sentiment,
                sentiment_adjustments=DEFAULT_SENTIMENT_ADJUSTMENTS if use_sentiment else None,
                enable_open_type_anchor=nd_enable_ot,
                open_type_params=nd_ot_params if nd_enable_ot else None,
                skip_gap_down=nd_skip_gd,
            )
            nextday_trades = strategy.simulate_trades_next_day(metrics, **nd_sim_kwargs)
            self.logger.info(f"隔日交易: {len(nextday_trades)} 笔")

            # 统计对比
            intra_stats = self._calc_trade_stats(intraday_trades)
            nd_stats = self._calc_trade_stats(nextday_trades)

            self.logger.info(
                f"  日内: 胜率={intra_stats['win_rate']:.1f}%, "
                f"净盈亏={intra_stats['avg_net_profit']:.4f}%"
            )
            self.logger.info(
                f"  隔日: 胜率={nd_stats['win_rate']:.1f}%, "
                f"净盈亏={nd_stats['avg_net_profit']:.4f}%"
            )

            better = '隔日' if nd_stats['avg_net_profit'] > intra_stats['avg_net_profit'] else '日内'
            self.logger.info(f"  推荐: {better}交易")

            stock_results.append({
                'stock_code': stock_code,
                'metrics_count': len(metrics),
                'intraday': intra_stats,
                'nextday': nd_stats,
                'intraday_params': trade_params,
                'nextday_params': nd_trade_params,
                'intraday_ot_params': open_type_params if enable_open_type_anchor else None,
                'nextday_ot_params': nd_ot_params if nd_enable_ot else None,
                'recommendation': better,
            })

            all_intraday_trades.extend(intraday_trades)
            all_nextday_trades.extend(nextday_trades)

        if not stock_results:
            self.logger.error("没有有效的分析结果，回测终止")
            return

        self._generate_comparison_report(
            stock_results, all_intraday_trades, all_nextday_trades, breakeven
        )


    def _optimize_open_type(self, strategy, metrics, trade_params, fee_calculator):
        """开盘类型参数优化（与 PricePositionRunner 逻辑一致）"""
        gap_up_metrics = [m for m in metrics if m.get('open_type') == OPEN_TYPE_GAP_UP]
        gap_down_metrics = [m for m in metrics if m.get('open_type') == OPEN_TYPE_GAP_DOWN]

        open_type_params = {}
        enable = False

        # 高开日优化
        if len(gap_up_metrics) >= 3:
            best_net, best_params = self._grid_search_ot(
                strategy, gap_up_metrics, trade_params, fee_calculator,
                'gap_up', 'simulate_trades',
                buy_range=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0],
                sell_range=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0],
                sl_range=[1.0, 1.5, 2.0, 2.5, 3.0],
            )
            if best_net is not None and best_net > 0:
                open_type_params['gap_up'] = best_params
                enable = True

        # 低开日优化
        skip_gap_down = True
        if len(gap_down_metrics) >= 3:
            best_net, best_params = self._grid_search_ot(
                strategy, gap_down_metrics, trade_params, fee_calculator,
                'gap_down', 'simulate_trades',
                buy_range=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
                sell_range=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
                sl_range=[1.5, 2.0, 2.5, 3.0, 3.5],
            )
            if best_net is not None and best_net > 0:
                open_type_params['gap_down'] = best_params
                enable = True
                skip_gap_down = False

        return open_type_params, enable, skip_gap_down

    def _optimize_next_day_params(self, strategy, metrics, zone_stats, fee_calculator, use_sentiment):
        """隔日交易独立参数优化（使用 simulate_trades_next_day 评估）"""
        # 网格搜索：用 simulate_trades_next_day 评估每组参数
        self.logger.info("开始隔日交易参数网格搜索...")

        buy_range = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
        sell_range = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
        sl_range = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

        nd_trade_params = {}
        for zn in ZONE_NAMES:
            zs = zone_stats.get(zn, {})
            if zs.get('count', 0) < 3:
                nd_trade_params[zn] = {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}
                continue

            zone_metrics = [m for m in metrics if m['zone'] == zn]
            if len(zone_metrics) < 3:
                nd_trade_params[zn] = {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}
                continue

            best_net = None
            best_p = None
            for buy in buy_range:
                for sell in sell_range:
                    for sl in sl_range:
                        test_params = {zn: {'buy_dip_pct': buy, 'sell_rise_pct': sell, 'stop_loss_pct': sl}}
                        trades = strategy.simulate_trades_next_day(
                            zone_metrics, test_params,
                            trade_amount=DEFAULT_TRADE_AMOUNT,
                            fee_calculator=fee_calculator,
                        )
                        if len(trades) < 2:
                            continue
                        avg_net = sum(t['net_profit_pct'] for t in trades) / len(trades)
                        if avg_net > 0 and (best_net is None or avg_net > best_net):
                            best_net = avg_net
                            best_p = {'buy_dip_pct': buy, 'sell_rise_pct': sell, 'stop_loss_pct': sl}

            if best_p:
                nd_trade_params[zn] = best_p
                self.logger.info(
                    f"  {zn}: 隔日最优 买入={best_p['buy_dip_pct']:.2f}%, "
                    f"卖出={best_p['sell_rise_pct']:.2f}%, "
                    f"止损={best_p['stop_loss_pct']:.1f}%, 净盈亏={best_net:.4f}%"
                )
            else:
                nd_trade_params[zn] = {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}

        # 开盘类型参数优化（隔日模式）
        gap_up_metrics = [m for m in metrics if m.get('open_type') == OPEN_TYPE_GAP_UP]
        gap_down_metrics = [m for m in metrics if m.get('open_type') == OPEN_TYPE_GAP_DOWN]

        nd_ot_params = {}
        nd_enable_ot = False

        if len(gap_up_metrics) >= 3:
            best_net, best_params = self._grid_search_ot(
                strategy, gap_up_metrics, nd_trade_params, fee_calculator,
                'gap_up', 'simulate_trades_next_day',
                buy_range=[0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0],
                sell_range=[0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0],
                sl_range=[1.0, 1.5, 2.0, 2.5, 3.0],
            )
            if best_net is not None and best_net > 0:
                nd_ot_params['gap_up'] = best_params
                nd_enable_ot = True

        nd_skip_gd = True
        if len(gap_down_metrics) >= 3:
            best_net, best_params = self._grid_search_ot(
                strategy, gap_down_metrics, nd_trade_params, fee_calculator,
                'gap_down', 'simulate_trades_next_day',
                buy_range=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
                sell_range=[0.5, 1.0, 1.5, 2.0, 3.0, 4.0],
                sl_range=[1.5, 2.0, 2.5, 3.0, 3.5],
            )
            if best_net is not None and best_net > 0:
                nd_ot_params['gap_down'] = best_params
                nd_enable_ot = True
                nd_skip_gd = False

        return nd_trade_params, nd_ot_params, nd_enable_ot, nd_skip_gd

    def _grid_search_ot(self, strategy, ot_metrics, trade_params, fee_calculator,
                        ot_key, sim_method, buy_range, sell_range, sl_range):
        """通用开盘类型网格搜索"""
        simulate_fn = getattr(strategy, sim_method)
        best_net = None
        best_params = None

        for buy in buy_range:
            for sell in sell_range:
                for sl in sl_range:
                    test_ot_params = {ot_key: {
                        'buy_dip_pct': buy, 'sell_rise_pct': sell, 'stop_loss_pct': sl
                    }}
                    trades = simulate_fn(
                        ot_metrics, trade_params,
                        trade_amount=DEFAULT_TRADE_AMOUNT,
                        fee_calculator=fee_calculator,
                        enable_open_type_anchor=True,
                        open_type_params=test_ot_params,
                    )
                    if len(trades) < 2:
                        continue
                    avg_net = sum(t['net_profit_pct'] for t in trades) / len(trades)
                    if avg_net > 0 and (best_net is None or avg_net > best_net):
                        best_net = avg_net
                        win_count = len([t for t in trades if t['net_profit_pct'] > 0])
                        best_params = {
                            'buy_dip_pct': buy,
                            'sell_rise_pct': sell,
                            'stop_loss_pct': sl,
                            'avg_net_profit': round(avg_net, 4),
                            'win_rate': round(win_count / len(trades) * 100, 1),
                            'trades_count': len(trades),
                        }

        return best_net, best_params

    def _calc_trade_stats(self, trades):
        """计算交易统计"""
        total = len(trades)
        if total == 0:
            return {
                'trades_count': 0, 'win_rate': 0, 'avg_profit': 0,
                'avg_net_profit': 0, 'max_profit': 0, 'max_loss': 0,
                'stop_loss_rate': 0,
            }
        profitable = [t for t in trades if t['net_profit_pct'] > 0]
        sl_count = len([t for t in trades if t['exit_type'] == 'stop_loss'])
        return {
            'trades_count': total,
            'win_rate': round(len(profitable) / total * 100, 2),
            'avg_profit': round(sum(t['profit_pct'] for t in trades) / total, 4),
            'avg_net_profit': round(sum(t['net_profit_pct'] for t in trades) / total, 4),
            'max_profit': round(max(t['profit_pct'] for t in trades), 4),
            'max_loss': round(min(t['profit_pct'] for t in trades), 4),
            'stop_loss_rate': round(sl_count / total * 100, 2),
        }


    def _generate_comparison_report(self, stock_results, all_intraday, all_nextday, breakeven):
        """生成日内 vs 隔日对比报告"""
        output_dir = Path(self.args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_name = f"next_day_compare_{timestamp}"

        lines = []
        lines.append("# 日内交易 vs 隔日交易 对比分析报告\n")
        lines.append(f"分析时间范围: {self.args.start} 至 {self.args.end}")
        lines.append(f"分析股票数: {len(stock_results)}只")
        lines.append(f"交易金额: {DEFAULT_TRADE_AMOUNT:.0f} 港币/笔")
        lines.append(f"盈亏平衡收益率: {breakeven:.4f}%")
        lines.append("")

        # 总览对比表
        lines.append("## 一、各股票对比总览\n")
        lines.append(
            "| 股票 | 日内交易数 | 日内胜率 | 日内净盈亏 | 隔日交易数 | 隔日胜率 | 隔日净盈亏 | 推荐 |"
        )
        lines.append(
            "|------|----------|---------|----------|----------|---------|----------|------|"
        )
        for r in stock_results:
            intra = r['intraday']
            nd = r['nextday']
            lines.append(
                f"| {r['stock_code']} "
                f"| {intra['trades_count']} | {intra['win_rate']:.1f}% | {intra['avg_net_profit']:.4f}% "
                f"| {nd['trades_count']} | {nd['win_rate']:.1f}% | {nd['avg_net_profit']:.4f}% "
                f"| {r['recommendation']} |"
            )
        lines.append("")

        # 汇总统计
        intra_total_stats = self._calc_trade_stats(all_intraday)
        nd_total_stats = self._calc_trade_stats(all_nextday)
        lines.append("## 二、汇总统计\n")
        lines.append("| 指标 | 日内交易 | 隔日交易 |")
        lines.append("|------|---------|---------|")
        lines.append(f"| 总交易数 | {intra_total_stats['trades_count']} | {nd_total_stats['trades_count']} |")
        lines.append(f"| 胜率 | {intra_total_stats['win_rate']:.1f}% | {nd_total_stats['win_rate']:.1f}% |")
        lines.append(f"| 平均毛盈亏 | {intra_total_stats['avg_profit']:.4f}% | {nd_total_stats['avg_profit']:.4f}% |")
        lines.append(f"| 平均净盈亏 | {intra_total_stats['avg_net_profit']:.4f}% | {nd_total_stats['avg_net_profit']:.4f}% |")
        lines.append(f"| 最大盈利 | {intra_total_stats['max_profit']:.4f}% | {nd_total_stats['max_profit']:.4f}% |")
        lines.append(f"| 最大亏损 | {intra_total_stats['max_loss']:.4f}% | {nd_total_stats['max_loss']:.4f}% |")
        lines.append(f"| 止损率 | {intra_total_stats['stop_loss_rate']:.1f}% | {nd_total_stats['stop_loss_rate']:.1f}% |")
        lines.append("")

        # 每只股票详细对比
        for r in stock_results:
            code = r['stock_code']
            intra = r['intraday']
            nd = r['nextday']
            lines.append(f"## {code} 详细对比\n")

            lines.append("| 指标 | 日内交易 | 隔日交易 |")
            lines.append("|------|---------|---------|")
            lines.append(f"| 交易次数 | {intra['trades_count']} | {nd['trades_count']} |")
            lines.append(f"| 胜率 | {intra['win_rate']:.1f}% | {nd['win_rate']:.1f}% |")
            lines.append(f"| 平均毛盈亏 | {intra['avg_profit']:.4f}% | {nd['avg_profit']:.4f}% |")
            lines.append(f"| 平均净盈亏 | {intra['avg_net_profit']:.4f}% | {nd['avg_net_profit']:.4f}% |")
            lines.append(f"| 最大盈利 | {intra['max_profit']:.4f}% | {nd['max_profit']:.4f}% |")
            lines.append(f"| 最大亏损 | {intra['max_loss']:.4f}% | {nd['max_loss']:.4f}% |")
            lines.append(f"| 止损率 | {intra['stop_loss_rate']:.1f}% | {nd['stop_loss_rate']:.1f}% |")
            lines.append(f"| **推荐** | {'✓' if r['recommendation'] == '日内' else ''} | {'✓' if r['recommendation'] == '隔日' else ''} |")
            lines.append("")

            # 日内参数
            lines.append("### 日内交易最优参数\n")
            lines.append("| 区间 | 买入跌幅 | 卖出涨幅 | 止损 |")
            lines.append("|------|---------|---------|------|")
            for zn in ZONE_NAMES:
                p = r['intraday_params'].get(zn, {})
                if p.get('buy_dip_pct', 0) > 0:
                    lines.append(f"| {zn} | {p['buy_dip_pct']:.2f}% | {p['sell_rise_pct']:.2f}% | {p['stop_loss_pct']:.1f}% |")
                else:
                    lines.append(f"| {zn} | - | - | - |")
            lines.append("")

            # 隔日参数
            lines.append("### 隔日交易最优参数\n")
            lines.append("| 区间 | 买入跌幅 | 卖出涨幅 | 止损 |")
            lines.append("|------|---------|---------|------|")
            for zn in ZONE_NAMES:
                p = r['nextday_params'].get(zn, {})
                if p.get('buy_dip_pct', 0) > 0:
                    lines.append(f"| {zn} | {p['buy_dip_pct']:.2f}% | {p['sell_rise_pct']:.2f}% | {p['stop_loss_pct']:.1f}% |")
                else:
                    lines.append(f"| {zn} | - | - | - |")
            lines.append("")

            # 开盘类型参数对比
            intra_ot = r.get('intraday_ot_params')
            nd_ot = r.get('nextday_ot_params')
            if intra_ot or nd_ot:
                lines.append("### 开盘类型参数对比\n")
                lines.append("| 开盘类型 | 模式 | 买入跌幅 | 卖出涨幅 | 止损 | 净盈亏 | 胜率 |")
                lines.append("|---------|------|---------|---------|------|--------|------|")
                for ot_key, ot_label in [('gap_up', '高开'), ('gap_down', '低开')]:
                    ip = (intra_ot or {}).get(ot_key)
                    np_ = (nd_ot or {}).get(ot_key)
                    if ip:
                        lines.append(
                            f"| {ot_label} | 日内 | {ip['buy_dip_pct']:.2f}% | {ip['sell_rise_pct']:.2f}% "
                            f"| {ip['stop_loss_pct']:.1f}% | {ip.get('avg_net_profit', 0):.4f}% "
                            f"| {ip.get('win_rate', 0):.1f}% |"
                        )
                    if np_:
                        lines.append(
                            f"| {ot_label} | 隔日 | {np_['buy_dip_pct']:.2f}% | {np_['sell_rise_pct']:.2f}% "
                            f"| {np_['stop_loss_pct']:.1f}% | {np_.get('avg_net_profit', 0):.4f}% "
                            f"| {np_.get('win_rate', 0):.1f}% |"
                        )
                lines.append("")

        # 写入文件
        md_content = "\n".join(lines)
        md_path = output_dir / f"{report_name}_report.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        self.logger.info(f"Markdown报告: {md_path}")

        # CSV
        if all_intraday:
            for t in all_intraday:
                t['mode'] = 'intraday'
            for t in all_nextday:
                t['mode'] = 'nextday'
            all_trades_combined = all_intraday + all_nextday
            csv_path = output_dir / f"{report_name}_trades.csv"
            pd.DataFrame(all_trades_combined).to_csv(csv_path, index=False, encoding='utf-8-sig')
            self.logger.info(f"CSV交易记录: {csv_path}")

        # JSON
        summary = {
            'generated_at': datetime.now().isoformat(),
            'start_date': self.args.start,
            'end_date': self.args.end,
            'trade_amount': DEFAULT_TRADE_AMOUNT,
            'breakeven_rate': breakeven,
            'total_intraday': self._calc_trade_stats(all_intraday),
            'total_nextday': self._calc_trade_stats(all_nextday),
            'per_stock': {
                r['stock_code']: {
                    'intraday': r['intraday'],
                    'nextday': r['nextday'],
                    'recommendation': r['recommendation'],
                }
                for r in stock_results
            }
        }
        json_path = output_dir / f"{report_name}_summary.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        self.logger.info(f"JSON摘要: {json_path}")

        # 打印总览
        self.logger.info("")
        self.logger.info("=" * 100)
        self.logger.info("日内 vs 隔日 对比总览")
        self.logger.info("=" * 100)
        self.logger.info(
            f"{'股票':<14} {'日内交易':>8} {'日内胜率':>8} {'日内净盈亏':>10} "
            f"{'隔日交易':>8} {'隔日胜率':>8} {'隔日净盈亏':>10} {'推荐':>6}"
        )
        self.logger.info("-" * 100)
        for r in stock_results:
            i = r['intraday']
            n = r['nextday']
            self.logger.info(
                f"{r['stock_code']:<14} {i['trades_count']:>8} {i['win_rate']:>7.1f}% "
                f"{i['avg_net_profit']:>9.4f}% {n['trades_count']:>8} {n['win_rate']:>7.1f}% "
                f"{n['avg_net_profit']:>9.4f}% {r['recommendation']:>6}"
            )
        self.logger.info("=" * 100)

    def run_optimization(self):
        self.logger.info("隔日交易对比分析暂不支持参数优化模式")
