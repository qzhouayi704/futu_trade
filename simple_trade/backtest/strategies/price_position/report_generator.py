#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
价格位置策略 — 报告生成模块

包含：
- generate_analysis_report: 生成单次分析报告（从 PricePositionStrategy 提取）
- generate_comparison_report: 生成多方案对比报告
- save_report: 保存报告到文件
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .constants import (
    ZONE_NAMES,
    OPEN_TYPE_GAP_UP,
    OPEN_TYPE_GAP_DOWN,
    ComparisonReport,
    SchemeResult,
    GridSearchResult,
    OpenTypeGridResult,
)


def generate_analysis_report(
    lookback_days: int,
    zone_stats: Dict[str, Any],
    trade_params: Dict[str, Dict[str, float]],
    trades: List[Dict[str, Any]],
    stock_codes: List[str],
    start_date: str,
    end_date: str,
) -> str:
    """生成单次价格位置统计策略分析报告（Markdown 格式）"""
    lines = []
    lines.append("# 价格位置统计策略分析报告\n")
    lines.append(f"分析时间范围: {start_date} 至 {end_date}\n")
    lines.append(f"分析股票数: {len(stock_codes)}只\n")
    lines.append(f"回看天数: {lookback_days}日\n")
    lines.append("")

    # 股票列表
    lines.append("## 一、分析股票列表\n")
    for code in stock_codes:
        lines.append(f"- {code}")
    lines.append("")

    # 区间统计
    lines.append("## 二、各区间涨跌幅统计\n")
    lines.append(
        "| 区间 | 天数 | 频率 | 涨幅均值 | 涨幅中位数 | 涨幅P25 | 涨幅P75 "
        "| 跌幅均值 | 跌幅中位数 | 跌幅P25 | 跌幅P75 |"
    )
    lines.append(
        "|------|------|------|----------|-----------|---------|---------|"
        "----------|-----------|---------|---------|"
    )

    for zone_name in ZONE_NAMES:
        s = zone_stats.get(zone_name, {})
        if s.get('count', 0) == 0:
            lines.append(f"| {zone_name} | 0 | 0% | - | - | - | - | - | - | - | - |")
            continue
        r = s['rise_stats']
        d = s['drop_stats']
        lines.append(
            f"| {zone_name} | {s['count']} | {s['frequency_pct']:.1f}% "
            f"| {r['mean']:.2f}% | {r['median']:.2f}% | {r['p25']:.2f}% | {r['p75']:.2f}% "
            f"| {d['mean']:.2f}% | {d['median']:.2f}% | {d['p25']:.2f}% | {d['p75']:.2f}% |"
        )
    lines.append("")

    # 推荐买卖参数
    lines.append("## 三、推荐买卖参数\n")
    lines.append("| 区间 | 买入跌幅基数 | 卖出涨幅基数 | 说明 |")
    lines.append("|------|------------|------------|------|")

    for zone_name in ZONE_NAMES:
        p = trade_params.get(zone_name, {})
        buy = p.get('buy_dip_pct', 0)
        sell = p.get('sell_rise_pct', 0)
        desc = f"前收盘价下跌{buy:.2f}%买入，上涨{sell:.2f}%卖出"
        lines.append(f"| {zone_name} | {buy:.2f}% | {sell:.2f}% | {desc} |")
    lines.append("")

    # 模拟交易结果
    lines.append("## 四、模拟交易结果\n")
    _append_trade_summary(lines, trades)

    lines.append("")
    return "\n".join(lines)


