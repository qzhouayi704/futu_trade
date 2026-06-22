#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立的 AI 股票分析服务

专用于「选股工作台」和「交易决策中心」的 AI 分析按钮。
接收股票代码 + 实时数据，连同规则知识库一起发给 Gemini，
返回结构化的买卖建议。
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

from .trading_rules_knowledge import TRADING_RULES_KNOWLEDGE

logger = logging.getLogger(__name__)


# 系统 Prompt：告诉 Gemini 它的角色和分析方法论
STOCK_AI_SYSTEM_PROMPT = """# 角色定义
你是一位资深的港股/美股短线量化交易分析师。你的分析必须像一个真正的操盘手一样思考——
不是罗列数据，而是从数据中提取矛盾、发现机会、识别风险。

# 核心分析方法论（按优先级执行）

## 第一步：定性判断（先下结论方向，再找证据）
看完所有数据后，先用一句话回答：这只股票现在是"被资金追捧"还是"被资金抛弃"？
判断依据的优先级：
1. **资金流方向** > 价格涨跌（价格是结果，资金是原因）
2. **大单动向** > 散户动向（主力决定方向）
3. **近期趋势** > 单日表现（一天的异动可能是噪音）

## 第二步：交叉验证（寻找确认或背离）
对比以下维度是否一致：
- 价格涨 + 资金流入 = ✅ 确认（健康上涨）
- 价格涨 + 资金流出 = ⚠️ 背离（可能是出货拉升，极度危险）
- 价格跌 + 资金流入 = 🔍 背离（可能是洗盘吸筹，需要更多证据）
- 价格跌 + 资金流出 = ✅ 确认（真实下跌，回避）

## 第三步：位置判断（同样的信号，位置不同含义不同）
- 低位放量 = 可能是建仓（看多）
- 高位放量 = 可能是出货（看空）
- 低位缩量 = 无人关注或洗盘末期
- 高位缩量 = 顶部背离信号
"低位"定义：K线20日位置 < 0.3
"高位"定义：K线20日位置 > 0.7

## 第四步：信号冲突时的决策优先级
当多个信号互相矛盾时，按以下优先级决策：
1. 🔴 经纪商席位显示"出货陷阱" → 最高优先级风险，直接建议卖出
2. 🔴 狙击手风险 TOP 3 + 持续流出信号 → 建议减仓/卖出
3. 🔴 一票否决触发 → 不管其他信号多好，不建议买入
4. 🟢 狙击手机会 TOP 3 + 价格低位 + 资金流入确认 → 积极关注
5. 📊 系统评分通过(>60) + 板块强势 → 可以买入
6. 其他情况 → 以资金流方向为准

## 第五步：给出操作建议时必须包含
- **为什么**：不超过200字，说清楚最关键的1-2个理由（不要面面俱到）
- **风险在哪**：最大的一个风险点
- **价格锚点**：如果建议买入/持有，止损设在哪里、目标价在哪里

# 常见错误（你必须避免）
❌ 看到亏损就建议止损（需要看趋势是否还在，资金是否在流入）
❌ 看到涨就建议买入（需要确认资金流方向，防止追高出货）
❌ 罗列所有指标但不下结论（用户需要明确的"买/卖/持有"）
❌ 所有股票都建议"HOLD"（这等于没分析）
❌ 把所有数据重复说一遍（用户已经看到了数据，需要的是你的判断）

# 输出要求
1. 所有文本必须使用简体中文
2. reasoning 字段要像人说话一样简洁有力，不要像报告一样生硬
3. 先在 reasoning 中展示你的推理过程，再给出 action
4. 严格输出 JSON 格式
"""


# Claude 结构化输出 schema（output_config.format）：强约束返回结构，消除手工 JSON 解析。
# 注：结构化输出不支持数值/字符串约束(min/max/maxLength)；可空字段用 anyOf+null。
STOCK_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["STRONG_BUY", "BUY", "HOLD", "REDUCE", "SELL", "STRONG_SELL"],
        },
        "confidence": {"type": "integer"},
        "reasoning": {"type": "string"},
        "key_factors": {"type": "array", "items": {"type": "string"}},
        "risk_warning": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "target_price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "stop_loss_price": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "score_assessment": {"type": "string"},
        "time_horizon": {"type": "string"},
    },
    "required": [
        "action", "confidence", "reasoning", "key_factors", "risk_warning",
        "target_price", "stop_loss_price", "score_assessment", "time_horizon",
    ],
    "additionalProperties": False,
}


