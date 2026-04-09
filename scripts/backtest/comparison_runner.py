"""
参数优化对比回测运行器

使用 ComparisonRunner 对每只股票运行保守/均衡/激进三种方案的对比回测，
同时对比日内/次日两种卖出模式，生成综合对比报告。
"""

import json
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from .base_runner import BaseBacktestRunner
from simple_trade.backtest.strategies.price_position_strategy import (
    PricePositionStrategy, TARGET_STOCKS, ZONE_NAMES,
    SENTIMENT_ETF_CODE, SENTIMENT_BEARISH, SENTIMENT_NEUTRAL, SENTIMENT_BULLISH,
)
from simple_trade.backtest.strategies.price_position.constants import (
    PRESET_SCHEMES, OPEN_TYPE_GAP_UP, OPEN_TYPE_FLAT, OPEN_TYPE_GAP_DOWN,
)
from simple_trade.backtest.strategies.price_position.comparison_runner import (
    ComparisonRunner,
)
from simple_trade.backtest.strategies.price_position.report_generator import (
    generate_comparison_report, save_report,
)
from simple_trade.backtest.core.loaders.backtest_only_loader import BacktestOnlyDataLoader
from simple_trade.backtest.core.fee_calculator import FeeCalculator

DEFAULT_TRADE_AMOUNT = 60000.0