def _append_trade_summary(lines: List[str], trades: List[Dict[str, Any]]) -> None:
    """追加模拟交易结果统计（内部辅助函数）"""
    if not trades:
        lines.append("无交易记录\n")
        return

    total_trades = len(trades)
    profitable = [t for t in trades if t['profit_pct'] > 0]
    win_rate = len(profitable) / total_trades * 100 if total_trades > 0 else 0
    avg_profit = sum(t['profit_pct'] for t in trades) / total_trades if total_trades > 0 else 0
    max_profit = max(t['profit_pct'] for t in trades)
    max_loss = min(t['profit_pct'] for t in trades)
    profit_exits = [t for t in trades if t['exit_type'] == 'profit']
    close_exits = [t for t in trades if t['exit_type'] == 'close']

    lines.append(f"- 总交易次数: {total_trades}")
    lines.append(f"- 盈利次数: {len(profitable)}")
    lines.append(f"- 胜率: {win_rate:.2f}%")
    lines.append(f"- 平均盈亏: {avg_profit:.4f}%")
    lines.append(f"- 最大盈利: {max_profit:.4f}%")
    lines.append(f"- 最大亏损: {max_loss:.4f}%")
    lines.append(f"- 止盈退出: {len(profit_exits)}次")
    lines.append(f"- 收盘平仓: {len(close_exits)}次")
    lines.append("")

    # 按区间统计交易结果
    lines.append("### 按区间统计\n")
    lines.append("| 区间 | 交易次数 | 胜率 | 平均盈亏 | 最大盈利 | 最大亏损 | 止盈率 |")
    lines.append("|------|---------|------|---------|---------|---------|--------|")

    for zone_name in ZONE_NAMES:
        zt = [t for t in trades if t['zone'] == zone_name]
        if not zt:
            lines.append(f"| {zone_name} | 0 | - | - | - | - | - |")
            continue
        zp = [t for t in zt if t['profit_pct'] > 0]
        zwr = len(zp) / len(zt) * 100
        zavg = sum(t['profit_pct'] for t in zt) / len(zt)
        zmax = max(t['profit_pct'] for t in zt)
        zmin = min(t['profit_pct'] for t in zt)
        zprofit = len([t for t in zt if t['exit_type'] == 'profit'])
        zpr = zprofit / len(zt) * 100
        lines.append(
            f"| {zone_name} | {len(zt)} | {zwr:.1f}% | {zavg:.4f}% "
            f"| {zmax:.4f}% | {zmin:.4f}% | {zpr:.1f}% |"
        )


def generate_comparison_report(report: ComparisonReport) -> str:
    """生成多方案对比报告（Markdown 格式）"""
    lines = []
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines.append("# 价格位置策略 — 多方案对比报告\n")
    lines.append(f"生成时间: {now}\n")
    lines.append(f"对比方案数: {len(report.scheme_results)}个\n")
    lines.append(f"推荐方案: **{report.recommended_scheme}** ⭐\n")
    lines.append("")

    # ---- 一、关键指标对比 ----
    lines.append("## 一、各方案关键指标对比\n")
    lines.append(
        "| 方案 | 总交易数 | 胜率 | 平均净盈亏 | 最大回撤 "
        "| 止损率 | 综合评分 | 推荐卖出模式 |"
    )
    lines.append(
        "|------|---------|------|-----------|---------|"
        "--------|---------|------------|"
    )
    for name, sr in report.scheme_results.items():
        star = " ⭐" if name == report.recommended_scheme else ""
        lines.append(
            f"| {name}{star} | {sr.total_trades} | {sr.win_rate:.1f}% "
            f"| {sr.avg_net_profit:.4f}% | {sr.max_drawdown:.4f}% "
            f"| {sr.stop_loss_rate:.1f}% | {sr.composite_score:.4f} "
            f"| {sr.recommended_sell_mode} |"
        )
    lines.append("")

    # ---- 二、Zone 参数详情 ----
    lines.append("## 二、各方案 Zone 参数详情\n")
    for name, sr in report.scheme_results.items():
        lines.append(f"### {name}\n")
        lines.append("| 区间 | buy_dip | sell_rise | stop_loss | 综合评分 | 交易数 | 降级 |")
        lines.append("|------|---------|----------|-----------|---------|--------|------|")
        for zone_name in ZONE_NAMES:
            gr = sr.zone_params.get(zone_name)
            if not gr or not gr.best_params:
                lines.append(f"| {zone_name} | - | - | - | - | 0 | - |")
                continue
            bp = gr.best_params
            deg = "是" if gr.degraded else "-"
            lines.append(
                f"| {zone_name} | {bp.buy_dip_pct:.2f}% | {bp.sell_rise_pct:.2f}% "
                f"| {bp.stop_loss_pct:.2f}% | {gr.composite_score:.4f} "
                f"| {gr.trades_count} | {deg} |"
            )
        lines.append("")

    # ---- 三、Zone×OpenType 参数矩阵 ----
    _append_zone_open_type_matrix(lines, report)

    # ---- 四、卖出模式对比 ----
    _append_sell_mode_comparison(lines, report)

    # ---- 五、卖出模式推荐分布 ----
    lines.append("## 五、卖出模式推荐分布\n")
    for mode, count in report.sell_mode_summary.items():
        label = "日内卖出" if mode == 'intraday' else "次日卖出"
        lines.append(f"- {label}: {count}个方案推荐")
    lines.append("")

    # ---- 六、搜索配置与过程统计 ----
    _append_search_config(lines, report)

    return "\n".join(lines)


