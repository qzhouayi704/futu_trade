#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini 量化分析师 Prompt 模板

综合持仓顾问角色：基于多维数据（K线走势、资金流向、板块信息等）
给出止损/止盈/加仓/减仓/持有的智能决策建议。
"""

from .analyst_models import AnalystInput, MarketContext


SYSTEM_PROMPT = """# Role Definition
You are a Senior Portfolio Advisor for Hong Kong & US equities. Your job is to \
analyze a HELD POSITION using multi-dimensional data and decide the optimal action.

# Core Responsibility
For each position, evaluate whether to: HOLD, ADD (加仓), REDUCE (减仓), \
TAKE_PROFIT (止盈), STOP_LOSS (止损), or STRONG_SELL (强卖).

DO NOT blindly recommend stop-loss just because losses exceed a threshold. \
Instead, analyze the full picture:
- Is the stock in a medium-term uptrend despite short-term pullback?
- Is smart money accumulating or distributing?
- Is the sector/plate performing well?
- Are there catalysts that could reverse the trend?
- Is the pullback healthy (to support levels) or a breakdown?

# Analysis Framework
1. **Trend Analysis:** Use 12-day K-line trend, MA positions, and price patterns \
to determine if this is a temporary pullback or a trend reversal.
2. **Capital Flow:** Confirm if institutional money (large orders) supports or \
contradicts the price action.
3. **Sector Context:** Is the sector strong? A stock in a hot sector has higher \
recovery probability.
4. **Risk-Reward:** Given current P&L, holding days, and trend, what is the \
optimal action?
5. **Time Sensitivity:** Consider the trading session and holding duration.

# Language Requirement
All text fields in your JSON output (rationale, risk_warning, key_factors, \
position_action_rationale) MUST be written in Simplified Chinese (简体中文).
"""


# 交易时段中文映射
SESSION_LABELS = {
    "PRE_MARKET": "盘前",
    "MORNING": "早盘",
    "LUNCH": "午休",
    "AFTERNOON": "午盘",
    "AFTER_HOURS": "盘后",
}


class AnalystPromptBuilder:
    """分析师 Prompt 构建器"""

    @classmethod
    def build_prompt(cls, input_data: AnalystInput) -> str:
        """构建完整的分析 Prompt"""
        tech = input_data.technical
        ctx = input_data.market_context
        news = input_data.news
        health = input_data.position_health or {}
        rule = input_data.rule_advice

        # 新闻部分
        news_breaking = news.has_breaking_news if news else False
        news_sentiment = news.sentiment if news else "N/A"
        news_score = f"{news.sentiment_score:+.2f}" if news else "0.00"
        news_facts = "; ".join(news.key_facts[:3]) if news and news.key_facts else "无"

        # 资金描述
        strength_desc = cls._get_strength_desc(tech.big_order_strength)
        imbalance_desc = cls._get_imbalance_desc(tech.order_imbalance)

        # 板块情绪
        sector_str = ", ".join(
            f"{k}:{v}" for k, v in ctx.sector_sentiment.items()
        ) if ctx.sector_sentiment else "N/A"

        # 规则引擎建议
        rule_type = rule.get('advice_type', 'N/A') if rule else "N/A"
        rule_urgency = rule.get('urgency', 'N/A') if rule else "N/A"
        rule_desc = rule.get('description', 'N/A') if rule else "N/A"

        # VWAP 位置
        vwap_pos = "ABOVE" if tech.current_price > tech.vwap and tech.vwap > 0 else "BELOW"

        # K线走势摘要
        kline_section = input_data.kline_summary or "暂无K线数据"

        # 板块信息
        sector_section = input_data.sector_info or "暂无板块数据"

        # 资金流向摘要
        capital_section = input_data.capital_flow_summary or "暂无资金流数据"

        return f"""# Input Data
- **Asset:** {input_data.stock_code} ({input_data.stock_name})
- **Trigger:** {input_data.trigger_type.value} - {input_data.trigger_reason}

**1. Position Status (持仓状态):**
- Health Level: {health.get('health_level', 'N/A')}
- Health Score: {health.get('score', 0):.1f}/100
- Current P&L: {health.get('profit_pct', 0):+.2f}%
- Holding Days: {health.get('holding_days', 0)}
- Trend: {health.get('trend', 'N/A')}
- Reasons: {', '.join(health.get('reasons', [])) or 'N/A'}