class StockAIAnalyzer:
    """独立的 AI 股票分析器

    用于选股工作台和交易决策中心的 AI 分析功能。
    与 GeminiAnalyst（持仓顾问）不同，本服务面向单只股票的独立分析，
    不要求该股票在持仓中。
    """

    def __init__(self, model: str = "gemini-3.1-pro-preview",
                 project: str = "", location: str = "global",
                 credentials_path: str = "",
                 api_key: str = "", proxy: Optional[str] = None,
                 claude_client=None):
        self.model_name = model
        self.client = None
        # Claude 优先（官方 SDK：结构化输出+prompt缓存+自适应思考）；未配置时回退 Gemini。
        self._claude = claude_client

        if not GEMINI_AVAILABLE:
            logger.warning("google-genai SDK 未安装，AI 分析不可用")
            return

        try:
            import os
            if proxy:
                os.environ['https_proxy'] = proxy
                os.environ['http_proxy'] = proxy

            # 优先使用 Vertex AI（服务账号认证）
            if credentials_path:
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = credentials_path

            if project:
                self.client = genai.Client(
                    vertexai=True,
                    project=project,
                    location=location,
                )
                logger.info(f"StockAIAnalyzer Vertex AI 初始化成功，项目: {project}, 模型: {model}")
            elif api_key:
                self.client = genai.Client(api_key=api_key)
                logger.info(f"StockAIAnalyzer API Key 初始化成功，模型: {model}")
            else:
                logger.warning("StockAIAnalyzer 跳过：未配置 Vertex AI 项目或 API Key")
        except Exception as e:
            logger.error(f"StockAIAnalyzer 初始化失败: {e}")

        # 分析结果缓存（5分钟有效）
        self._cache: Dict[str, Dict] = {}
        self._cache_ttl = 300

    def is_available(self) -> bool:
        if self._claude is not None and self._claude.is_available():
            return True
        return GEMINI_AVAILABLE and self.client is not None

    async def analyze_stock(
        self,
        stock_code: str,
        stock_name: str,
        quote: Dict[str, Any],
        klines: Optional[List[Dict]] = None,
        score_result: Optional[Dict] = None,
        plate_info: Optional[str] = None,
        position_info: Optional[Dict] = None,
        news_data: Optional[Dict] = None,
        flow_data: Optional[Dict] = None,
        capital_flow_summary: Optional[Dict] = None,
        intraday_levels_data: Optional[Dict] = None,
        sniper_data: Optional[Dict] = None,
        pipeline_records: Optional[List[Dict]] = None,
        sniper_history: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """对单只股票执行 AI 分析

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            quote: 实时报价数据
            klines: K线数据列表（近30日）
            score_result: 标的评分结果（来自 StockScorer）
            plate_info: 所属板块信息
            position_info: 持仓信息（可选，如果是持仓股票）

        Returns:
            结构化的分析结果
        """
        if not self.is_available():
            logger.warning(f"[AI分析] {stock_code} 跳过：服务不可用")
            return {'success': False, 'error': 'AI 分析服务不可用'}

        # 检查缓存
        cached = self._get_cached(stock_code)
        if cached:
            return cached

        import time
        start_time = time.time()
        _use_claude = self._claude is not None and self._claude.is_available()
        engine = self._claude.model if _use_claude else self.model_name
        logger.info(f"[AI分析] 开始分析 {stock_code} ({stock_name})，引擎: {engine}")

        try:
            # 构建分析 Prompt
            prompt = self._build_analysis_prompt(
                stock_code, stock_name, quote, klines,
                score_result, plate_info, position_info, news_data, flow_data,
                capital_flow_summary, intraday_levels_data, sniper_data,
                pipeline_records, sniper_history,
            )
            logger.info(f"[AI分析] {stock_code} Prompt 构建完成，长度: {len(prompt)} 字符，K线: {len(klines) if klines else 0} 条")

            # 优先 Claude（官方 SDK：结构化输出免手工解析；静态 system+规则库走 prompt 缓存）
            if _use_claude:
                data = await self._claude.analyze(
                    system_prompt=STOCK_AI_SYSTEM_PROMPT,
                    cached_context=TRADING_RULES_KNOWLEDGE,
                    user_content=prompt,
                    schema=STOCK_ANALYSIS_SCHEMA,
                    label=stock_code,
                    max_tokens=4096,
                )
                result = self._normalize_result(data, stock_code, stock_name) if data else None
            else:
                # 回退 Gemini（文本响应 + 手工剥 JSON）
                response = await self._call_gemini(prompt)
                if not response:
                    logger.error(f"[AI分析] {stock_code} Gemini 返回空响应")
                    return {'success': False, 'error': 'AI 分析请求失败'}
                logger.info(f"[AI分析] {stock_code} Gemini 响应长度: {len(response)} 字符")
                result = self._parse_response(response, stock_code, stock_name)
            elapsed = time.time() - start_time
            if result:
                self._cache[stock_code] = {
                    'data': result,
                    'timestamp': datetime.now().isoformat(),
                }
                logger.info(
                    f"[AI分析] {stock_code} 分析完成 ✓ | "
                    f"建议: {result['action']} | 置信度: {result['confidence']}% | "
                    f"耗时: {elapsed:.1f}s"
                )
                return {'success': True, 'data': result}

            logger.error(f"[AI分析] {stock_code} 响应解析失败，耗时: {elapsed:.1f}s")
            return {'success': False, 'error': '解析 AI 响应失败'}

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[AI分析] {stock_code} 异常，耗时: {elapsed:.1f}s: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}

    def _build_analysis_prompt(
        self,
        stock_code: str,
        stock_name: str,
        quote: Dict[str, Any],
        klines: Optional[List[Dict]],
        score_result: Optional[Dict],
        plate_info: Optional[str],
        position_info: Optional[Dict],
        news_data: Optional[Dict] = None,
        flow_data: Optional[Dict] = None,
        capital_flow_summary: Optional[Dict] = None,
        intraday_levels_data: Optional[Dict] = None,
        sniper_data: Optional[Dict] = None,
        pipeline_records: Optional[List[Dict]] = None,
        sniper_history: Optional[List[Dict]] = None,
    ) -> str:
        """构建完整的分析 Prompt"""

        # 1. 基本信息
        prompt = f"""# 分析目标
- **股票**: {stock_code} ({stock_name})
- **分析时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        # 2. 实时行情
        last_price = quote.get('last_price', 0)
        change_pct = quote.get('change_rate', quote.get('change_percent', 0))
        volume = quote.get('volume', 0)
        turnover = quote.get('turnover', 0)
        turnover_rate = quote.get('turnover_rate', 0)
        high_price = quote.get('high_price', 0)
        low_price = quote.get('low_price', 0)
        open_price = quote.get('open_price', 0)
        prev_close = quote.get('prev_close_price', quote.get('last_close_price', 0))

        amplitude = 0
        if prev_close and prev_close > 0 and high_price > 0 and low_price > 0:
            amplitude = (high_price - low_price) / prev_close * 100

        prompt += f"""