class ComparisonBacktestRunner(BaseBacktestRunner):
    """参数优化对比回测运行器"""

    def get_strategy_name(self) -> str:
        return "价格位置策略 — 多方案对比优化"

    def get_log_name(self) -> str:
        return 'comparison_backtest'

    def create_strategy(self):
        return PricePositionStrategy()

    def create_data_loader(self) -> BacktestOnlyDataLoader:
        return BacktestOnlyDataLoader(
            self.db_manager, market='HK',
            use_stock_pool_only=False,
            only_stocks_with_kline=False,
            min_kline_days=15,
        )

    def run_baseline(self):
        """运行多方案对比回测"""
        strategy = self.create_strategy()
        fee_calculator = FeeCalculator()

        self.logger.info(f"策略: {strategy.get_strategy_name()}")
        self.logger.info(f"目标股票: {len(TARGET_STOCKS)} 只")
        self.logger.info(f"回测时间: {self.args.start} 至 {self.args.end}")
        self.logger.info(f"交易金额: {DEFAULT_TRADE_AMOUNT:.0f} 港币/笔")
        self.logger.info(f"对比方案: {', '.join(PRESET_SCHEMES.keys())}")

        breakeven = fee_calculator.estimate_breakeven_profit('HK', DEFAULT_TRADE_AMOUNT)
        self.logger.info(f"盈亏平衡收益率: {breakeven:.4f}%")

        start_dt = datetime.strptime(self.args.start, '%Y-%m-%d')
        end_dt = datetime.strptime(self.args.end, '%Y-%m-%d')

        # 加载大盘情绪数据
        sentiment_map = self._load_sentiment(strategy, start_dt, end_dt)

        stock_reports: Dict[str, Any] = {}

        for stock_code in TARGET_STOCKS:
            self.logger.info("")
            self.logger.info(f"{'=' * 60}")
            self.logger.info(f"分析 {stock_code}")
            self.logger.info(f"{'=' * 60}")

            report = self._run_stock(strategy, fee_calculator, stock_code,
                                     start_dt, end_dt, sentiment_map)
            if report is None:
                continue

            stock_reports[stock_code] = report
            self._log_stock_summary(stock_code, report)

        if not stock_reports:
            self.logger.error("没有有效的分析结果，回测终止")
            return

        self._generate_output(stock_reports, breakeven)

    def _load_sentiment(self, strategy, start_dt, end_dt) -> dict:
        """加载大盘情绪映射表"""
        self.logger.info(f"加载大盘情绪数据: {SENTIMENT_ETF_CODE}")
        etf_df = self.data_loader.load_kline_data(
            stock_code=SENTIMENT_ETF_CODE,
            start_date=start_dt, end_date=end_dt,
        )
        if etf_df is None or etf_df.empty:
            self.logger.warning(f"{SENTIMENT_ETF_CODE} 无K线数据，不使用情绪调整")
            return {}

        sentiment_map = strategy.build_sentiment_map(etf_df.to_dict('records'))
        self.logger.info(f"情绪映射表: {len(sentiment_map)} 个交易日")

        # 统计分布
        counts = {SENTIMENT_BEARISH: 0, SENTIMENT_NEUTRAL: 0, SENTIMENT_BULLISH: 0}
        for v in sentiment_map.values():
            counts[v['sentiment_level']] = counts.get(v['sentiment_level'], 0) + 1
        total = len(sentiment_map)
        self.logger.info(
            f"情绪分布: 弱势={counts[SENTIMENT_BEARISH]}天({counts[SENTIMENT_BEARISH]/total*100:.1f}%), "
            f"中性={counts[SENTIMENT_NEUTRAL]}天({counts[SENTIMENT_NEUTRAL]/total*100:.1f}%), "
            f"强势={counts[SENTIMENT_BULLISH]}天({counts[SENTIMENT_BULLISH]/total*100:.1f}%)"
        )
        return sentiment_map

    def _run_stock(self, strategy, fee_calculator, stock_code,
                   start_dt, end_dt, sentiment_map):
        """对单只股票运行多方案对比回测"""
        kline_df = self.data_loader.load_kline_data(
            stock_code=stock_code, start_date=start_dt, end_date=end_dt,
        )
        if kline_df is None or kline_df.empty:
            self.logger.warning(f"{stock_code}: 无K线数据，跳过")
            return None

        self.logger.info(f"加载 {len(kline_df)} 条K线数据")
        kline_list = kline_df.to_dict('records')
        for k in kline_list:
            k['stock_code'] = stock_code

        # 计算指标
        use_sentiment = len(sentiment_map) > 0
        metrics = strategy.calculate_daily_metrics(
            kline_list,
            sentiment_map=sentiment_map if use_sentiment else None,
        )
        if not metrics:
            self.logger.warning(f"{stock_code}: 指标数据为空，跳过")
            return None

        self.logger.info(f"生成 {len(metrics)} 条指标数据")

        # 区间统计
        zone_stats = strategy.compute_zone_statistics(metrics)
        for zn, s in zone_stats.items():
            if s['count'] > 0:
                self.logger.info(
                    f"  {zn}: {s['count']}天, "
                    f"涨幅中位数={s['rise_stats']['median']:.2f}%, "
                    f"跌幅中位数={s['drop_stats']['median']:.2f}%"
                )

        # 运行多方案对比
        runner = ComparisonRunner(
            strategy=strategy,
            metrics=metrics,
            zone_stats=zone_stats,
            fee_calculator=fee_calculator,
            trade_amount=DEFAULT_TRADE_AMOUNT,
        )
        runner.load_preset_schemes()

        self.logger.info("开始多方案对比回测...")
        report = runner.run_comparison()
        return report

    def _log_stock_summary(self, stock_code: str, report) -> None:
        """打印单只股票的对比结果摘要"""
        self.logger.info(f"\n{stock_code} 对比结果:")
        self.logger.info(f"  推荐方案: {report.recommended_scheme}")

        for name, result in report.scheme_results.items():
            marker = " ★" if name == report.recommended_scheme else ""
            self.logger.info(
                f"  {name}{marker}: "
                f"交易数={result.total_trades}, "
                f"胜率={result.win_rate:.1f}%, "
                f"净盈亏={result.avg_net_profit:.4f}%, "
                f"综合评分={result.composite_score:.4f}, "
                f"推荐卖出={result.recommended_sell_mode}"
            )

    def _generate_output(self, stock_reports: Dict[str, Any], breakeven: float):
        """生成所有输出文件"""
        output_dir = Path(self.args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # 1. 生成 Markdown 对比报告
        md_lines = self._build_markdown(stock_reports, breakeven)
        md_content = "\n".join(md_lines)
        md_path = output_dir / f"comparison_{timestamp}_report.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        self.logger.info(f"Markdown 报告: {md_path}")

        # 2. 每只股票的详细对比报告（使用 report_generator）
        for stock_code, report in stock_reports.items():
            detail = generate_comparison_report(report)
            detail_path = save_report(
                detail,
                f"comparison_{stock_code.replace('.', '_')}_{timestamp}",
                str(output_dir),
            )
            self.logger.info(f"  {stock_code} 详细报告: {detail_path}")

        # 3. JSON 摘要
        summary = self._build_json_summary(stock_reports, breakeven)
        json_path = output_dir / f"comparison_{timestamp}_summary.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        self.logger.info(f"JSON 摘要: {json_path}")

        # 4. 打印总览
        self._print_overview(stock_reports)

    def _build_markdown(self, stock_reports, breakeven) -> List[str]:
        """构建 Markdown 总览报告"""
        lines = []
        lines.append("# 价格位置策略 — 多方案对比优化报告\n")
        lines.append(f"分析时间: {self.args.start} 至 {self.args.end}")
        lines.append(f"股票数: {len(stock_reports)} 只")
        lines.append(f"交易金额: {DEFAULT_TRADE_AMOUNT:.0f} 港币/笔")
        lines.append(f"盈亏平衡: {breakeven:.4f}%")
        lines.append(f"对比方案: {', '.join(PRESET_SCHEMES.keys())}")
        lines.append("")

        # 总览表
        lines.append("## 各股票推荐方案总览\n")
        lines.append("| 股票 | 推荐方案 | 交易数 | 胜率 | 净盈亏 | 综合评分 | 卖出模式 |")
        lines.append("|------|---------|-------|------|--------|---------|---------|")
        for code, report in stock_reports.items():
            best = report.recommended_scheme
            r = report.scheme_results.get(best)
            if r:
                lines.append(
                    f"| {code} | {best} | {r.total_trades} "
                    f"| {r.win_rate:.1f}% | {r.avg_net_profit:.4f}% "
                    f"| {r.composite_score:.4f} | {r.recommended_sell_mode} |"
                )
        lines.append("")

        # 各方案横向对比
        for scheme_name in PRESET_SCHEMES:
            lines.append(f"## {scheme_name} 各股票表现\n")
            lines.append("| 股票 | 交易数 | 胜率 | 净盈亏 | 止损率 | 综合评分 | 卖出模式 |")
            lines.append("|------|-------|------|--------|--------|---------|---------|")
            for code, report in stock_reports.items():
                r = report.scheme_results.get(scheme_name)
                if r:
                    lines.append(
                        f"| {code} | {r.total_trades} | {r.win_rate:.1f}% "
                        f"| {r.avg_net_profit:.4f}% | {r.stop_loss_rate:.1f}% "
                        f"| {r.composite_score:.4f} | {r.recommended_sell_mode} |"
                    )
            lines.append("")

        # 卖出模式推荐分布
        lines.append("## 卖出模式推荐分布\n")
        intraday_count = sum(
            1 for rpt in stock_reports.values()
            for sr in rpt.scheme_results.values()
            if sr.recommended_sell_mode == 'intraday'
        )
        next_day_count = sum(
            1 for rpt in stock_reports.values()
            for sr in rpt.scheme_results.values()
            if sr.recommended_sell_mode == 'next_day'
        )
        lines.append(f"- 日内卖出推荐: {intraday_count} 次")
        lines.append(f"- 次日卖出推荐: {next_day_count} 次")
        lines.append("")

        return lines

    def _build_json_summary(self, stock_reports, breakeven) -> dict:
        """构建 JSON 摘要"""
        per_stock = {}
        for code, report in stock_reports.items():
            schemes = {}
            for name, r in report.scheme_results.items():
                schemes[name] = {
                    'total_trades': r.total_trades,
                    'win_rate': r.win_rate,
                    'avg_net_profit': r.avg_net_profit,
                    'stop_loss_rate': r.stop_loss_rate,
                    'composite_score': r.composite_score,
                    'recommended_sell_mode': r.recommended_sell_mode,
                }
            per_stock[code] = {
                'recommended_scheme': report.recommended_scheme,
                'schemes': schemes,
            }

        return {
            'generated_at': datetime.now().isoformat(),
            'start_date': self.args.start,
            'end_date': self.args.end,
            'trade_amount': DEFAULT_TRADE_AMOUNT,
            'breakeven_rate': breakeven,
            'preset_schemes': list(PRESET_SCHEMES.keys()),
            'per_stock': per_stock,
        }

    def _print_overview(self, stock_reports) -> None:
        """打印总览表"""
        self.logger.info("")
        self.logger.info("=" * 100)
        self.logger.info("多方案对比回测总览")
        self.logger.info("=" * 100)
        self.logger.info(
            f"{'股票':<14} {'推荐方案':<10} {'交易数':>6} {'胜率':>8} "
            f"{'净盈亏':>10} {'综合评分':>10} {'卖出模式':>10}"
        )
        self.logger.info("-" * 100)
        for code, report in stock_reports.items():
            best = report.recommended_scheme
            r = report.scheme_results.get(best)
            if r:
                self.logger.info(
                    f"{code:<14} {best:<10} {r.total_trades:>6} "
                    f"{r.win_rate:>7.1f}% {r.avg_net_profit:>9.4f}% "
                    f"{r.composite_score:>9.4f} {r.recommended_sell_mode:>10}"
                )
        self.logger.info("=" * 100)

    def run_optimization(self):
        """参数优化模式（同 run_baseline，本身就是优化）"""
        self.run_baseline()
