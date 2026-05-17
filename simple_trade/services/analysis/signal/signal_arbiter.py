#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SignalArbiter — 多策略信号仲裁器

职责：
- 收集多个策略引擎对同一只股票的评分结果
- 计算策略共识度（consensus）
- 输出最终综合判定 + 置信度

设计原则：
- 纯函数：输入各策略评分，输出共识结果
- 不依赖任何数据源，只依赖 StockSnapshot 和各策略的评分结果
- 矛盾信号自动衰减，而非简单取平均
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class Verdict(str, Enum):
    """最终判定"""
    STRONG_BUY = "strong_buy"       # 强烈买入
    BUY = "buy"                     # 买入
    WATCH = "watch"                 # 观望
    SELL = "sell"                   # 卖出
    STRONG_SELL = "strong_sell"     # 强烈卖出
    CONFLICTING = "conflicting"    # 信号矛盾


VERDICT_LABELS = {
    Verdict.STRONG_BUY: "🟢 强烈买入",
    Verdict.BUY: "🔵 买入",
    Verdict.WATCH: "⚪ 观望",
    Verdict.SELL: "🟡 卖出",
    Verdict.STRONG_SELL: "🔴 强烈卖��",
    Verdict.CONFLICTING: "⚠️ 矛盾",
}


@dataclass
class StrategyVote:
    """单个策略的投票"""
    strategy_name: str          # 策略名称
    score: float                # 评分（标准化到 0-100）
    signal: str                 # bullish / bearish / neutral
    weight: float = 1.0         # 权重
    passed: bool = True         # 是否通过该策略的筛选
    detail: str = ""            # 简要说明


@dataclass
class ConsensusResult:
    """共识结果"""
    stock_code: str
    stock_name: str

    # 共识指标
    verdict: Verdict = Verdict.WATCH                 # 最终判定
    verdict_label: str = ""                 # 中文标签
    consensus_score: float = 0.0            # 共识评分 0-100
    confidence: float = 0.0                 # 置信度 0-1（一致性越高越大）
    bullish_count: int = 0                  # 看多策略数
    bearish_count: int = 0                  # 看空策略数
    neutral_count: int = 0                  # 中性策略数
    total_strategies: int = 0               # 参与策略总数

    # 各策略投票明细
    votes: List[StrategyVote] = field(default_factory=list)

    # 否决信息
    vetoed: bool = False
    veto_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'verdict': self.verdict.value,
            'verdict_label': self.verdict_label,
            'consensus_score': round(self.consensus_score, 1),
            'confidence': round(self.confidence, 2),
            'bullish_count': self.bullish_count,
            'bearish_count': self.bearish_count,
            'neutral_count': self.neutral_count,
            'total_strategies': self.total_strategies,
            'vetoed': self.vetoed,
            'veto_reason': self.veto_reason,
            'votes': [
                {
                    'strategy': v.strategy_name,
                    'score': round(v.score, 1),
                    'signal': v.signal,
                    'weight': v.weight,
                    'passed': v.passed,
                    'detail': v.detail,
                }
                for v in self.votes
            ],
        }