## 实时行情
| 指标 | 数值 |
|------|------|
| 当前价 | {last_price:.3f} |
| 涨跌幅 | {change_pct:+.2f}% |
| 开盘价 | {open_price:.3f} |
| 最高价 | {high_price:.3f} |
| 最低价 | {low_price:.3f} |
| 前收盘 | {prev_close:.3f} |
| 振幅 | {amplitude:.2f}% |
| 成交量 | {volume:,} |
| 成交额 | {turnover:,.0f} |
| 换手率 | {turnover_rate:.2f}% |
"""

        # 3. K线走势（近20日）
        if klines and len(klines) > 0:
            recent = klines[-20:] if len(klines) >= 20 else klines
            lines = []
            for k in recent:
                date = k.get('time_key', k.get('date', '?'))
                o = k.get('open', 0)
                h = k.get('high', 0)
                l = k.get('low', 0)
                c = k.get('close', 0)
                vol = k.get('volume', 0)
                chg = ((c - o) / o * 100) if o > 0 else 0
                lines.append(
                    f"| {date} | {o:.2f} | {h:.2f} | {l:.2f} | {c:.2f} | {vol:,} | {chg:+.2f}% |"
                )

            prompt += f"""
## 近{len(recent)}日K线走势
| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 | 涨跌 |
|------|------|------|------|------|--------|------|
"""
            prompt += "\n".join(lines) + "\n"

            # 简单指标
            closes = [k.get('close', 0) for k in recent if k.get('close', 0) > 0]
            if len(closes) >= 5:
                ma5 = sum(closes[-5:]) / 5
                prompt += f"\n- MA5 = {ma5:.3f}"
            if len(closes) >= 10:
                ma10 = sum(closes[-10:]) / 10
                prompt += f", MA10 = {ma10:.3f}"
            if len(closes) >= 20:
                ma20 = sum(closes[-20:]) / 20
                prompt += f", MA20 = {ma20:.3f}"

            # 5日累计涨幅
            if len(closes) >= 6:
                change_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
                prompt += f"\n- 5日累计涨幅: {change_5d:+.2f}%"

            # 20日价格位置
            if len(recent) >= 10:
                highs = [k.get('high', 0) for k in recent]
                lows = [k.get('low', 0) for k in recent]
                max_h = max(highs) if highs else last_price
                min_l = min(lows) if lows else last_price
                if max_h > min_l:
                    kline_pos = (last_price - min_l) / (max_h - min_l)
                    prompt += f"\n- K线位置: {kline_pos:.2f} (0=最低, 1=最高)"

            prompt += "\n"

        # 4. 标的评分（如果有）
        if score_result:
            best_mode = score_result.get('best_mode', score_result.get('mode', ''))
            prompt += f"""