**2. Time Context:**
- Timestamp: {ctx.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
- Trading Session: {SESSION_LABELS.get(ctx.trading_session, ctx.trading_session)}
- Minutes Since Open: {ctx.minutes_since_open}
- Session Hint: {cls._get_session_hint(ctx)}

**3. Price Action & Technicals:**
- Current Price: {tech.current_price:.3f}
- Change: {tech.change_pct:+.2f}%
- VWAP: {tech.vwap:.3f} (Deviation: {tech.vwap_deviation:+.2f}%)
- Price vs VWAP: {vwap_pos}
- Trend: {tech.trend}
- MA Positions: MA5={tech.price_vs_ma5}, MA10={tech.price_vs_ma10}, MA20={tech.price_vs_ma20}
- RSI(14): {tech.rsi_14:.1f} ({tech.rsi_signal})
- Volume Ratio: {tech.volume_ratio:.2f}
- Turnover Rate: {tech.turnover_rate:.2f}%

**4. K-Line Trend (近12日走势):**
{kline_section}

**5. Micro-structure & Capital Flow:**
- Capital Score: {tech.capital_score:.1f}/100
- Large Order Net Inflow: {tech.main_net_inflow / 10000:+.1f}万 HKD
- Big Order Strength: {tech.big_order_strength:+.2f} ({strength_desc})
- Order Book Imbalance: {tech.order_imbalance:+.2f} ({imbalance_desc})
- Bid-Ask Spread: {tech.spread_pct:.3f}%

**6. Capital Flow Summary (资金流向概览):**
{capital_section}

**7. Sector / Plate Context (板块信息):**
{sector_section}

**8. Catalyst / News:**
- Has Breaking News: {news_breaking}
- News Sentiment: {news_sentiment} (Score: {news_score})
- Key Facts: {news_facts}

**9. Market Context:**
- Market Sentiment: {ctx.market_sentiment}
- HSI Change: {ctx.hsi_change_pct:+.2f}%
- Sector Sentiment: {sector_str}

**10. Rule Engine Advice (规则引擎参考):**
- Type: {rule_type}
- Urgency: {rule_urgency}
- Description: {rule_desc}
> Note: The rule engine uses fixed thresholds. You should evaluate whether its \
advice is correct based on the full context above.

# Output Format (Strict JSON)
Output ONLY a valid JSON object.

{{
  "catalyst_impact": "Bullish" | "Bearish" | "Neutral",
  "smart_money_alignment": "Confirming" | "Diverging" | "Unclear",
  "is_priced_in": true or false,
  "alpha_signal_score": -1.0 to 1.0,
  "suggested_action": "STRONG_BUY" | "BUY" | "HOLD" | "REDUCE" | "SELL" | "STRONG_SELL" | "WAIT",
  "confidence": 0.0 to 1.0,
  "target_price": number or null,
  "stop_loss_price": number or null,
  "risk_warning": "风险提示（中文）或 null",
  "rationale": "用不超过120字的简体中文，综合K线走势、资金流向、板块表现，解释为什么建议该操作。",
  "position_action_rationale": "用简体中文，针对当前持仓，解释为什么不应/应该止损，或应该加仓/减仓/持有。",
  "key_factors": ["关键因素1（中文）", "关键因素2（中文）", "关键因素3（中文）"]
}}
"""

    @classmethod
    def _get_session_hint(cls, ctx: MarketContext) -> str:
        """根据交易时段给出提示"""
        if ctx.trading_session == "MORNING" and ctx.minutes_since_open < 30:
            return "开盘波动期，警惕假突破"
        elif ctx.trading_session == "MORNING" and ctx.minutes_since_open < 60:
            return "早盘趋势形成中"
        elif ctx.trading_session == "AFTERNOON" and ctx.minutes_since_open > 180:
            return "尾盘阶段，避免追涨，注意获利了结"
        elif ctx.trading_session == "LUNCH":
            return "午休时段，不交易"
        return "正常交易时段"

    @staticmethod
    def _get_strength_desc(strength: float) -> str:
        if strength > 0.3:
            return "主力买入强劲"
        elif strength < -0.3:
            return "主力卖出明显"
        return "多空均衡"

    @staticmethod
    def _get_imbalance_desc(imbalance: float) -> str:
        if imbalance > 0.3:
            return "买盘支撑强"
        elif imbalance < -0.3:
            return "卖压较大"
        return "盘口均衡"
