"""
流动性评分计算器

基于多维度指标计算股票流动性评分，用于筛选高流动性股票。

评分维度：
- 成交量（30%）
- 换手率（25%）
- 成交额（20%）
- 振幅（15%）
- 历史稳定性（10%）

流动性等级：
- A级（高流动性）：score >= 70
- B级（中等流动性）：50 <= score < 70
- C级（低流动性）：30 <= score < 50
- D级（极低流动性）：score < 30（过滤）
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import numpy as np

from simple_trade.utils.converters import get_last_price


logger = logging.getLogger(__name__)


# 港股流动性阈值
HK_LIQUIDITY_THRESHOLDS = {
    # 基础阈值（必须满足）
    "min_volume": 500_000,              # 最低成交量：50万股
    "min_turnover_rate": 0.1,           # 最低换手率：0.1%
    "min_turnover_amount": 1_000_000,   # 最低成交额：100万港元
    "min_price": 1.0,                   # 最低价格：1港元
    "min_amplitude": 0.5,               # 最低振幅：0.5%

    # 优秀阈值（用于评分）
    "excellent_volume": 5_000_000,      # 优秀成交量：500万股
    "excellent_turnover_rate": 2.0,     # 优秀换手率：2%
    "excellent_amount": 50_000_000,     # 优秀成交额：5000万港元

    # 历史稳定性
    "history_days": 5,                  # 历史数据天数
    "max_volume_cv": 1.5,               # 最大成交量变异系数（CV）
    "max_turnover_cv": 1.5,             # 最大换手率变异系数
}

# 美股流动性阈值
US_LIQUIDITY_THRESHOLDS = {
    "min_volume": 3_000_000,            # 最低成交量：300万股
    "min_turnover_rate": 0.5,           # 最低换手率：0.5%
    "min_turnover_amount": 5_000_000,   # 最低成交额：500万美元
    "min_price": 0,                     # 美股不设价格下限
    "min_amplitude": 1.0,               # 最低振幅：1%
    "excellent_volume": 20_000_000,     # 优秀成交量：2000万股
    "excellent_turnover_rate": 5.0,     # 优秀换手率：5%
    "excellent_amount": 100_000_000,    # 优秀成交额：1亿美元
    "history_days": 5,
    "max_volume_cv": 1.2,               # 美股流动性更稳定
    "max_turnover_cv": 1.2,
}


class LiquidityCalculator:
    """流动性评分计算器"""

    def __init__(self, db_manager, config: Optional[Dict] = None):
        """
        初始化流动性计算器

        Args:
            db_manager: 数据库管理器
            config: 配置字典（可选）
        """
        self.db_manager = db_manager
        self.config = config or {}
        self.logger = logging.getLogger(__name__)

    def get_thresholds(self, market: str) -> Dict:
        """获取市场对应的流动性阈值"""
        if market == "HK":
            return HK_LIQUIDITY_THRESHOLDS
        elif market == "US":
            return US_LIQUIDITY_THRESHOLDS
        return HK_LIQUIDITY_THRESHOLDS

    async def calculate_liquidity_score(
        self,
        stock_code: str,
        quote: Dict,
        include_history: bool = True
    ) -> Dict:
        """
        计算流动性评分

        Args:
            stock_code: 股票代码
            quote: 实时报价数据
            include_history: 是否包含历史稳定性检查

        Returns:
            {
                'liquidity_score': 82.5,
                'liquidity_level': 'A',
                'volume_score': 85.0,
                'turnover_rate_score': 90.0,
                'amount_score': 80.0,
                'amplitude_score': 75.0,
                'stability_score': 88.0,
                'is_volume_anomaly': False,
                'pass_threshold': True,
            }
        """
        market = "HK" if stock_code.startswith("HK.") else "US"
        thresholds = self.get_thresholds(market)

        # 1. 当前指标评分
        volume = quote.get('volume', 0) or 0
        turnover_rate = quote.get('turnover_rate', 0) or 0
        turnover_amount = quote.get('turnover', 0) or 0
        amplitude = quote.get('amplitude', 0) or 0

        volume_score = self._score_volume(volume, thresholds)
        turnover_rate_score = self._score_turnover_rate(turnover_rate, thresholds)
        amount_score = self._score_amount(turnover_amount, thresholds)
        amplitude_score = self._score_amplitude(amplitude)

        # 2. 历史稳定性评分
        stability_score = 50.0  # 默认中性分
        is_anomaly = False
        kline_data_missing = False

        if include_history:
            try:
                hist_data = await self.get_historical_liquidity_data(
                    stock_code, thresholds['history_days']
                )
                if hist_data:
                    stability_score = self.calculate_stability_score(hist_data, thresholds)
                    is_anomaly = self.detect_volume_anomaly(hist_data, volume)
                else:
                    kline_data_missing = True
            except Exception as e:
                self.logger.warning(f"历史稳定性计算失败 {stock_code}: {e}")

        # 3. 综合评分
        liquidity_score = (
            volume_score * 0.30 +
            turnover_rate_score * 0.25 +
            amount_score * 0.20 +
            amplitude_score * 0.15 +
            stability_score * 0.10
        )

        # 4. 异常惩罚
        if is_anomaly:
            liquidity_score *= 0.5  # 异常放大时评分减半

        # 5. 等级判定
        level = self._get_liquidity_level(liquidity_score)

        return {
            'liquidity_score': round(liquidity_score, 2),
            'liquidity_level': level,
            'volume_score': round(volume_score, 2),
            'turnover_rate_score': round(turnover_rate_score, 2),
            'amount_score': round(amount_score, 2),
            'amplitude_score': round(amplitude_score, 2),
            'stability_score': round(stability_score, 2),
            'is_volume_anomaly': is_anomaly,
            'pass_threshold': liquidity_score >= 30,  # D级以上才通过
            'kline_data_missing': kline_data_missing,
        }

    def _score_volume(self, volume: int, thresholds: Dict) -> float:
        """
        成交量评分（0-100）

        超过阈值2倍得满分
        """
        if volume <= 0:
            return 0.0

        min_vol = thresholds['min_volume']
        excellent_vol = thresholds['excellent_volume']

        if volume < min_vol:
            return 0.0

        # 线性评分：min_volume -> 50分，excellent_volume -> 100分
        score = 50 + (volume - min_vol) / (excellent_vol - min_vol) * 50
        return min(100.0, score)

    def _score_turnover_rate(self, turnover_rate: float, thresholds: Dict) -> float:
        """
        换手率评分（0-100）

        超过阈值2倍得满分
        """
        if turnover_rate <= 0:
            return 0.0

        min_rate = thresholds['min_turnover_rate']
        excellent_rate = thresholds['excellent_turnover_rate']

        if turnover_rate < min_rate:
            return 0.0

        # 线性评分
        score = 50 + (turnover_rate - min_rate) / (excellent_rate - min_rate) * 50
        return min(100.0, score)

    def _score_amount(self, amount: float, thresholds: Dict) -> float:
        """
        成交额评分（0-100）

        超过阈值2倍得满分
        """
        if amount <= 0:
            return 0.0

        min_amount = thresholds['min_turnover_amount']
        excellent_amount = thresholds['excellent_amount']

        if amount < min_amount:
            return 0.0

        # 线性评分
        score = 50 + (amount - min_amount) / (excellent_amount - min_amount) * 50
        return min(100.0, score)

    def _score_amplitude(self, amplitude: float) -> float:
        """
        振幅评分（0-100）

        振幅3%得30分，10%得100分，超过10%扣分（可能是异常波动）
        """
        if amplitude <= 0:
            return 0.0

        if amplitude < 10:
            # 线性评分：0% -> 0分，10% -> 100分
            return min(100.0, amplitude * 10)
        else:
            # 超过10%扣分
            return 80.0

    def _get_liquidity_level(self, score: float) -> str:
        """
        根据评分判定流动性等级

        A级（高流动性）：score >= 70
        B级（中等流动性）：50 <= score < 70
        C级（低流动性）：30 <= score < 50
        D级（极低流动性）：score < 30
        """
        if score >= 70:
            return 'A'
        elif score >= 50:
            return 'B'
        elif score >= 30:
            return 'C'
        else:
            return 'D'

    async def get_historical_liquidity_data(
        self,
        stock_code: str,
        days: int = 5
    ) -> Optional[Dict]:
        """
        获取历史流动性数据

        从 kline_data 表获取最近N个交易日的数据

        Returns:
            {
                'volumes': [100000, 120000, ...],
                'turnover_rates': [0.5, 0.6, ...],
                'turnovers': [1000000, 1200000, ...],
                'mean_volume': 110000,
                'std_volume': 10000,
                'cv_volume': 0.09,
                'mean_turnover_rate': 0.55,
                'cv_turnover_rate': 0.1,
            }
        """
        try:
            # 从数据库获取K线数据（同步方法，不使用 await）
            klines = self.db_manager.kline_queries.get_stock_kline(
                stock_code, days
            )

            if not klines or len(klines) < 3:
                # 至少需要3天数据
                return None

            volumes = [k.get('volume', 0) or 0 for k in klines]
            turnover_rates = [k.get('turnover_rate', 0) or 0 for k in klines]
            turnovers = [k.get('turnover', 0) or 0 for k in klines]

            # 过滤掉0值
            volumes = [v for v in volumes if v > 0]
            turnover_rates = [r for r in turnover_rates if r > 0]
            turnovers = [t for t in turnovers if t > 0]

            if not volumes or not turnover_rates:
                return None

            mean_volume = np.mean(volumes)
            std_volume = np.std(volumes)
            cv_volume = std_volume / mean_volume if mean_volume > 0 else 999

            mean_turnover_rate = np.mean(turnover_rates)
            std_turnover_rate = np.std(turnover_rates)
            cv_turnover_rate = std_turnover_rate / mean_turnover_rate if mean_turnover_rate > 0 else 999

            return {
                'volumes': volumes,
                'turnover_rates': turnover_rates,
                'turnovers': turnovers,
                'mean_volume': mean_volume,
                'std_volume': std_volume,
                'cv_volume': cv_volume,
                'mean_turnover_rate': mean_turnover_rate,
                'std_turnover_rate': std_turnover_rate,
                'cv_turnover_rate': cv_turnover_rate,
            }

        except Exception as e:
            self.logger.error(f"获取历史流动性数据失败 {stock_code}: {e}")
            return None

    def calculate_stability_score(
        self,
        hist_data: Dict,
        thresholds: Dict
    ) -> float:
        """
        计算历史稳定性评分（0-100）

        CV（变异系数）越小越稳定，评分越高
        """
        if not hist_data:
            return 50.0  # 无历史数据时给中性分

        cv_volume = hist_data['cv_volume']
        cv_turnover = hist_data['cv_turnover_rate']
        max_cv_volume = thresholds['max_volume_cv']
        max_cv_turnover = thresholds['max_turnover_cv']

        # CV越小越稳定，评分越高
        volume_stability = max(0, 100 - (cv_volume / max_cv_volume) * 100)
        turnover_stability = max(0, 100 - (cv_turnover / max_cv_turnover) * 100)

        return (volume_stability * 0.6 + turnover_stability * 0.4)

    def detect_volume_anomaly(
        self,
        hist_data: Dict,
        current_volume: int
    ) -> bool:
        """
        检测当前成交量是否为异常放大

        当前成交量超过历史均值+3倍标准差，且超过均值5倍，视为异常
        """
        if not hist_data or len(hist_data['volumes']) < 3:
            return False

        mean_vol = hist_data['mean_volume']
        std_vol = hist_data['std_volume']

        # 当前成交量超过历史均值+3倍标准差，且超过均值5倍
        threshold = mean_vol + 3 * std_vol

        if current_volume > threshold and current_volume > mean_vol * 5:
            return True  # 异常放大

        return False