## 系统评分结果
- **最佳策略**: {best_mode}
- **最佳策略总分**: {score_result.get('total_score', 'N/A')}/100
- **是否通过**: {'✅ 通过' if score_result.get('passed') else '❌ 未通过'}
- **一票否决**: {score_result.get('veto_reason', '无')}
"""
            # 展示各策略独立评分
            strategies = score_result.get('strategies', [])
            if strategies:
                prompt += "\n### 各策略独立评分\n"
                for strat in strategies:
                    triggered = strat.get('triggered', True)
                    status = '✅通过' if strat.get('passed') else '❌未通过'
                    if not triggered:
                        status = '⏸️未触发'
                    prompt += f"\n**{strat['mode']}** — {strat['total_score']}/100 ({status})\n"
                    for d in strat.get('details', []):
                        prompt += f"  - {d.get('dimension', '')}: {d.get('score', 0)}/{d.get('max', 0)} (值={d.get('value', 'N/A')}) {d.get('note', '')}\n"
            else:
                # 旧格式兼容
                details = score_result.get('details', [])
                if details:
                    prompt += "- **分项评分**:\n"
                    for d in details:
                        prompt += f"  - {d.get('dimension', '')}: {d.get('score', 0)}/{d.get('max', 0)} (值={d.get('value', 'N/A')}) {d.get('note', '')}\n"

        # 5. 板块信息
        if plate_info:
            prompt += f"\n## 板块信息\n{plate_info}\n"

        # 6. 持仓信息（如果是持仓股票）
        if position_info:
            cost_price = position_info.get('cost_price', 0)
            qty = position_info.get('qty', 0)
            pl_ratio = position_info.get('pl_ratio', 0)
            holding_days = position_info.get('holding_days', 0)
            prompt += f"""
## 持仓信息
- 成本价: {cost_price:.3f}
- 持仓数量: {qty}
- 盈亏比例: {pl_ratio:+.2f}%
- 持有天数: {holding_days}
"""

        # 7. 资金流数据（从 quote 中提取）
        main_net_inflow = quote.get('main_net_inflow', 0)
        capital_score = quote.get('capital_score', 0)
        net_inflow_ratio = quote.get('net_inflow_ratio', 0)
        if main_net_inflow or capital_score:
            direction = "净流入" if main_net_inflow > 0 else "净流出"
            prompt += f"""
## 资金流向
- 主力资金{direction}: {abs(main_net_inflow)/10000:.1f}万
- 资金评分: {capital_score:.0f}/100
- 净流入占比: {net_inflow_ratio:+.2f}%
"""

        # 8. 消息面数据
        if news_data and news_data.get('news'):
            prompt += "\n## 消息面（近期新闻）\n"
            for item in news_data['news'][:5]:
                sentiment_icon = {'positive': '🟢', 'negative': '🔴'}.get(item.get('sentiment', ''), '⚪')
                prompt += f"- {sentiment_icon} [{item.get('date', '')}] {item.get('title', '')}\n"
                if item.get('summary'):
                    prompt += f"  摘要: {item['summary']}\n"
            catalysts = news_data.get('key_catalysts', [])
            risks = news_data.get('risk_factors', [])
            if catalysts:
                prompt += f"- **催化剂**: {', '.join(catalysts)}\n"
            if risks:
                prompt += f"- **风险因素**: {', '.join(risks)}\n"
            prompt += f"- **总体情绪**: {news_data.get('overall_sentiment', 'neutral')}\n"

        # 9. 日内资金流分析（逐笔成交数据）
        if flow_data:
            prompt += "\n## 日内资金流分析（实时逐笔成交）\n"

            # 大单追踪汇总
            summary = flow_data.get('big_order_summary')
            if summary:
                prompt += f"""### 近 30 分钟大单追踪