class SignalArbiter:
    """多策略信号仲裁器"""

    # 策略权重（可配置）
    DEFAULT_WEIGHTS = {
        'screener': 1.0,        # stock_scorer 选股评分
        'capital': 1.2,         # capital_score 资金评分（略高权重，最强预测力）
        'price_position': 0.8,  # 价格位置信号
        'overnight': 1.0,       # 盘后优选
        'ticker': 0.9,          # 成交分析
        'breakout': 0.7,        # 突破扫描
    }

    def __init__(self, weights: Dict[str, float] = None):
        self.weights = weights or self.DEFAULT_WEIGHTS

    def arbitrate(
        self,
        stock_code: str,
        stock_name: str,
        votes: List[StrategyVote],
        veto_reason: str = "",
    ) -> ConsensusResult:
        """
        对一只股票执行多策略共识仲裁

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            votes: 各策略的投票列表
            veto_reason: 一票否决原因（来自 stock_scorer）

        Returns:
            ConsensusResult 共识结果
        """
        result = ConsensusResult(
            stock_code=stock_code,
            stock_name=stock_name,
            votes=votes,
            total_strategies=len(votes),
        )

        # 一票否决
        if veto_reason:
            result.vetoed = True
            result.veto_reason = veto_reason
            result.verdict = Verdict.STRONG_SELL
            result.verdict_label = VERDICT_LABELS[Verdict.STRONG_SELL]
            result.confidence = 1.0
            return result

        if not votes:
            result.verdict = Verdict.WATCH
            result.verdict_label = VERDICT_LABELS[Verdict.WATCH]
            return result

        # 统计多空
        for v in votes:
            if v.signal == "bullish":
                result.bullish_count += 1
            elif v.signal == "bearish":
                result.bearish_count += 1
            else:
                result.neutral_count += 1

        # 加权平均分
        total_weight = 0
        weighted_score = 0
        for v in votes:
            w = self.weights.get(v.strategy_name, 1.0) * v.weight
            weighted_score += v.score * w
            total_weight += w

        if total_weight > 0:
            result.consensus_score = weighted_score / total_weight

        # 置信度 = 一致性
        # 全部看多/看空 → 1.0，完全分裂 → 0.0
        n = len(votes)
        if n > 0:
            max_direction = max(result.bullish_count, result.bearish_count, result.neutral_count)
            result.confidence = max_direction / n

        # 矛盾检测：同时有看多和看空
        has_contradiction = result.bullish_count > 0 and result.bearish_count > 0

        # 最终判定
        if has_contradiction and result.confidence < 0.6:
            result.verdict = Verdict.CONFLICTING
        elif result.consensus_score >= 75 and result.bullish_count >= result.bearish_count:
            result.verdict = Verdict.STRONG_BUY
        elif result.consensus_score >= 60 and result.bullish_count > result.bearish_count:
            result.verdict = Verdict.BUY
        elif result.consensus_score <= 30 and result.bearish_count > result.bullish_count:
            result.verdict = Verdict.STRONG_SELL
        elif result.consensus_score <= 45 and result.bearish_count >= result.bullish_count:
            result.verdict = Verdict.SELL
        else:
            result.verdict = Verdict.WATCH

        # 矛盾时衰减置信度
        if has_contradiction:
            result.confidence *= 0.5

        result.verdict_label = VERDICT_LABELS[result.verdict]

        logger.info(
            f"[仲裁] {stock_code}: {result.verdict_label} "
            f"score={result.consensus_score:.1f} conf={result.confidence:.2f} "
            f"多{result.bullish_count}/空{result.bearish_count}/中{result.neutral_count}"
        )

        return result

    def arbitrate_from_snapshot(self, snapshot, scorer_result=None,
                                overnight_result=None) -> ConsensusResult:
        """
        便捷方法：从 StockSnapshot + 各策略结果直接仲裁

        Args:
            snapshot: StockSnapshot
            scorer_result: StockScorer.score_snapshot() 的结果
            overnight_result: OvernightCandidate
        """
        votes = []

        # 资金信号（来自 Snapshot）
        cap_signal = snapshot.capital_signal_simple
        votes.append(StrategyVote(
            strategy_name="capital",
            score=snapshot.capital_score,
            signal=cap_signal,
            detail=f"资金评分{snapshot.capital_score:.0f}",
        ))

        # 选股评分（来自 scorer）
        if scorer_result:
            signal = "bullish" if scorer_result.passed else (
                "bearish" if scorer_result.total_score < 40 else "neutral"
            )
            votes.append(StrategyVote(
                strategy_name="screener",
                score=scorer_result.total_score,
                signal=signal,
                passed=scorer_result.passed,
                detail=f"标的评分{scorer_result.total_score}",
            ))

        # 成交分析（来自 Snapshot）
        if snapshot.ticker_score is not None:
            t_signal = snapshot.ticker_signal or "neutral"
            # ticker_score 是 -100~+100，归一化到 0-100
            t_normalized = (snapshot.ticker_score + 100) / 2
            votes.append(StrategyVote(
                strategy_name="ticker",
                score=t_normalized,
                signal=t_signal,
                detail=f"成交分析{snapshot.ticker_score:+.0f}",
            ))

        # 盘后优选（如果有）
        if overnight_result and hasattr(overnight_result, 'total_score'):
            o_signal = "bullish" if overnight_result.total_score >= 60 else (
                "bearish" if overnight_result.total_score < 30 else "neutral"
            )
            votes.append(StrategyVote(
                strategy_name="overnight",
                score=overnight_result.total_score,
                signal=o_signal,
                detail=f"盘后{overnight_result.verdict}" if hasattr(overnight_result, 'verdict') else "",
            ))

        veto = scorer_result.veto_reason if scorer_result else ""
        return self.arbitrate(snapshot.code, snapshot.name, votes, veto)
