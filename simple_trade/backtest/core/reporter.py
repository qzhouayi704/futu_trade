"""
回测报告生成器

负责生成回测报告，支持多种格式：
- Markdown格式报告
- CSV格式详细数据
- JSON格式摘要

报告内容包括：
- 回测参数
- 回测结果统计
- 涨幅分布
- 详细信号列表
"""

import json
import pandas as pd
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path
import logging


class BacktestReporter:
    """
    回测报告生成器

    生成多种格式的回测报告。
    """

    def __init__(self, output_dir: str = 'backtest_results'):
        """
        初始化报告生成器

        Args:
            output_dir: 输出目录路径
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(__name__)

    def generate_report(
        self,
        analysis: Dict[str, Any],
        signals: List[Dict[str, Any]],
        params: Dict[str, Any],
        report_name: Optional[str] = None,
        strategy_name: Optional[str] = None
    ) -> Dict[str, str]:
        """
        生成完整回测报告

        Args:
            analysis: 分析结果（来自 BacktestAnalyzer.analyze）
            signals: 信号列表
            params: 回测参数
            report_name: 报告名称（可选，如果不提供则自动生成）
            strategy_name: 策略名称（可选，用于文件命名）

        Returns:
            生成的文件路径字典
        """
        # 生成报告名称（策略名 + 时间戳）
        if report_name is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            if strategy_name:
                # 将策略名转换为文件名安全的格式
                safe_strategy_name = strategy_name.replace(' ', '_').replace('/', '_')
                report_name = f"{safe_strategy_name}_{timestamp}"
            else:
                report_name = f"backtest_{timestamp}"

        file_paths = {}

        # 生成Markdown报告
        md_path = self._generate_markdown_report(analysis, params, report_name)
        file_paths['markdown'] = str(md_path)

        # 生成CSV详细数据
        csv_path = self._generate_csv_report(signals, report_name)
        file_paths['csv'] = str(csv_path)

        # 生成JSON摘要
        json_path = self._generate_json_summary(analysis, params, report_name)
        file_paths['json'] = str(json_path)

        self.logger.info(f"报告已生成到: {self.output_dir}")
        self.logger.info(f"  - Markdown: {md_path.name}")
        self.logger.info(f"  - CSV: {csv_path.name}")
        self.logger.info(f"  - JSON: {json_path.name}")
        return file_paths

    def _generate_markdown_report(
        self,
        analysis: Dict[str, Any],
        params: Dict[str, Any],
        report_name: str
    ) -> Path:
        """生成Markdown格式报告"""
        output_path = self.output_dir / f"{report_name}_report.md"

        content = [
            "# 港股回测报告\n",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            f"报告文件: {report_name}\n",
            "\n---\n",
            "\n## 📋 报告说明\n",
            "\n本报告基于历史数据进行策略回测，用于评估策略的有效性和参数优化。\n",
            "\n**数据来源**: 数据库中的历史K线数据\n",
            "**回测方式**: 使用历史数据模拟交易，不包含实时API请求\n",
            "**结果解读**: 回测结果仅供参考，实际交易结果可能因市场环境、滑点、手续费等因素而有所不同\n",
            "\n---\n",
            "\n## 一、回测参数\n"
        ]

        # 回测参数
        content.append(f"- **回测时间范围**: {params.get('start_date', 'N/A')} 至 {params.get('end_date', 'N/A')}\n")
        content.append(f"- **股票市场**: {params.get('market', 'HK')}\n")
        content.append(f"- **测试股票数**: {params.get('total_stocks', 'N/A')}只\n")

        if 'strategy_name' in params:
            content.append(f"- **策略名称**: {params['strategy_name']}\n")

        # 策略参数
        if 'strategy_params' in params:
            content.append("\n### 策略参数\n")
            for key, value in params['strategy_params'].items():
                content.append(f"- {key}: {value}\n")

        # 回测结果
        content.append("\n## 二、回测结果\n")
        content.append(f"- **总信号数**: {analysis.get('total_signals', 0)}\n")
        content.append(f"- **达标次数**: {analysis.get('rise_count', 0)}\n")
        content.append(f"- **胜率**: {analysis.get('win_rate', 0):.2f}%\n")
        content.append(f"- **平均涨幅**: {analysis.get('avg_rise', 0):.2f}%\n")
        content.append(f"- **最大涨幅**: {analysis.get('max_rise', 0):.2f}%\n")

        if 'avg_days_to_peak' in analysis:
            content.append(f"- **平均达到最高点天数**: {analysis['avg_days_to_peak']:.1f}天\n")

        # 涨幅分布
        if 'distribution' in analysis:
            content.append("\n## 三、涨幅分布\n")
            dist = analysis['distribution']
            total = analysis['total_signals']

            for range_label, count in dist.items():
                percentage = (count / total * 100) if total > 0 else 0
                content.append(f"- **{range_label}**: {count}次 ({percentage:.2f}%)\n")

        # 按股票统计（如果有）
        if 'by_stock' in analysis:
            content.append("\n## 四、按股票统计（Top 10）\n")
            content.append("\n| 股票代码 | 股票名称 | 信号数 | 胜率 | 平均涨幅 |\n")
            content.append("|---------|---------|--------|------|----------|\n")

            for stock_stat in analysis['by_stock'][:10]:
                content.append(
                    f"| {stock_stat['stock_code']} | "
                    f"{stock_stat['stock_name']} | "
                    f"{stock_stat['count']} | "
                    f"{stock_stat['win_rate']:.2f}% | "
                    f"{stock_stat['avg_rise']:.2f}% |\n"
                )

        # 写入文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(content)

        self.logger.info(f"Markdown报告已生成: {output_path}")
        return output_path

    def _generate_csv_report(
        self,
        signals: List[Dict[str, Any]],
        report_name: str
    ) -> Path:
        """生成CSV格式详细数据"""
        output_path = self.output_dir / f"{report_name}_signals.csv"

        if not signals:
            self.logger.warning("没有信号数据，跳过CSV生成")
            return output_path

        # 转换为DataFrame
        df = pd.DataFrame(signals)

        # 确保列顺序
        columns = [
            'date', 'stock_code', 'stock_name', 'buy_price',
            'turnover_rate', 'is_low_position', 'max_rise_pct',
            'max_rise_days', 'is_target_reached'
        ]

        # 添加每日涨幅列（如果存在）
        day_columns = [col for col in df.columns if col.startswith('day')]
        columns.extend(sorted(day_columns))

        # 选择存在的列
        existing_columns = [col for col in columns if col in df.columns]
        df = df[existing_columns]

        # 保存
        df.to_csv(output_path, index=False, encoding='utf-8-sig')

        self.logger.info(f"CSV报告已生成: {output_path}，共{len(df)}条记录")
        return output_path

    def _generate_json_summary(
        self,
        analysis: Dict[str, Any],
        params: Dict[str, Any],
        report_name: str
    ) -> Path:
        """生成JSON格式摘要"""
        output_path = self.output_dir / f"{report_name}_summary.json"

        summary = {
            'generated_at': datetime.now().isoformat(),
            'backtest_params': params,
            'summary': {
                'total_signals': analysis.get('total_signals', 0),
                'rise_count': analysis.get('rise_count', 0),
                'win_rate': analysis.get('win_rate', 0),
                'avg_rise': analysis.get('avg_rise', 0),
                'max_rise': analysis.get('max_rise', 0),
                'avg_days_to_peak': analysis.get('avg_days_to_peak', 0)
            },
            'distribution': analysis.get('distribution', {})
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.logger.info(f"JSON摘要已生成: {output_path}")
        return output_path

    def generate_optimization_report(
        self,
        comparison_df: pd.DataFrame,
        best_params: Dict[str, Any],
        report_name: Optional[str] = None
    ) -> Dict[str, str]:
        """
        生成参数优化报告

        Args:
            comparison_df: 参数对比DataFrame
            best_params: 最优参数
            report_name: 报告名称

        Returns:
            生成的文件路径字典
        """
        if report_name is None:
            report_name = f"optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        file_paths = {}

        # 生成参数对比CSV
        csv_path = self.output_dir / f"{report_name}_params_comparison.csv"
        comparison_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        file_paths['comparison_csv'] = str(csv_path)

        # 生成最优参数JSON
        json_path = self.output_dir / f"{report_name}_best_params.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(best_params, f, indent=2, ensure_ascii=False)
        file_paths['best_params_json'] = str(json_path)

        # 生成优化报告Markdown
        md_path = self._generate_optimization_markdown(
            comparison_df, best_params, report_name
        )
        file_paths['markdown'] = str(md_path)

        self.logger.info(f"参数优化报告已生成到: {self.output_dir}")
        return file_paths

    def _generate_optimization_markdown(
        self,
        comparison_df: pd.DataFrame,
        best_params: Dict[str, Any],
        report_name: str
    ) -> Path:
        """生成参数优化Markdown报告"""
        output_path = self.output_dir / f"{report_name}_report.md"

        content = [
            "# 参数优化报告\n",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "\n## 一、最优参数\n"
        ]

        # 按不同指标的最优参数
        for metric_name, result in best_params.items():
            content.append(f"\n### {metric_name}\n")
            content.append(f"- **胜率**: {result['win_rate']:.2f}%\n")
            content.append(f"- **平均涨幅**: {result.get('avg_rise', 0):.2f}%\n")
            content.append(f"- **信号数**: {result['total_signals']}\n")

            content.append("\n**参数配置**:\n")
            for key, value in result['params'].items():
                content.append(f"- {key}: {value}\n")

        # 参数对比表（Top 10）
        content.append("\n## 二、参数对比（Top 10）\n")
        content.append("\n按胜率排序:\n")

        top_10 = comparison_df.nlargest(10, 'win_rate')
        content.append("\n| 排名 | 胜率 | 平均涨幅 | 信号数 | 参数组合 |\n")
        content.append("|------|------|----------|--------|----------|\n")

        for idx, row in enumerate(top_10.itertuples(), 1):
            params_str = ", ".join([
                f"{col}={getattr(row, col)}"
                for col in comparison_df.columns
                if col not in ['total_signals', 'win_rate', 'avg_rise', 'max_rise', 'avg_days_to_peak']
            ])
            content.append(
                f"| {idx} | "
                f"{row.win_rate:.2f}% | "
                f"{row.avg_rise:.2f}% | "
                f"{row.total_signals} | "
                f"{params_str} |\n"
            )

        # 写入文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(content)

        self.logger.info(f"优化报告Markdown已生成: {output_path}")
        return output_path