- 主力趋势: **{summary['trend']}**
- 平均强度: {summary['avg_strength']:+.2f} (正=买方主导, 负=卖方主导)
- 买方主导周期: {summary['buy_dominant_periods']}/{summary['total_periods']}
- 卖方主导周期: {summary['sell_dominant_periods']}/{summary['total_periods']}
"""

            # 当日累计
            accum = flow_data.get('daily_accumulator')
            if accum:
                prompt += f"""### 当日累计
- 大单买入: {accum['big_buy']}
- 大单卖出: {accum['big_sell']}
- **净额**: {accum['net']} ({'\u2191净流入' if accum['is_net_inflow'] else '\u2193净流出'})
- 买卖比: {accum['ratio']}
"""

            # 资金流信号
            signal = flow_data.get('flow_signal')
            if signal:
                prompt += f"""### \u26a0\ufe0f 资金流信号
- **信号类型**: {signal['label']}
- **详情**: {signal['detail']}
- **含义**: {'\u5e95部承接,看多' if signal['type']=='absorption' else '\u4e3b\u529b\u51fa\u8d27,\u770b\u7a7a' if signal['type']=='pump_dump' else '\u4e70\u65b9\u65e0\u529b,\u770b\u7a7a' if signal['type']=='failed_catch' else '\u6d17\u76d8\u53ef\u80fd,\u89c2\u671b' if signal['type']=='washout' else '\u5f85\u5224\u65ad'}
"""

            # 最近快照明细
            snapshots = flow_data.get('recent_big_orders', [])
            if snapshots:
                prompt += "### 最近大单快照\n"
                prompt += "| 时间 | 买入额 | 卖出额 | 买卖比 | 强度 |\n"
                prompt += "|------|--------|--------|--------|------|\n"
                for s in snapshots[:6]:
                    prompt += f"| {s['time'][-8:]} | {s['buy_amt']} | {s['sell_amt']} | {s['ratio']} | {s['strength']:+.2f} |\n"
                prompt += "\n"

        # 10. 逐笔资金流时间线摘要（动能+买卖比+前后半段对比）
        if capital_flow_summary and capital_flow_summary.get('summary'):
            s = capital_flow_summary['summary']
            prompt += f"""
