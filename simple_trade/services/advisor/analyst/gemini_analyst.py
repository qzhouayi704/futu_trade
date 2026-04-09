#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gemini 量化分析师 - 核心分析引擎

基于 Gemini AI 的短线量化分析师，
接收预处理后的技术指标、资金流向、新闻等数据，
输出结构化的交易建议。
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

from .analyst_models import (
    AnalystAction, AnalystInput, AnalystOutput,
    MarketContext, NewsSummary, TriggerEvent,
)
from .analyst_prompt import SYSTEM_PROMPT, AnalystPromptBuilder
from .trigger_detector import TriggerDetector

logger = logging.getLogger(__name__)


# 港股交易时间
HK_MARKET_OPEN_HOUR = 9
HK_MARKET_OPEN_MINUTE = 30
HK_LUNCH_START_HOUR = 12
HK_LUNCH_END_HOUR = 13
HK_MARKET_CLOSE_HOUR = 16


class GeminiAnalyst:
    """Gemini 量化分析师"""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3-flash-preview",
        technical_service=None,
        config: Optional[dict] = None,
        proxy: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model_name = model
        self.client = None
        self._technical = technical_service
        self._config = config or {}

        # 初始化 Gemini 客户端
        if GEMINI_AVAILABLE and api_key:
            try:
                # 设置代理
                if proxy:
                    import os
                    os.environ['https_proxy'] = proxy
                    os.environ['http_proxy'] = proxy
                    logger.info(f"Gemini 使用代理: {proxy}")

                self.client = genai.Client(api_key=api_key)
                logger.info(f"Gemini 量化分析师初始化成功，模型: {model}")
            except Exception as e:
                logger.error(f"Gemini 分析师初始化失败: {e}")

        # 触发检测器
        self.trigger_detector = TriggerDetector(config)

        # 分析结果缓存
        self._analysis_cache: Dict[str, AnalystOutput] = {}
        self._cache_ttl = self._config.get('cache_ttl', 300)

    def is_available(self) -> bool:
        """检查服务是否可用"""
        return GEMINI_AVAILABLE and self.client is not None

    async def analyze(
        self,
        trigger: TriggerEvent,
        position_health: Optional[Dict] = None,
        quote: Optional[Dict] = None,
        klines: Optional[List] = None,
        rule_advice: Optional[Dict] = None,
        news_data: Optional[Dict] = None,
        market_data: Optional[Dict] = None,
        sector_info: Optional[str] = None,
        capital_flow_data: Optional[Dict] = None,
    ) -> Optional[AnalystOutput]:
        """执行单只股票的深度分析（含K线走势、板块、资金流等多维数据）"""
        if not self.is_available():
            logger.warning("Gemini 不可用，跳过分析")
            return None

        try:
            # 1. 获取技术指标
            tech_indicators = None
            if self._technical and quote:
                tech_indicators = await self._technical.get_indicators(
                    trigger.stock_code, quote, klines or []
                )

            if not tech_indicators:
                from simple_trade.services.market_data.technical_service import TechnicalIndicators
                tech_indicators = TechnicalIndicators(
                    stock_code=trigger.stock_code,
                    current_price=quote.get('last_price', 0) if quote else 0,
                    change_pct=quote.get('change_rate', 0) if quote else 0,
                )

            # 2. 构建市场上下文
            market_ctx = self._build_market_context(market_data)

            # 3. 构建新闻摘要
            news_summary = self._build_news_summary(news_data) if news_data else None

            # 4. 构建增强数据
            kline_summary = self._build_kline_summary(klines) if klines else None
            capital_flow_summary = self._build_capital_flow_summary(capital_flow_data) if capital_flow_data else None

            # 5. 构建输入数据包
            input_data = AnalystInput(
                stock_code=trigger.stock_code,
                stock_name=trigger.stock_name,
                trigger_type=trigger.trigger_type,
                trigger_reason=trigger.reason,
                market_context=market_ctx,
                technical=tech_indicators,
                position_health=position_health or {},
                news=news_summary,
                rule_advice=rule_advice,
                kline_summary=kline_summary,
                sector_info=sector_info,
                capital_flow_summary=capital_flow_summary,
            )

            # 6. 构建 Prompt
            prompt = AnalystPromptBuilder.build_prompt(input_data)

            # 7. 调用 Gemini API
            response = await self._call_gemini(prompt)
            if not response:
                return None

            # 8. 解析响应
            output = self._parse_response(
                response, trigger.stock_code, trigger.stock_name
            )

            # 9. 缓存结果 + 标记冷却
            if output:
                self._analysis_cache[trigger.stock_code] = output
                self.trigger_detector.mark_triggered(trigger.stock_code)

            return output

        except Exception as e:
            logger.error(f"Gemini 分析失败 {trigger.stock_code}: {e}", exc_info=True)
            return None

    async def _call_gemini(self, prompt: str) -> Optional[str]:
        """调用 Gemini API（含重试逻辑，应对503/网络不稳定）"""
        import time
        max_retries = self._config.get('max_retries', 3)

        for attempt in range(max_retries):
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: self.client.models.generate_content(
                        model=self.model_name,
                        contents=[
                            {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                            {"role": "model", "parts": [{"text": "明白，我将作为综合持仓顾问进行多维度分析。"}]},
                            {"role": "user", "parts": [{"text": prompt}]},
                        ]
                    )
                )

                if response and response.text:
                    return response.text.strip()
                return None

            except Exception as e:
                err_str = str(e)
                # 503 (高负载) 或 429 (频率限制) → 重试
                if ('503' in err_str or '429' in err_str or 'UNAVAILABLE' in err_str) and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)  # 2s, 4s
                    logger.warning(f"Gemini API 暂时不可用 (attempt {attempt+1}/{max_retries})，{wait}s 后重试: {err_str[:100]}")
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"调用 Gemini API 失败: {e}")
                return None

    def _parse_response(
        self, response: str, stock_code: str, stock_name: str
    ) -> Optional[AnalystOutput]:
        """解析 Gemini 响应"""
        try:
            # 提取 JSON
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()

            data = json.loads(json_str)

            # 映射 action
            action_str = data.get('suggested_action', 'WAIT')
            try:
                action = AnalystAction(action_str)
            except ValueError:
                action = AnalystAction.WAIT

            return AnalystOutput(
                stock_code=stock_code,
                stock_name=stock_name,
                catalyst_impact=data.get('catalyst_impact', 'Neutral'),
                smart_money_alignment=data.get('smart_money_alignment', 'Unclear'),
                is_priced_in=data.get('is_priced_in', False),
                alpha_signal_score=float(data.get('alpha_signal_score', 0)),
                action=action,
                confidence=float(data.get('confidence', 0)),
                reasoning=data.get('rationale', ''),
                key_factors=data.get('key_factors', []),
                risk_warning=data.get('risk_warning'),
                target_price=data.get('target_price'),
                stop_loss_price=data.get('stop_loss_price'),
                time_horizon="INTRADAY",
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"解析 Gemini 响应失败: {e}, response={response[:200]}")
            return None

    def _build_market_context(self, market_data: Optional[Dict] = None) -> MarketContext:
        """构建市场上下文"""
        now = datetime.now()
        session = self._get_trading_session(now)
        minutes = self._minutes_since_open(now)

        hsi_change = 0.0
        sentiment = "NEUTRAL"
        sector_sentiment = {}

        if market_data:
            hsi_change = market_data.get('hsi_change_pct', 0)
            sentiment = market_data.get('sentiment', 'NEUTRAL')
            sector_sentiment = market_data.get('sector_sentiment', {})

        if not sentiment or sentiment == "NEUTRAL":
            if hsi_change > 1:
                sentiment = "BULLISH"
            elif hsi_change < -1:
                sentiment = "BEARISH"

        return MarketContext(
            timestamp=now,
            trading_session=session,
            minutes_since_open=minutes,
            market_sentiment=sentiment,
            hsi_change_pct=hsi_change,
            sector_sentiment=sector_sentiment,
        )

    @staticmethod
    def _get_trading_session(now: datetime) -> str:
        """判断当前交易时段"""
        hour, minute = now.hour, now.minute
        time_val = hour * 60 + minute

        open_time = HK_MARKET_OPEN_HOUR * 60 + HK_MARKET_OPEN_MINUTE
        lunch_start = HK_LUNCH_START_HOUR * 60
        lunch_end = HK_LUNCH_END_HOUR * 60
        close_time = HK_MARKET_CLOSE_HOUR * 60

        if time_val < open_time:
            return "PRE_MARKET"
        elif time_val < lunch_start:
            return "MORNING"
        elif time_val < lunch_end:
            return "LUNCH"
        elif time_val < close_time:
            return "AFTERNOON"
        return "AFTER_HOURS"

    @staticmethod
    def _minutes_since_open(now: datetime) -> int:
        """计算开盘后分钟数"""
        open_minutes = HK_MARKET_OPEN_HOUR * 60 + HK_MARKET_OPEN_MINUTE
        current_minutes = now.hour * 60 + now.minute
        return max(0, current_minutes - open_minutes)

    @staticmethod
    def _build_news_summary(news_data: Dict) -> Optional[NewsSummary]:
        """构建新闻摘要"""
        if not news_data:
            return None
        return NewsSummary(
            has_breaking_news=news_data.get('is_breaking', False),
            sentiment=news_data.get('sentiment', 'NEUTRAL'),
            sentiment_score=news_data.get('sentiment_score', 0),
            key_facts=news_data.get('key_facts', [])[:3],
            related_stocks=news_data.get('related_stocks', []),
        )

    @staticmethod
    def _build_kline_summary(klines: List) -> Optional[str]:
        """从K线数据中提取近12日走势摘要供 Gemini 分析"""
        if not klines:
            return None
        try:
            recent = klines[-12:] if len(klines) >= 12 else klines
            lines = []
            for k in recent:
                date = k.get('time_key', k.get('date', '?'))
                o = k.get('open', 0)
                h = k.get('high', 0)
                l = k.get('low', 0)
                c = k.get('close', 0)
                vol = k.get('volume', 0)
                chg = ((c - o) / o * 100) if o > 0 else 0
                lines.append(f"{date}: O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f} Vol={vol} Chg={chg:+.2f}%")

            # 计算区间涨跌幅
            first_close = recent[0].get('close', 0) or recent[0].get('open', 0)
            last_close = recent[-1].get('close', 0)
            period_chg = ((last_close - first_close) / first_close * 100) if first_close > 0 else 0

            # 简单 MA 计算
            closes = [k.get('close', 0) for k in recent if k.get('close', 0) > 0]
            ma5 = sum(closes[-5:]) / min(5, len(closes)) if closes else 0
            ma10 = sum(closes[-10:]) / min(10, len(closes)) if closes else 0

            summary = "\n".join(lines)
            summary += f"\n--- 近{len(recent)}日区间涨跌幅: {period_chg:+.2f}%"
            summary += f" | MA5={ma5:.2f} MA10={ma10:.2f}"
            if last_close > 0:
                summary += f" | 当前价距MA5: {(last_close/ma5-1)*100:+.1f}%" if ma5 > 0 else ""
                summary += f", 距MA10: {(last_close/ma10-1)*100:+.1f}%" if ma10 > 0 else ""
            return summary
        except Exception as e:
            logger.warning(f"构建K线摘要失败: {e}")
            return None

    @staticmethod
    def _build_capital_flow_summary(data: Dict) -> Optional[str]:
        """从资金流数据构建摘要"""
        if not data:
            return None
        try:
            parts = []
            main_inflow = data.get('main_net_inflow', 0)
            if main_inflow:
                direction = "净流入" if main_inflow > 0 else "净流出"
                parts.append(f"主力资金{direction}: {abs(main_inflow)/10000:.1f}万")

            big_buy = data.get('big_buy_ratio', 0)
            big_sell = data.get('big_sell_ratio', 0)
            if big_buy or big_sell:
                parts.append(f"大单买占比: {big_buy:.1f}%, 大单卖占比: {big_sell:.1f}%")

            score = data.get('capital_score', 0)
            if score:
                parts.append(f"资金评分: {score:.0f}/100")

            net_ratio = data.get('net_inflow_ratio', 0)
            if net_ratio:
                parts.append(f"净流入占比: {net_ratio:+.2f}%")

            return " | ".join(parts) if parts else None
        except Exception as e:
            logger.warning(f"构建资金流摘要失败: {e}")
            return None

    def get_cached_analysis(self, stock_code: str) -> Optional[AnalystOutput]:
        """获取缓存的分析结果"""
        cached = self._analysis_cache.get(stock_code)
        if cached and (datetime.now() - cached.created_at).total_seconds() < self._cache_ttl:
            return cached
        return None

    def get_all_cached(self) -> Dict[str, AnalystOutput]:
        """获取所有缓存的分析结果"""
        now = datetime.now()
        return {
            code: output for code, output in self._analysis_cache.items()
            if (now - output.created_at).total_seconds() < self._cache_ttl
        }