def _append_zone_open_type_matrix(lines: List[str], report: ComparisonReport) -> None:
    """追加 Zone×OpenType 参数矩阵"""
    has_cross = any(
        sr.zone_open_type_params for sr in report.scheme_results.values()
    )
    if not has_cross:
        return

    lines.append("## 三、Zone×OpenType 参数矩阵\n")
    for name, sr in report.scheme_results.items():
        if not sr.zone_open_type_params:
            continue
        lines.append(f"### {name}\n")
        lines.append(
            "| 区间 | 开盘类型 | buy_dip | sell_rise | stop_loss "
            "| 综合评分 | 交易数 | 回退 |"
        )
        lines.append(
            "|------|---------|---------|----------|-----------|"
            "---------|--------|------|"
        )
        for zone_name in ZONE_NAMES:
            zone_map = sr.zone_open_type_params.get(zone_name, {})
            for ot_key, ot_label in [
                (OPEN_TYPE_GAP_UP, '高开'),
                (OPEN_TYPE_GAP_DOWN, '低开'),
            ]:
                otr: Optional[OpenTypeGridResult] = zone_map.get(ot_key)
                if not otr or not otr.best_params:
                    lines.append(
                        f"| {zone_name} | {ot_label} | - | - | - | - | 0 | - |"
                    )
                    continue
                bp = otr.best_params
                fb = "是" if otr.fallback_to_flat else "-"
                lines.append(
                    f"| {zone_name} | {ot_label} | {bp.buy_dip_pct:.2f}% "
                    f"| {bp.sell_rise_pct:.2f}% | {bp.stop_loss_pct:.2f}% "
                    f"| {otr.composite_score:.4f} | {otr.trades_count} | {fb} |"
                )
        lines.append("")


def _append_sell_mode_comparison(lines: List[str], report: ComparisonReport) -> None:
    """追加卖出模式对比表格"""
    lines.append("## 四、卖出模式对比\n")
    for name, sr in report.scheme_results.items():
        smc = sr.sell_mode_comparison
        if not smc:
            continue
        lines.append(f"### {name}\n")
        lines.append("| 指标 | 日内卖出 | 次日卖出 |")
        lines.append("|------|---------|---------|")
        intra = smc.intraday
        nxt = smc.next_day
        lines.append(f"| 总交易数 | {intra.total_trades} | {nxt.total_trades} |")
        lines.append(f"| 胜率 | {intra.win_rate:.1f}% | {nxt.win_rate:.1f}% |")
        lines.append(
            f"| 平均净盈亏 | {intra.avg_net_profit:.4f}% | {nxt.avg_net_profit:.4f}% |"
        )
        lines.append(
            f"| 最大回撤 | {intra.max_drawdown:.4f}% | {nxt.max_drawdown:.4f}% |"
        )
        lines.append(
            f"| 止损率 | {intra.stop_loss_rate:.1f}% | {nxt.stop_loss_rate:.1f}% |"
        )
        lines.append(
            f"| 综合评分 | {intra.composite_score:.4f} | {nxt.composite_score:.4f} |"
        )
        suffix = ""
        if smc.next_day_insufficient:
            suffix = " （次日模式交易数不足）"
        intra_mark = "✅" if smc.recommended_mode == 'intraday' else ""
        nxt_mark = f"✅{suffix}" if smc.recommended_mode == 'next_day' else ""
        if smc.recommended_mode == 'intraday' and suffix:
            intra_mark = f"✅{suffix}"
        lines.append(f"| **推荐** | {intra_mark} | {nxt_mark} |")
        lines.append("")


def _append_search_config(lines: List[str], report: ComparisonReport) -> None:
    """追加搜索配置与过程统计"""
    lines.append("## 六、搜索配置与过程统计\n")
    for name, sr in report.scheme_results.items():
        lines.append(f"### {name}\n")
        scheme = sr.scheme
        lines.append(f"- min_sell_rise_pct: {scheme.min_sell_rise_pct}")
        lines.append(f"- min_buy_dip_pct: {scheme.min_buy_dip_pct}")
        lines.append(f"- min_trades: {scheme.min_trades}")
        lines.append(
            f"- enable_zone_open_type: {'是' if scheme.enable_zone_open_type else '否'}"
        )
        lines.append("")

        # 各区间搜索统计
        for zone_name in ZONE_NAMES:
            gr = sr.zone_params.get(zone_name)
            if not gr or not gr.search_config or not gr.search_stats:
                continue
            sc = gr.search_config
            ss = gr.search_stats
            lines.append(f"**{zone_name}**:")
            lines.append(f"  - sell_rise 范围: {sc.sell_rise_range}")
            lines.append(f"  - buy_dip 范围: {sc.buy_dip_range}")
            lines.append(f"  - min_trades: {sc.min_trades}")
            lines.append(f"  - 总组合数: {ss.total_combos}")
            lines.append(f"  - 有效组合数: {ss.valid_combos}")
            lines.append(f"  - 跳过组合数: {ss.skipped_combos}")
            lines.append("")


def save_report(content: str, filename: str, output_dir: str = 'backtest_results') -> str:
    """保存报告到文件，返回保存路径"""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return filepath