## 日内资金流动能分析（逐笔成交时间线）
| 指标 | 数值 |
|------|------|
| **动能标签** | {s.get('momentum_label', '未知')} |
| **信号** | {s.get('signal', 'neutral')} |
| **买卖力量比** | {s.get('buy_sell_ratio', 'N/A')} |
| **累计净流入** | {s.get('cum_net', 0):.1f}万 |
| **最近净流入** | {s.get('recent_net', 0):.1f}万 |
| **前半段净流入** | {s.get('first_half_net', 0):.1f}万 |
| **后半段净流入** | {s.get('second_half_net', 0):.1f}万 |
| **数据点数** | {capital_flow_summary.get('data_points', 0)} |
"""
            first_half = s.get('first_half_net', 0)
            second_half = s.get('second_half_net', 0)
            if first_half != 0 or second_half != 0:
                if second_half > first_half > 0:
                    prompt += "- **特征**: 后半段加速流入（买方力量增强）\n"
                elif first_half > 0 > second_half:
                    prompt += "- **特征**: 前半段流入后半段流出（冲高出货嫌疑）\n"
                elif first_half < 0 and second_half > abs(first_half):
                    prompt += "- **特征**: 先杀后拉（洗盘或抄底）\n"
                elif second_half < first_half < 0:
                    prompt += "- **特征**: 后半段加速流出（恐慌性抛售）\n"

            absorption = s.get('absorption')
            if absorption:
                prompt += f"- **吸筹信号**: {absorption}\n"

            recent_pts = capital_flow_summary.get('recent_points', [])
            if recent_pts:
                prompt += "\n### 最近资金流快照\n"
                prompt += "| 时间 | 买入(万) | 卖出(万) | 净买入(万) | 累计净(万) | 价格 |\n"
                prompt += "|------|----------|----------|------------|------------|------|\n"
                for p in recent_pts:
                    prompt += f"| {p['time']} | {p['buy_in']} | {p['sell_in']} | {p['net_buy']} | {p['cum_net']} | {p.get('price', 'N/A')} |\n"
                prompt += "\n"

        # 11. 日内支撑/阻力位 + VWAP/POC + 经纪商席位
        if intraday_levels_data:
            prompt += "\n## 日内关键价位分析\n"

            supports = intraday_levels_data.get('support_levels', [])
            if supports:
                prompt += "### 支撑位\n"
                prompt += "| 价位 | 强度 | 类型 | 成交量 |\n"
                prompt += "|------|------|------|--------|\n"
                for lv in supports:
                    prompt += f"| {lv.get('price', 0)} | {lv.get('strength', 0)}/100 | {lv.get('label', '')} | {lv.get('volume', 0):,} |\n"
            else:
                prompt += "- **支撑位**: 无明确大单支撑（下方无托底，风险较高）\n"

            resistances = intraday_levels_data.get('resistance_levels', [])
            if resistances:
                prompt += "### 阻力位\n"
                prompt += "| 价位 | 强度 | 类型 | 成交量 |\n"
                prompt += "|------|------|------|--------|\n"
                for lv in resistances:
                    prompt += f"| {lv.get('price', 0)} | {lv.get('strength', 0)}/100 | {lv.get('label', '')} | {lv.get('volume', 0):,} |\n"

            vwap = intraday_levels_data.get('vwap', {})
            poc = intraday_levels_data.get('poc', {})
            current_price = intraday_levels_data.get('current_price', 0)
            if vwap or poc:
                prompt += "\n### 关键参考价位\n"
                if vwap:
                    prompt += f"- **VWAP**: {vwap.get('price', 0):.3f} (当前偏离: {vwap.get('deviation_pct', 0):+.2f}%)\n"
                if poc:
                    prompt += f"- **POC(最大成交密集区)**: {poc.get('price', 0):.3f}\n"
                if current_price:
                    prompt += f"- **当前价**: {current_price:.3f}\n"

            broker = intraday_levels_data.get('broker_analysis', {})
            if broker:
                prompt += "\n### 经纪商席位分析（庄家动向）\n"

                buyer_details = broker.get('buyer_details', [])
                if buyer_details:
                    prompt += "**买方席位:**\n"
                    for b in buyer_details[:6]:
                        tag = b.get('tag', '未知')
                        tag_icon = {'机构': '🏦', '散户': '👤', '北水': '🔴'}.get(tag, '❓')
                        prompt += f"- {tag_icon} {b.get('name', '')} ({tag})\n"

                seller_details = broker.get('seller_details', [])
                if seller_details:
                    prompt += "**卖方席位:**\n"
                    for sd in seller_details[:6]:
                        tag = sd.get('tag', '未知')
                        tag_icon = {'机构': '🏦', '散户': '👤', '北水': '🔴'}.get(tag, '❓')
                        prompt += f"- {tag_icon} {sd.get('name', '')} ({tag})\n"

                inst_sell = broker.get('institutional_sell_count', 0)
                retail_buy = broker.get('retail_buy_count', 0)
                is_trap = broker.get('is_trap', False)
                trap_conf = broker.get('trap_confidence', 0)
                prompt += f"\n- 机构卖出席位数: {inst_sell}\n"
                prompt += f"- 散户买入席位数: {retail_buy}\n"
                if is_trap:
                    prompt += f"- ⚠️ **出货陷阱警告**: 置信度 {trap_conf:.0%}，{broker.get('reason', '')}\n"
                elif retail_buy >= 3 and inst_sell >= 2:
                    prompt += "- ⚠️ **风险提示**: 散户接盘+机构出货的格局，需警惕\n"
                prompt += "\n"

        # 12. 输出格式要求
        prompt += """
## 输出格式（严格JSON）
请输出以下 JSON 格式，不要包含其他文字：

