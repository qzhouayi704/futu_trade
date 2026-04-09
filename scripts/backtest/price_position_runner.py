"""
价格位置统计策略回测运行器

按每只股票独立进行统计分析、推荐参数、止损优化、模拟交易。
每只股票的波动特征不同，必须分别计算最优买卖参数。
"""

import json
import pandas as pd
from datetime import datetime
from pathlib import Path

from .base_runner import BaseBacktestRunner
from simple_trade.backtest.strategies.price_position_strategy import (
    PricePositionStrategy, TARGET_STOCKS, ZONE_NAMES,
    SENTIMENT_ETF_CODE, SENTIMENT_LEVELS, SENTIMENT_BEARISH, SENTIMENT_NEUTRAL, SENTIMENT_BULLISH,
    DEFAULT_SENTIMENT_THRESHOLDS, DEFAULT_SENTIMENT_ADJUSTMENTS,
    DEFAULT_OPEN_ANCHOR_PARAMS,
    OPEN_TYPE_GAP_UP, OPEN_TYPE_FLAT, OPEN_TYPE_GAP_DOWN, OPEN_TYPES, DEFAULT_GAP_THRESHOLD,
)
from simple_trade.backtest.core.loaders.backtest_only_loader import BacktestOnlyDataLoader
from simple_trade.backtest.core.fee_calculator import FeeCalculator

# 固定交易金额（港币）
DEFAULT_TRADE_AMOUNT = 60000.0


class PricePositionRunner(BaseBacktestRunner):
    """价格位置统计策略回测运行器"""

    def get_strategy_name(self) -> str:
        return "价格位置统计策略"

    def get_log_name(self) -> str:
        return 'price_position_backtest'

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
        """按每只股票独立分析 + 止损优化 + 模拟交易 + 生成报告（含大盘情绪）"""
        strategy = self.create_strategy()
        fee_calculator = FeeCalculator()

        self.logger.info(f"策略: {strategy.get_strategy_name()}")
        self.logger.info(f"目标股票: {len(TARGET_STOCKS)}只")
        self.logger.info(f"回测时间: {self.args.start} 至 {self.args.end}")
        self.logger.info(f"交易金额: {DEFAULT_TRADE_AMOUNT:.0f} 港币/笔")
        self.logger.info("模式: 按股票独立分析 + 网格搜索优化 + 大盘情绪调整")

        # 计算盈亏平衡收益率
        breakeven = fee_calculator.estimate_breakeven_profit('HK', DEFAULT_TRADE_AMOUNT)
        self.logger.info(f"盈亏平衡收益率: {breakeven:.4f}%")

        start_dt = datetime.strptime(self.args.start, '%Y-%m-%d')
        end_dt = datetime.strptime(self.args.end, '%Y-%m-%d')

        # ===== 加载恒生科技ETF数据，构建情绪映射表 =====
        self.logger.info(f"\n加载大盘情绪数据: {SENTIMENT_ETF_CODE}")
        etf_kline_df = self.data_loader.load_kline_data(
            stock_code=SENTIMENT_ETF_CODE,
            start_date=start_dt,
            end_date=end_dt
        )

        sentiment_map = {}
        if etf_kline_df is not None and not etf_kline_df.empty:
            etf_kline_list = etf_kline_df.to_dict('records')
            sentiment_map = strategy.build_sentiment_map(etf_kline_list)
            self.logger.info(f"情绪映射表: {len(sentiment_map)} 个交易日")

            # 统计情绪分布
            bearish_days = sum(1 for v in sentiment_map.values() if v['sentiment_level'] == SENTIMENT_BEARISH)
            neutral_days = sum(1 for v in sentiment_map.values() if v['sentiment_level'] == SENTIMENT_NEUTRAL)
            bullish_days = sum(1 for v in sentiment_map.values() if v['sentiment_level'] == SENTIMENT_BULLISH)
            total_days = len(sentiment_map)
            self.logger.info(
                f"情绪分布: 弱势={bearish_days}天({bearish_days/total_days*100:.1f}%), "
                f"中性={neutral_days}天({neutral_days/total_days*100:.1f}%), "
                f"强势={bullish_days}天({bullish_days/total_days*100:.1f}%)"
            )
        else:
            self.logger.warning(f"{SENTIMENT_ETF_CODE} 无K线数据，将不使用情绪调整")

        use_sentiment = len(sentiment_map) > 0

        stock_results = []
        all_trades = []

        for stock_code in TARGET_STOCKS:
            self.logger.info("")
            self.logger.info(f"{'='*60}")
            self.logger.info(f"分析 {stock_code}")
            self.logger.info(f"{'='*60}")

            # 加载K线数据
            kline_df = self.data_loader.load_kline_data(
                stock_code=stock_code,
                start_date=start_dt,
                end_date=end_dt
            )

            if kline_df is None or kline_df.empty:
                self.logger.warning(f"{stock_code}: 无K线数据，跳过")
                continue

            self.logger.info(f"加载 {len(kline_df)} 条K线数据")

            kline_list = kline_df.to_dict('records')
            for k in kline_list:
                k['stock_code'] = stock_code

            # 1. 计算该股票的每日指标（含情绪数据）
            metrics = strategy.calculate_daily_metrics(kline_list, sentiment_map=sentiment_map if use_sentiment else None)
            if not metrics:
                self.logger.warning(f"{stock_code}: 指标数据为空，跳过")
                continue

            self.logger.info(f"生成 {len(metrics)} 条指标数据")

            # 2. 该股票独立的区间统计
            zone_stats = strategy.compute_zone_statistics(metrics)

            for zn, s in zone_stats.items():
                if s['count'] > 0:
                    self.logger.info(
                        f"  {zn}: {s['count']}天, "
                        f"涨幅中位数={s['rise_stats']['median']:.2f}%, "
                        f"跌幅中位数={s['drop_stats']['median']:.2f}%"
                    )

            # 3. 该股票独立的推荐参数（含初始止损）— 作为初始参考
            initial_params = strategy.recommend_trade_params(zone_stats)

            for zn, p in initial_params.items():
                if p['buy_dip_pct'] > 0:
                    self.logger.info(
                        f"  {zn}: 初始买入跌幅={p['buy_dip_pct']:.2f}%, "
                        f"初始卖出涨幅={p['sell_rise_pct']:.2f}%, "
                        f"初始止损={p['stop_loss_pct']:.2f}%"
                    )

            # 4. 网格搜索：联合优化 buy_dip_pct, sell_rise_pct, stop_loss_pct
            self.logger.info("开始网格搜索优化...")
            grid_results = strategy.optimize_params_grid(
                metrics, zone_stats,
                fee_calculator=fee_calculator,
                trade_amount=DEFAULT_TRADE_AMOUNT,
            )

            # 构建最优参数
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
                    self.logger.info(
                        f"  {zn}: 最优买入跌幅={best['buy_dip_pct']:.2f}%, "
                        f"最优卖出涨幅={best['sell_rise_pct']:.2f}%, "
                        f"最优止损={best['stop_loss_pct']:.1f}%, "
                        f"利润空间={gr.get('profit_spread', 0):.2f}%, "
                        f"净盈亏={gr.get('avg_net_profit', 0):.4f}%, "
                        f"胜率={gr.get('win_rate', 0):.1f}%, "
                        f"搜索组合={gr.get('searched_combos', 0)}"
                    )
                else:
                    trade_params[zn] = {'buy_dip_pct': 0, 'sell_rise_pct': 0, 'stop_loss_pct': 3.0}
                    self.logger.info(f"  {zn}: 无可行参数（搜索组合={gr.get('searched_combos', 0)}）")

            # 5. 用最优参数运行最终模拟交易（含费用 + 情绪调整）
            # 第二阶段：按情绪等级分别优化调整系数
            # 核心改进：只用对应情绪等级的交易来评估该等级的系数，避免被其他等级稀释
            best_sentiment_adjustments = dict(DEFAULT_SENTIMENT_ADJUSTMENTS)
            if use_sentiment:
                self.logger.info("开始情绪调整系数优化（按等级独立评估）...")
                multiplier_range = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5]

                # --- 独立优化 bearish 系数 ---
                best_bear_net = None
                best_bear_adj = DEFAULT_SENTIMENT_ADJUSTMENTS[SENTIMENT_BEARISH]
                for bear_buy_m in multiplier_range:
                    for bear_sell_m in multiplier_range:
                        # bearish: buy_dip放大(>=1), sell_rise缩小(<=1)
                        if bear_buy_m < 1.0 or bear_sell_m > 1.0:
                            continue

                        test_adj = {
                            SENTIMENT_BEARISH: {'buy_dip_multiplier': bear_buy_m, 'sell_rise_multiplier': bear_sell_m},
                            SENTIMENT_NEUTRAL: {'buy_dip_multiplier': 1.0, 'sell_rise_multiplier': 1.0},
                            SENTIMENT_BULLISH: {'buy_dip_multiplier': 1.0, 'sell_rise_multiplier': 1.0},
                        }

                        test_trades = strategy.simulate_trades(
                            metrics, trade_params,
                            trade_amount=DEFAULT_TRADE_AMOUNT,
                            fee_calculator=fee_calculator,
                            use_sentiment=True,
                            sentiment_adjustments=test_adj,
                        )

                        # 只看 bearish 天的交易表现
                        bear_trades = [t for t in test_trades if t.get('sentiment_level') == SENTIMENT_BEARISH]
                        if len(bear_trades) < 2:
                            continue

                        bear_avg_net = sum(t['net_profit_pct'] for t in bear_trades) / len(bear_trades)
                        if best_bear_net is None or bear_avg_net > best_bear_net:
                            best_bear_net = bear_avg_net
                            best_bear_adj = {'buy_dip_multiplier': bear_buy_m, 'sell_rise_multiplier': bear_sell_m}

                self.logger.info(
                    f"  弱势最优: 买入×{best_bear_adj['buy_dip_multiplier']:.1f}, "
                    f"卖出×{best_bear_adj['sell_rise_multiplier']:.1f} "
                    f"(弱势天净盈亏={best_bear_net:.4f}%)" if best_bear_net is not None else
                    f"  弱势: 交易数不足，使用默认系数"
                )

                # --- 独立优化 bullish 系数 ---
                best_bull_net = None
                best_bull_adj = DEFAULT_SENTIMENT_ADJUSTMENTS[SENTIMENT_BULLISH]
                for bull_buy_m in multiplier_range:
                    for bull_sell_m in multiplier_range:
                        # bullish: buy_dip缩小(<=1), sell_rise放大(>=1)
                        if bull_buy_m > 1.0 or bull_sell_m < 1.0:
                            continue

                        test_adj = {
                            SENTIMENT_BEARISH: {'buy_dip_multiplier': 1.0, 'sell_rise_multiplier': 1.0},
                            SENTIMENT_NEUTRAL: {'buy_dip_multiplier': 1.0, 'sell_rise_multiplier': 1.0},
                            SENTIMENT_BULLISH: {'buy_dip_multiplier': bull_buy_m, 'sell_rise_multiplier': bull_sell_m},
                        }

                        test_trades = strategy.simulate_trades(
                            metrics, trade_params,
                            trade_amount=DEFAULT_TRADE_AMOUNT,
                            fee_calculator=fee_calculator,
                            use_sentiment=True,
                            sentiment_adjustments=test_adj,
                        )

                        # 只看 bullish 天的交易表现
                        bull_trades = [t for t in test_trades if t.get('sentiment_level') == SENTIMENT_BULLISH]
                        if len(bull_trades) < 2:
                            continue

                        bull_avg_net = sum(t['net_profit_pct'] for t in bull_trades) / len(bull_trades)
                        if best_bull_net is None or bull_avg_net > best_bull_net:
                            best_bull_net = bull_avg_net
                            best_bull_adj = {'buy_dip_multiplier': bull_buy_m, 'sell_rise_multiplier': bull_sell_m}

                self.logger.info(
                    f"  强势最优: 买入×{best_bull_adj['buy_dip_multiplier']:.1f}, "
                    f"卖出×{best_bull_adj['sell_rise_multiplier']:.1f} "
                    f"(强势天净盈亏={best_bull_net:.4f}%)" if best_bull_net is not None else
                    f"  强势: 交易数不足，使用默认系数"
                )

                # 组合最终系数
                best_sentiment_adjustments = {
                    SENTIMENT_BEARISH: best_bear_adj,
                    SENTIMENT_NEUTRAL: {'buy_dip_multiplier': 1.0, 'sell_rise_multiplier': 1.0},
                    SENTIMENT_BULLISH: best_bull_adj,
                }

                self.logger.info(
                    f"  最终情绪系数: "
                    f"弱势[买入×{best_bear_adj['buy_dip_multiplier']:.1f}, "
                    f"卖出×{best_bear_adj['sell_rise_multiplier']:.1f}], "
                    f"强势[买入×{best_bull_adj['buy_dip_multiplier']:.1f}, "
                    f"卖出×{best_bull_adj['sell_rise_multiplier']:.1f}]"
                )

            # 第三阶段：开盘类型参数优化（替换旧的情绪双锚点）
            # 3.1 计算开盘类型分布统计
            gap_threshold = DEFAULT_GAP_THRESHOLD
            gap_up_metrics = [m for m in metrics if m.get('open_type') == OPEN_TYPE_GAP_UP]
            flat_metrics = [m for m in metrics if m.get('open_type') == OPEN_TYPE_FLAT]
            gap_down_metrics = [m for m in metrics if m.get('open_type') == OPEN_TYPE_GAP_DOWN]
            total_metrics = len(metrics)

            open_type_stats = {
                OPEN_TYPE_GAP_UP: {
                    'count': len(gap_up_metrics),
                    'pct': round(len(gap_up_metrics) / total_metrics * 100, 1) if total_metrics > 0 else 0,
                },
                OPEN_TYPE_FLAT: {
                    'count': len(flat_metrics),
                    'pct': round(len(flat_metrics) / total_metrics * 100, 1) if total_metrics > 0 else 0,
                },
                OPEN_TYPE_GAP_DOWN: {
                    'count': len(gap_down_metrics),
                    'pct': round(len(gap_down_metrics) / total_metrics * 100, 1) if total_metrics > 0 else 0,
                },
            }

            self.logger.info(
                f"开盘类型分布: "
                f"高开={open_type_stats[OPEN_TYPE_GAP_UP]['count']}天({open_type_stats[OPEN_TYPE_GAP_UP]['pct']}%), "
                f"平开={open_type_stats[OPEN_TYPE_FLAT]['count']}天({open_type_stats[OPEN_TYPE_FLAT]['pct']}%), "
                f"低开={open_type_stats[OPEN_TYPE_GAP_DOWN]['count']}天({open_type_stats[OPEN_TYPE_GAP_DOWN]['pct']}%)"
            )

            # 3.2 高开日网格搜索：open_price 锚点最优参数
            open_type_params = {}
            enable_open_type_anchor = False

            if len(gap_up_metrics) >= 3:
                self.logger.info("开始高开日参数优化（open_price锚点）...")
                gu_buy_range = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
                gu_sell_range = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
                gu_sl_range = [1.0, 1.5, 2.0, 2.5, 3.0]
                best_gu_net = None
                best_gu_params = None
                best_gu_win_rate = 0
                best_gu_trades_count = 0

                for gu_buy in gu_buy_range:
                    for gu_sell in gu_sell_range:
                        for gu_sl in gu_sl_range:
                            test_ot_params = {
                                'gap_up': {
                                    'buy_dip_pct': gu_buy,
                                    'sell_rise_pct': gu_sell,
                                    'stop_loss_pct': gu_sl,
                                }
                            }

                            test_trades = strategy.simulate_trades(
                                gap_up_metrics, trade_params,
                                trade_amount=DEFAULT_TRADE_AMOUNT,
                                fee_calculator=fee_calculator,
                                enable_open_type_anchor=True,
                                open_type_params=test_ot_params,
                            )

                            if len(test_trades) < 2:
                                continue

                            avg_net = sum(t['net_profit_pct'] for t in test_trades) / len(test_trades)
                            if avg_net > 0 and (best_gu_net is None or avg_net > best_gu_net):
                                best_gu_net = avg_net
                                best_gu_params = {
                                    'buy_dip_pct': gu_buy,
                                    'sell_rise_pct': gu_sell,
                                    'stop_loss_pct': gu_sl,
                                }
                                win_count = len([t for t in test_trades if t['net_profit_pct'] > 0])
                                best_gu_win_rate = round(win_count / len(test_trades) * 100, 1)
                                best_gu_trades_count = len(test_trades)

                if best_gu_net is not None and best_gu_net > 0:
                    open_type_params['gap_up'] = best_gu_params
                    open_type_params['gap_up']['avg_net_profit'] = round(best_gu_net, 4)
                    open_type_params['gap_up']['win_rate'] = best_gu_win_rate
                    open_type_params['gap_up']['trades_count'] = best_gu_trades_count
                    enable_open_type_anchor = True
                    self.logger.info(
                        f"  高开日最优: 买入回调={best_gu_params['buy_dip_pct']:.2f}%, "
                        f"卖出涨幅={best_gu_params['sell_rise_pct']:.2f}%, "
                        f"止损={best_gu_params['stop_loss_pct']:.1f}%, "
                        f"净盈亏={best_gu_net:.4f}%, 胜率={best_gu_win_rate}%, "
                        f"交易数={best_gu_trades_count}"
                    )
                else:
                    self.logger.info("  高开日: 无正收益参数组合，使用zone默认参数")
            else:
                self.logger.info(f"  高开日: 样本不足({len(gap_up_metrics)}天)，跳过优化")

            # 3.3 低开日网格搜索：prev_close 锚点独立参数
            if len(gap_down_metrics) >= 3:
                self.logger.info("开始低开日参数优化（prev_close锚点）...")
                gd_buy_range = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
                gd_sell_range = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
                gd_sl_range = [1.5, 2.0, 2.5, 3.0, 3.5]
                best_gd_net = None
                best_gd_params = None
                best_gd_win_rate = 0
                best_gd_trades_count = 0

                for gd_buy in gd_buy_range:
                    for gd_sell in gd_sell_range:
                        for gd_sl in gd_sl_range:
                            test_ot_params = {
                                'gap_down': {
                                    'buy_dip_pct': gd_buy,
                                    'sell_rise_pct': gd_sell,
                                    'stop_loss_pct': gd_sl,
                                }
                            }

                            test_trades = strategy.simulate_trades(
                                gap_down_metrics, trade_params,
                                trade_amount=DEFAULT_TRADE_AMOUNT,
                                fee_calculator=fee_calculator,
                                enable_open_type_anchor=True,
                                open_type_params=test_ot_params,
                            )

                            if len(test_trades) < 2:
                                continue

                            avg_net = sum(t['net_profit_pct'] for t in test_trades) / len(test_trades)
                            if avg_net > 0 and (best_gd_net is None or avg_net > best_gd_net):
                                best_gd_net = avg_net
                                best_gd_params = {
                                    'buy_dip_pct': gd_buy,
                                    'sell_rise_pct': gd_sell,
                                    'stop_loss_pct': gd_sl,
                                }
                                win_count = len([t for t in test_trades if t['net_profit_pct'] > 0])
                                best_gd_win_rate = round(win_count / len(test_trades) * 100, 1)
                                best_gd_trades_count = len(test_trades)

                if best_gd_net is not None and best_gd_net > 0:
                    open_type_params['gap_down'] = best_gd_params
                    open_type_params['gap_down']['avg_net_profit'] = round(best_gd_net, 4)
                    open_type_params['gap_down']['win_rate'] = best_gd_win_rate
                    open_type_params['gap_down']['trades_count'] = best_gd_trades_count
                    enable_open_type_anchor = True
                    self.logger.info(
                        f"  低开日最优: 买入跌幅={best_gd_params['buy_dip_pct']:.2f}%, "
                        f"卖出涨幅={best_gd_params['sell_rise_pct']:.2f}%, "
                        f"止损={best_gd_params['stop_loss_pct']:.1f}%, "
                        f"净盈亏={best_gd_net:.4f}%, 胜率={best_gd_win_rate}%, "
                        f"交易数={best_gd_trades_count}"
                    )
                else:
                    self.logger.info("  低开日: 无正收益参数组合")
            else:
                self.logger.info(f"  低开日: 样本不足({len(gap_down_metrics)}天)，跳过优化")

            # 3.4 评估低开日整体净盈亏，决定是否建议跳过
            skip_gap_down = False
            gap_down_recommendation = 'skip'  # 默认建议跳过

            if len(gap_down_metrics) >= 3:
                # 用最优低开参数（如有）或zone参数模拟低开日交易
                if 'gap_down' in open_type_params:
                    gd_test_trades = strategy.simulate_trades(
                        gap_down_metrics, trade_params,
                        trade_amount=DEFAULT_TRADE_AMOUNT,
                        fee_calculator=fee_calculator,
                        enable_open_type_anchor=True,
                        open_type_params={'gap_down': open_type_params['gap_down']},
                    )
                else:
                    gd_test_trades = strategy.simulate_trades(
                        gap_down_metrics, trade_params,
                        trade_amount=DEFAULT_TRADE_AMOUNT,
                        fee_calculator=fee_calculator,
                    )

                if gd_test_trades:
                    gd_total_net = sum(t['net_profit_pct'] for t in gd_test_trades)
                    gd_avg_net = gd_total_net / len(gd_test_trades)
                    if gd_avg_net > 0:
                        gap_down_recommendation = 'trade'
                        skip_gap_down = False
                        self.logger.info(
                            f"  低开日评估: 平均净盈亏={gd_avg_net:.4f}% (正收益，建议交易)"
                        )
                    else:
                        gap_down_recommendation = 'skip'
                        skip_gap_down = True
                        self.logger.info(
                            f"  低开日评估: 平均净盈亏={gd_avg_net:.4f}% (负收益，建议跳过)"
                        )
                else:
                    self.logger.info("  低开日评估: 无交易产生，建议跳过")
                    skip_gap_down = True
            else:
                self.logger.info("  低开日评估: 样本不足，建议跳过")
                skip_gap_down = True

            # 3.5 最终模拟交易：使用开盘类型锚点
            trades = strategy.simulate_trades(
                metrics, trade_params,
                trade_amount=DEFAULT_TRADE_AMOUNT,
                fee_calculator=fee_calculator,
                use_sentiment=use_sentiment,
                sentiment_adjustments=best_sentiment_adjustments if use_sentiment else None,
                enable_open_type_anchor=enable_open_type_anchor,
                open_type_params=open_type_params if enable_open_type_anchor else None,
                skip_gap_down=skip_gap_down,
            )
            self.logger.info(f"产生 {len(trades)} 笔模拟交易")

            # 统计开盘类型分布
            gu_trades = [t for t in trades if t.get('open_type') == OPEN_TYPE_GAP_UP]
            fl_trades = [t for t in trades if t.get('open_type') == OPEN_TYPE_FLAT]
            gd_trades = [t for t in trades if t.get('open_type') == OPEN_TYPE_GAP_DOWN]
            if gu_trades or gd_trades:
                self.logger.info(
                    f"  高开: {len(gu_trades)}笔, 平开: {len(fl_trades)}笔, 低开: {len(gd_trades)}笔"
                )

            # 统计该股票结果
            total = len(trades)
            profitable = [t for t in trades if t['net_profit_pct'] > 0]
            win_rate = len(profitable) / total * 100 if total > 0 else 0
            avg_profit = sum(t['profit_pct'] for t in trades) / total if total > 0 else 0
            avg_net_profit = sum(t['net_profit_pct'] for t in trades) / total if total > 0 else 0
            stop_loss_count = len([t for t in trades if t['exit_type'] == 'stop_loss'])
            stop_loss_rate = stop_loss_count / total * 100 if total > 0 else 0

            if total > 0:
                self.logger.info(
                    f"胜率: {win_rate:.1f}%, 毛盈亏: {avg_profit:.4f}%, "
                    f"净盈亏: {avg_net_profit:.4f}%, 止损率: {stop_loss_rate:.1f}%"
                )

            stock_results.append({
                'stock_code': stock_code,
                'metrics_count': len(metrics),
                'zone_stats': zone_stats,
                'trade_params': trade_params,
                'grid_results': grid_results,
                'trades_count': total,
                'win_count': len(profitable),
                'win_rate': round(win_rate, 2),
                'avg_profit': round(avg_profit, 4),
                'avg_net_profit': round(avg_net_profit, 4),
                'max_profit': round(max((t['profit_pct'] for t in trades), default=0), 4),
                'max_loss': round(min((t['profit_pct'] for t in trades), default=0), 4),
                'stop_loss_rate': round(stop_loss_rate, 2),
                'sentiment_adjustments': best_sentiment_adjustments if use_sentiment else None,
                'open_type_stats': open_type_stats,
                'open_type_params': open_type_params if enable_open_type_anchor else None,
                'enable_open_type_anchor': enable_open_type_anchor,
                'gap_threshold': gap_threshold,
                'skip_gap_down': skip_gap_down,
                'gap_down_recommendation': gap_down_recommendation,
            })

            all_trades.extend(trades)

        if not stock_results:
            self.logger.error("没有有效的分析结果，回测终止")
            return

        # 6. 生成报告
        self._generate_reports(strategy, stock_results, all_trades, breakeven, sentiment_map, use_sentiment)

    def _generate_reports(self, strategy, stock_results, all_trades, breakeven, sentiment_map=None, use_sentiment=False):
        """生成按股票分别展示的报告（含情绪分析）"""
        output_dir = Path(self.args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_name = f"price_position_{timestamp}"

        # ===== Markdown 报告 =====
        lines = []
        lines.append("# 价格位置统计策略分析报告（修正版：基于prev_close买卖 + 网格搜索优化 + 手续费）\n")
        lines.append(f"分析时间范围: {self.args.start} 至 {self.args.end}")
        lines.append(f"分析股票数: {len(stock_results)}只")
        lines.append(f"回看天数: {strategy.lookback_days}日")
        lines.append(f"交易金额: {DEFAULT_TRADE_AMOUNT:.0f} 港币/笔")
        lines.append(f"盈亏平衡收益率: {breakeven:.4f}%")
        if use_sentiment:
            lines.append(f"大盘情绪数据源: {SENTIMENT_ETF_CODE}（恒生科技ETF）")
        lines.append("")

        # 情绪分布统计
        if use_sentiment and sentiment_map:
            lines.append("## 〇、大盘情绪分布\n")
            bearish_days = sum(1 for v in sentiment_map.values() if v['sentiment_level'] == SENTIMENT_BEARISH)
            neutral_days = sum(1 for v in sentiment_map.values() if v['sentiment_level'] == SENTIMENT_NEUTRAL)
            bullish_days = sum(1 for v in sentiment_map.values() if v['sentiment_level'] == SENTIMENT_BULLISH)
            total_days = len(sentiment_map)
            lines.append("| 情绪等级 | 天数 | 占比 |")
            lines.append("|---------|------|------|")
            lines.append(f"| 弱势(bearish) | {bearish_days} | {bearish_days/total_days*100:.1f}% |")
            lines.append(f"| 中性(neutral) | {neutral_days} | {neutral_days/total_days*100:.1f}% |")
            lines.append(f"| 强势(bullish) | {bullish_days} | {bullish_days/total_days*100:.1f}% |")
            lines.append(f"| 合计 | {total_days} | 100% |")
            lines.append("")

            # 按情绪等级分组统计交易结果
            if all_trades:
                lines.append("### 按情绪等级分组的交易结果\n")
                lines.append("| 情绪等级 | 交易数 | 胜率 | 平均毛盈亏 | 平均净盈亏 |")
                lines.append("|---------|-------|------|----------|----------|")
                for level, label in [(SENTIMENT_BEARISH, '弱势'), (SENTIMENT_NEUTRAL, '中性'), (SENTIMENT_BULLISH, '强势')]:
                    st_trades = [t for t in all_trades if t.get('sentiment_level') == level]
                    if st_trades:
                        st_win = len([t for t in st_trades if t['net_profit_pct'] > 0])
                        st_wr = st_win / len(st_trades) * 100
                        st_avg = sum(t['profit_pct'] for t in st_trades) / len(st_trades)
                        st_avg_net = sum(t['net_profit_pct'] for t in st_trades) / len(st_trades)
                        lines.append(f"| {label} | {len(st_trades)} | {st_wr:.1f}% | {st_avg:.4f}% | {st_avg_net:.4f}% |")
                    else:
                        lines.append(f"| {label} | 0 | - | - | - |")
                lines.append("")

        # 总览表
        lines.append("## 一、各股票回测总览\n")
        lines.append("| 股票 | 指标天数 | 交易次数 | 胜率 | 毛盈亏 | 净盈亏 | 最大盈利 | 最大亏损 | 止损率 |")
        lines.append("|------|---------|---------|------|--------|--------|---------|---------|--------|")
        for r in stock_results:
            lines.append(
                f"| {r['stock_code']} | {r['metrics_count']} | {r['trades_count']} "
                f"| {r['win_rate']:.1f}% | {r['avg_profit']:.4f}% | {r['avg_net_profit']:.4f}% "
                f"| {r['max_profit']:.4f}% | {r['max_loss']:.4f}% | {r['stop_loss_rate']:.1f}% |"
            )
        lines.append("")

        # 每只股票的详细分析
        for r in stock_results:
            code = r['stock_code']
            lines.append(f"## {code} 详细分析\n")

            # 区间统计
            lines.append(f"### 区间涨跌幅统计\n")
            lines.append("| 区间 | 天数 | 频率 | 涨幅均值 | 涨幅中位数 | 涨幅P75 | 跌幅均值 | 跌幅中位数 | 跌幅P75 |")
            lines.append("|------|------|------|---------|-----------|---------|---------|-----------|---------|")

            for zn in ZONE_NAMES:
                s = r['zone_stats'].get(zn, {})
                if s.get('count', 0) == 0:
                    lines.append(f"| {zn} | 0 | 0% | - | - | - | - | - | - |")
                    continue
                rs = s['rise_stats']
                ds = s['drop_stats']
                lines.append(
                    f"| {zn} | {s['count']} | {s['frequency_pct']:.1f}% "
                    f"| {rs['mean']:.2f}% | {rs['median']:.2f}% | {rs['p75']:.2f}% "
                    f"| {ds['mean']:.2f}% | {ds['median']:.2f}% | {ds['p75']:.2f}% |"
                )
            lines.append("")

            # 推荐参数（网格搜索最优）
            lines.append(f"### 网格搜索最优参数\n")
            lines.append("| 区间 | 买入跌幅基数 | 卖出涨幅基数 | 止损比例 | 利润空间 |")
            lines.append("|------|------------|------------|---------|---------|")
            for zn in ZONE_NAMES:
                p = r['trade_params'].get(zn, {})
                buy = p.get('buy_dip_pct', 0)
                sell = p.get('sell_rise_pct', 0)
                sl = p.get('stop_loss_pct', 0)
                if buy > 0:
                    spread = buy + sell
                    lines.append(f"| {zn} | {buy:.2f}% | {sell:.2f}% | {sl:.1f}% | {spread:.2f}% |")
                else:
                    lines.append(f"| {zn} | - | - | - | - |")
            lines.append("")

            # 网格搜索详情
            grid = r.get('grid_results', {})
            if grid:
                lines.append(f"### 网格搜索结果\n")
                lines.append("| 区间 | 净盈亏 | 胜率 | 交易数 | 止损率 | 搜索组合 |")
                lines.append("|------|--------|------|-------|--------|---------|")
                for zn in ZONE_NAMES:
                    g = grid.get(zn, {})
                    if g.get('trades_count', 0) > 0:
                        lines.append(
                            f"| {zn} | {g['avg_net_profit']:.4f}% "
                            f"| {g['win_rate']:.1f}% | {g['trades_count']} "
                            f"| {g['stop_loss_rate']:.1f}% | {g.get('searched_combos', 0)} |"
                        )
                    else:
                        lines.append(f"| {zn} | - | - | 0 | - | {g.get('searched_combos', 0)} |")
                lines.append("")

            # 情绪调整系数
            sa = r.get('sentiment_adjustments')
            if sa:
                lines.append(f"### 最优情绪调整系数\n")
                lines.append("| 情绪等级 | 买入跌幅乘数 | 卖出涨幅乘数 |")
                lines.append("|---------|------------|------------|")
                for level, label in [(SENTIMENT_BEARISH, '弱势'), (SENTIMENT_NEUTRAL, '中性'), (SENTIMENT_BULLISH, '强势')]:
                    adj = sa.get(level, {})
                    lines.append(f"| {label} | ×{adj.get('buy_dip_multiplier', 1.0):.1f} | ×{adj.get('sell_rise_multiplier', 1.0):.1f} |")
                lines.append("")

            # 开盘类型参数
            ot_stats = r.get('open_type_stats')
            if ot_stats:
                lines.append(f"### 开盘类型分布\n")
                lines.append("| 开盘类型 | 天数 | 占比 |")
                lines.append("|---------|------|------|")
                lines.append(f"| 高开(>{r.get('gap_threshold', DEFAULT_GAP_THRESHOLD)}%) | {ot_stats[OPEN_TYPE_GAP_UP]['count']} | {ot_stats[OPEN_TYPE_GAP_UP]['pct']}% |")
                lines.append(f"| 平开(±{r.get('gap_threshold', DEFAULT_GAP_THRESHOLD)}%) | {ot_stats[OPEN_TYPE_FLAT]['count']} | {ot_stats[OPEN_TYPE_FLAT]['pct']}% |")
                lines.append(f"| 低开(<-{r.get('gap_threshold', DEFAULT_GAP_THRESHOLD)}%) | {ot_stats[OPEN_TYPE_GAP_DOWN]['count']} | {ot_stats[OPEN_TYPE_GAP_DOWN]['pct']}% |")
                lines.append("")

            ot_params = r.get('open_type_params')
            if r.get('enable_open_type_anchor') and ot_params:
                lines.append(f"### 开盘类型参数\n")
                lines.append("| 开盘类型 | 锚点 | 买入跌幅 | 卖出涨幅 | 止损 | 净盈亏 | 胜率 | 交易数 | 建议 |")
                lines.append("|---------|------|---------|---------|------|--------|------|-------|------|")

                # 高开
                if 'gap_up' in ot_params:
                    gup = ot_params['gap_up']
                    lines.append(
                        f"| 高开 | open_price | {gup['buy_dip_pct']:.2f}% | {gup['sell_rise_pct']:.2f}% "
                        f"| {gup['stop_loss_pct']:.1f}% | {gup.get('avg_net_profit', 0):.4f}% "
                        f"| {gup.get('win_rate', 0):.1f}% | {gup.get('trades_count', 0)} | 交易 |"
                    )
                else:
                    lines.append("| 高开 | - | - | - | - | - | - | - | 使用zone参数 |")

                # 平开
                lines.append("| 平开 | prev_close | (按区间) | (按区间) | (按区间) | - | - | - | 交易 |")

                # 低开
                if 'gap_down' in ot_params:
                    gdp = ot_params['gap_down']
                    gd_rec = r.get('gap_down_recommendation', 'skip')
                    rec_label = '交易' if gd_rec == 'trade' else '跳过'
                    lines.append(
                        f"| 低开 | prev_close | {gdp['buy_dip_pct']:.2f}% | {gdp['sell_rise_pct']:.2f}% "
                        f"| {gdp['stop_loss_pct']:.1f}% | {gdp.get('avg_net_profit', 0):.4f}% "
                        f"| {gdp.get('win_rate', 0):.1f}% | {gdp.get('trades_count', 0)} | {rec_label} |"
                    )
                else:
                    gd_rec = r.get('gap_down_recommendation', 'skip')
                    rec_label = '交易' if gd_rec == 'trade' else '跳过'
                    lines.append(f"| 低开 | prev_close | - | - | - | - | - | - | {rec_label} |")
                lines.append("")
            else:
                lines.append(f"### 开盘类型参数\n")
                lines.append(f"- 状态: 未启用（无正收益参数组合）")
                lines.append("")

            # 交易结果
            stock_trades = [t for t in all_trades if t['stock_code'] == code]
            if stock_trades:
                lines.append(f"### 模拟交易结果\n")
                lines.append(f"- 交易次数: {len(stock_trades)}")
                profitable = [t for t in stock_trades if t['net_profit_pct'] > 0]
                lines.append(f"- 胜率（净）: {len(profitable)/len(stock_trades)*100:.1f}%")
                lines.append(f"- 平均毛盈亏: {sum(t['profit_pct'] for t in stock_trades)/len(stock_trades):.4f}%")
                lines.append(f"- 平均净盈亏: {sum(t['net_profit_pct'] for t in stock_trades)/len(stock_trades):.4f}%")
                sl_trades = [t for t in stock_trades if t['exit_type'] == 'stop_loss']
                lines.append(f"- 止损次数: {len(sl_trades)} ({len(sl_trades)/len(stock_trades)*100:.1f}%)")

                # 按开盘类型统计
                gu_stock_trades = [t for t in stock_trades if t.get('open_type') == OPEN_TYPE_GAP_UP]
                fl_stock_trades = [t for t in stock_trades if t.get('open_type') == OPEN_TYPE_FLAT]
                gd_stock_trades = [t for t in stock_trades if t.get('open_type') == OPEN_TYPE_GAP_DOWN]
                if gu_stock_trades or gd_stock_trades:
                    lines.append("")
                    lines.append("#### 按开盘类型统计\n")
                    lines.append("| 开盘类型 | 交易数 | 占比 | 胜率 | 平均净盈亏 |")
                    lines.append("|---------|-------|------|------|----------|")
                    for ot_label, ot_trades in [('高开', gu_stock_trades), ('平开', fl_stock_trades), ('低开', gd_stock_trades)]:
                        if ot_trades:
                            ot_win = len([t for t in ot_trades if t['net_profit_pct'] > 0])
                            ot_wr = ot_win / len(ot_trades) * 100
                            ot_avg_net = sum(t['net_profit_pct'] for t in ot_trades) / len(ot_trades)
                            ot_pct = len(ot_trades) / len(stock_trades) * 100
                            lines.append(f"| {ot_label} | {len(ot_trades)} | {ot_pct:.1f}% | {ot_wr:.1f}% | {ot_avg_net:.4f}% |")
                        else:
                            lines.append(f"| {ot_label} | 0 | 0% | - | - |")
                    lines.append("")

                # 按区间统计
                lines.append("")
                lines.append("| 区间 | 交易数 | 胜率 | 毛盈亏 | 净盈亏 | 止盈率 | 止损率 |")
                lines.append("|------|-------|------|--------|--------|--------|--------|")
                for zn in ZONE_NAMES:
                    zt = [t for t in stock_trades if t['zone'] == zn]
                    if not zt:
                        continue
                    zp = [t for t in zt if t['net_profit_pct'] > 0]
                    zpr = len([t for t in zt if t['exit_type'] == 'profit'])
                    zsl = len([t for t in zt if t['exit_type'] == 'stop_loss'])
                    lines.append(
                        f"| {zn} | {len(zt)} | {len(zp)/len(zt)*100:.1f}% "
                        f"| {sum(t['profit_pct'] for t in zt)/len(zt):.4f}% "
                        f"| {sum(t['net_profit_pct'] for t in zt)/len(zt):.4f}% "
                        f"| {zpr/len(zt)*100:.1f}% | {zsl/len(zt)*100:.1f}% |"
                    )
            lines.append("")

        md_content = "\n".join(lines)
        md_path = output_dir / f"{report_name}_report.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        self.logger.info(f"Markdown报告: {md_path}")

        # ===== CSV 交易记录 =====
        if all_trades:
            csv_path = output_dir / f"{report_name}_trades.csv"
            pd.DataFrame(all_trades).to_csv(csv_path, index=False, encoding='utf-8-sig')
            self.logger.info(f"CSV交易记录: {csv_path}")

        # ===== JSON 摘要 =====
        summary = {
            'generated_at': datetime.now().isoformat(),
            'start_date': self.args.start,
            'end_date': self.args.end,
            'trade_amount': DEFAULT_TRADE_AMOUNT,
            'breakeven_rate': breakeven,
            'use_sentiment': use_sentiment,
            'sentiment_etf': SENTIMENT_ETF_CODE if use_sentiment else None,
            'per_stock': {
                r['stock_code']: {
                    'trades_count': r['trades_count'],
                    'win_rate': r['win_rate'],
                    'avg_profit': r['avg_profit'],
                    'avg_net_profit': r['avg_net_profit'],
                    'stop_loss_rate': r['stop_loss_rate'],
                    'trade_params': {
                        zn: {k: v for k, v in p.items()}
                        for zn, p in r['trade_params'].items()
                    },
                    'sentiment_adjustments': {
                        level: {k: v for k, v in adj.items()}
                        for level, adj in r['sentiment_adjustments'].items()
                    } if r.get('sentiment_adjustments') else None,
                    'open_type_stats': r.get('open_type_stats'),
                    'enable_open_type_anchor': r.get('enable_open_type_anchor', False),
                    'open_type_params': r.get('open_type_params'),
                    'gap_threshold': r.get('gap_threshold', DEFAULT_GAP_THRESHOLD),
                    'skip_gap_down': r.get('skip_gap_down', False),
                    'gap_down_recommendation': r.get('gap_down_recommendation', 'skip'),
                }
                for r in stock_results
            }
        }
        json_path = output_dir / f"{report_name}_summary.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        self.logger.info(f"JSON摘要: {json_path}")

        # ===== 打印总览 =====
        self.logger.info("")
        self.logger.info("=" * 90)
        self.logger.info("各股票回测结果总览")
        self.logger.info("=" * 90)
        self.logger.info(
            f"{'股票':<14} {'交易数':>6} {'胜率':>8} {'毛盈亏':>10} {'净盈亏':>10} "
            f"{'最大盈利':>10} {'最大亏损':>10} {'止损率':>8}"
        )
        self.logger.info("-" * 90)
        for r in stock_results:
            self.logger.info(
                f"{r['stock_code']:<14} {r['trades_count']:>6} "
                f"{r['win_rate']:>7.1f}% {r['avg_profit']:>9.4f}% {r['avg_net_profit']:>9.4f}% "
                f"{r['max_profit']:>9.4f}% {r['max_loss']:>9.4f}% {r['stop_loss_rate']:>7.1f}%"
            )
        self.logger.info("=" * 90)

    def run_optimization(self):
        self.logger.info("价格位置统计策略暂不支持参数优化模式")