```json
{
  "action": "STRONG_BUY" | "BUY" | "HOLD" | "REDUCE" | "SELL" | "STRONG_SELL",
  "confidence": 0-100,
  "reasoning": "用不超过300字的简体中文，综合分析资金流动能、支撑阻力位、经纪商动向和技术面，解释为什么给出此建议",
  "key_factors": ["因素1", "因素2", "因素3", "因素4"],
  "risk_warning": "主要风险提示（简体中文），包含经纪商异常和支撑缺失等风险，无风险则为null",
  "target_price": 目标价(数字，参考阻力位)或null,
  "stop_loss_price": 止损价(数字，参考支撑位或VWAP)或null,
  "score_assessment": "对系统评分的简短评价（中文）",
  "time_horizon": "SHORT_TERM(1-3天)" | "MEDIUM_TERM(3-10天)"
}
```
"""

        # 13. 盘中狙击手数据（Sniper 排行 + 信号）
        if sniper_data:
            prompt += "\n## 盘中狙击手实时排行（双窗口评分: 3分钟+30分钟）\n"

            # 该股在排行中的位置
            pos = sniper_data.get('stock_position')
            if pos:
                pos_type = '🟢机会' if pos['type'] == 'opportunity' else '🔴风险'
                prompt += f"- **该股状态**: {pos_type} TOP {pos['rank']}\uff08得分: {pos['score']}\uff09\n"
                detail = pos.get('detail', {})
                if detail:
                    prompt += f"  - 触发窗口: {detail.get('window', '?')}分钟\n"
                    prompt += f"  - 窗口净流入: {detail.get('w_net', 0)}万\n"
                    prompt += f"  - 窗口涨跌: {detail.get('w_chg', 0):+.2f}%\n"
            else:
                prompt += "- **该股状态**: 未进入 TOP 3 排行\n"

            # 当前 TOP 3 排行（帮助 AI 了解市场全局）
            ranking = sniper_data.get('ranking', {})
            opp_top = ranking.get('opportunity', [])
            risk_top = ranking.get('risk', [])
            if opp_top:
                prompt += "\n### 当前机会 TOP 3\n"
                for item in opp_top:
                    prompt += f"- {item['stock_name']}\uff1a得分 {item['score']}, 涨跌 {item['chg']:+.2f}%\n"
            if risk_top:
                prompt += "\n### 当前风险 TOP 3\n"
                for item in risk_top:
                    prompt += f"- {item['stock_name']}\uff1a得分 {item['score']}, 涨跌 {item['chg']:+.2f}%\n"

            # 该股今日 sniper 信号
            signals = sniper_data.get('signals', [])
            if signals:
                prompt += f"\n### 该股今日狙击手信号\uff08{len(signals)}条\uff09\n"
                type_labels = {
                    'mega_sell': '巨量砸盘', 'mega_buy': '巨量抢筹',
                    'reversal_bear': '资金转负', 'reversal_bull': '资金转正',
                    'accel_in': '资金加速', 'sustained_out': '持续流出',
                }
                for sig in signals[-5:]:
                    label = type_labels.get(sig.get('signal_type', ''), sig.get('signal_type', ''))
                    prompt += f"- {sig.get('emoji', '')} [{sig.get('time', '')}] {label}: {sig.get('detail', '')}\n"
            prompt += "\n"

        # 14. 策略 Pipeline 记录（系统自身的策略判断）
        if pipeline_records:
            prompt += f"\n## 今日策略引擎记录（系统已产生的信号）\n"
            prompt += "| 时间 | 策略来源 | 方向 | 决策 | 原因 |\n"
            prompt += "|------|---------|------|------|------|\n"
            for rec in pipeline_records[-10:]:
                ts = (rec.get('timestamp', '') or '')[:16]
                prompt += (
                    f"| {ts} | {rec.get('source', '')} | {rec.get('direction', '')} | "
                    f"{rec.get('final_action', '')} | {(rec.get('final_reason', '') or '')[:60]} |\n"
                )
            prompt += "\n> ⚠️ 注意：如果策略引擎已发出 SELL 信号（如触达止盈线），请在分析中重点评估。\n"

        # 15. 近3日 Sniper 信号历史（多日模式识别）
        if sniper_history:
            type_labels = {
                'mega_sell': '巨量砸盘', 'mega_buy': '巨量抢筹',
                'reversal_bear': '资金转负', 'reversal_bull': '资金转正',
                'accel_in': '资金加速', 'sustained_out': '持续流出',
                'distribution_trap': '出货陷阱', 'accumulation_signal': '主力吸筹',
            }
            prompt += f"\n## 近3日狙击手信号历史（{len(sniper_history)}条）\n"
            prompt += "| 日期时间 | 信号类型 | 价格 |\n"
            prompt += "|---------|---------|------|\n"
            for sig in sniper_history[-20:]:
                ts = sig.get('created_at', sig.get('time', ''))[:16]
                stype = sig.get('signal_type', '')
                label = type_labels.get(stype, stype)
                prompt += f"| {ts} | {label} | {sig.get('price', 0):.3f} |\n"
            prompt += "\n> 💡 关注多日模式：如果前几天持续 mega_sell/sustained_out 而今天出现 mega_buy/reversal_bull，可能是底部反转信号。\n"

        return prompt



    async def _call_gemini(self, prompt: str) -> Optional[str]:
        """调用 Gemini API"""
        import time
        max_retries = 3

        for attempt in range(max_retries):
            try:
                logger.info(f"[AI分析] 调用 Gemini API (attempt {attempt+1}/{max_retries})，模型: {self.model_name}")
                call_start = time.time()
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.models.generate_content(
                        model=self.model_name,
                        contents=[
                            {"role": "user", "parts": [{"text": STOCK_AI_SYSTEM_PROMPT}]},
                            {"role": "model", "parts": [{"text": "明白，我将根据规则知识库和数据进行专业分���。"}]},
                            {"role": "user", "parts": [{"text": TRADING_RULES_KNOWLEDGE}]},
                            {"role": "model", "parts": [{"text": "已理解全部交易规则，请提供股票数据。"}]},
                            {"role": "user", "parts": [{"text": prompt}]},
                        ]
                    )
                )

                call_elapsed = time.time() - call_start
                if response and response.text:
                    logger.info(f"[AI分析] Gemini API 调用成功，耗时: {call_elapsed:.1f}s")
                    return response.text.strip()
                logger.warning(f"[AI分析] Gemini API 返回空文本，耗时: {call_elapsed:.1f}s")
                return None

            except Exception as e:
                err_str = str(e)
                if ('503' in err_str or '429' in err_str or 'UNAVAILABLE' in err_str) \
                        and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        f"Gemini API 暂时不可用 (attempt {attempt+1}/{max_retries})，"
                        f"{wait}s 后重试: {err_str[:100]}"
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"调用 Gemini API 失败: {e}")
                return None

    def _normalize_result(
        self, data: Optional[Dict[str, Any]], stock_code: str, stock_name: str
    ) -> Optional[Dict[str, Any]]:
        """标准化结构化结果（Claude 结构化输出 / Gemini 解析后通用）。"""
        if not data:
            return None
        try:
            action = data.get('action', 'HOLD')
            valid_actions = {
                'STRONG_BUY', 'BUY', 'HOLD', 'REDUCE', 'SELL', 'STRONG_SELL',
            }
            if action not in valid_actions:
                action = 'HOLD'

            try:
                confidence = min(100, max(0, int(data.get('confidence', 50))))
            except (TypeError, ValueError):
                confidence = 50

            key_factors = data.get('key_factors') or []
            if not isinstance(key_factors, list):
                key_factors = []

            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'action': action,
                'confidence': confidence,
                'reasoning': data.get('reasoning', ''),
                'key_factors': key_factors[:5],
                'risk_warning': data.get('risk_warning'),
                'target_price': data.get('target_price'),
                'stop_loss_price': data.get('stop_loss_price'),
                'score_assessment': data.get('score_assessment', ''),
                'time_horizon': data.get('time_horizon', 'SHORT_TERM'),
                'analyzed_at': datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"标准化 AI 结果失败: {e}, data={str(data)[:300]}")
            return None

    def _parse_response(
        self, response: str, stock_code: str, stock_name: str
    ) -> Optional[Dict[str, Any]]:
        """解析 Gemini 文本响应（剥 markdown 取 JSON）后标准化。"""
        try:
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            data = json.loads(json_str)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"解析 AI 响应失败: {e}, response={response[:300]}")
            return None
        return self._normalize_result(data, stock_code, stock_name)

    def _get_cached(self, stock_code: str) -> Optional[Dict]:
        """获取缓存的分析结果"""
        cached = self._cache.get(stock_code)
        if not cached:
            return None
        ts = datetime.fromisoformat(cached['timestamp'])
        age = (datetime.now() - ts).total_seconds()
        if age > self._cache_ttl:
            del self._cache[stock_code]
            logger.debug(f"[AI分析] {stock_code} 缓存已过期 ({age:.0f}s > {self._cache_ttl}s)")
            return None
        action = cached['data'].get('action', '?')
        logger.info(f"[AI分析] {stock_code} 命中缓存 (建议: {action}，缓存年龄: {age:.0f}s)")
        return {'success': True, 'data': cached['data'], 'from_cache': True}

    def clear_cache(self, stock_code: str = None):
        """清除缓存"""
        if stock_code:
            self._cache.pop(stock_code, None)
        else:
            self._cache.clear()
