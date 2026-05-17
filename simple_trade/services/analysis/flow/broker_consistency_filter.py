#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
经纪商一致性过滤器 (Broker Consistency Filter)

通过富途 get_broker_queue 接口获取实时经纪商席位排队数据，
交叉验证"资金流方向"与"席位分布"是否一致，识别以下陷阱：

1. 诱多派发陷阱：表面大单买入（散户通道），实际机构在卖方密集挂单出货
2. 诱空洗盘陷阱：表面资金流出（机构对倒），实际散户在恐慌抛售被机构吸筹

核心依据：挂单盘口可以造假（Spoofing），但经纪商通道归属无法伪造。
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from futu import RET_OK, SubType

logger = logging.getLogger("broker_consistency")


# ============================================================
# 券商画像分类
# ============================================================

# 散户/游资通道 — 以互联网券商和中小券商为主
RETAIL_BROKER_KEYWORDS = [
    '富途', '华盛', '长桥', '盈立', '尊嘉', '微牛',
    '老虎', '雪盈', '艾德', '利弗莫尔',
    '耀才', '致富', '信诚',
]

# 机构/主力通道 — 以大型中资、外资投行为主
INSTITUTIONAL_BROKER_KEYWORDS = [
    '银河', '华泰', '中金', '中信', '摩根', '瑞银',
    '巴克莱', '高盛', '麦格理', '花旗', '美林',
    '汇丰', '渣打', '法兴', '德银', '野村',
    '招银', '国泰君安', '海通', '广发',
    '荷银', '凯基', '交银', '中银国际',
    '建银', '工银', '光大', '申万',
]

# 港股通/沪深港通道 — 代表内地资金(北水)
CONNECT_BROKER_KEYWORDS = [
    '港股通', '沪港通', '深港通',
    '中国投资信息', '中国创盈',
]


@dataclass
class BrokerAnalysisResult:
    """经纪商一致性分析结果"""
    stock_code: str = ""
    is_trap: bool = False                   # 是否命中诱多陷阱
    trap_confidence: float = 0.0            # 陷阱置信度 (0-1)
    institutional_sell_count: int = 0       # 卖方中机构席位数
    retail_buy_count: int = 0               # 买方中散户席位数
    total_bid_brokers: int = 0              # 买方总席位数
    total_ask_brokers: int = 0              # 卖方总席位数
    top_sellers: List[str] = field(default_factory=list)   # 卖方前5券商名
    top_buyers: List[str] = field(default_factory=list)    # 买方前5券商名
    # 详细席位数据：[{name, pos, tag}]
    buyer_details: List[Dict] = field(default_factory=list)
    seller_details: List[Dict] = field(default_factory=list)
    reason: str = ""                        # 人类可读描述


class BrokerConsistencyFilter:
    """经纪商一致性过滤器 — 识别主力诱多派发陷阱"""

    def __init__(self, futu_client=None):
        """
        Args:
            futu_client: FutuClient 封装对象，需要有 .client 属性(OpenQuoteContext)
        """
        self._futu_client = futu_client
        self._subscribed: set = set()  # 已订阅 BROKER 的股票集合

    def check_distribution_trap(
        self,
        stock_code: str,
        change_pct: float = 0.0,
    ) -> BrokerAnalysisResult:
        """
        检查经纪商席位分布，识别诱多陷阱

        Args:
            stock_code: 股票代码
            change_pct: 当日涨跌幅(%)，用于过滤低波动场景

        Returns:
            BrokerAnalysisResult
        """
        result = BrokerAnalysisResult(stock_code=stock_code)

        if not self._futu_client:
            return result

        quote_ctx = getattr(self._futu_client, 'client', None)
        if not quote_ctx:
            return result

        try:
            # 确保已订阅 BROKER 数据
            self._ensure_subscription(stock_code, quote_ctx)

            # 获取经纪商队列
            ret, bid_df, ask_df = quote_ctx.get_broker_queue(stock_code)
            if ret != RET_OK:
                logger.debug(f"[{stock_code}] 获取经纪商队列失败: {bid_df}")
                return result

            # 提取唯一券商列表 (去重，按 pos 排序取前排)
            top_buyers = self._extract_unique_brokers(
                bid_df, 'bid_broker_name', 'bid_broker_pos', top_n=10
            )
            top_sellers = self._extract_unique_brokers(
                ask_df, 'ask_broker_name', 'ask_broker_pos', top_n=10
            )

            result.top_buyers = [b['name'] for b in top_buyers[:5]]
            result.top_sellers = [s['name'] for s in top_sellers[:5]]
            result.buyer_details = top_buyers[:8]
            result.seller_details = top_sellers[:8]
            result.total_bid_brokers = len(top_buyers)
            result.total_ask_brokers = len(top_sellers)

            # 分类计数
            retail_buy = sum(1 for b in top_buyers if b['tag'] == '散户')
            inst_sell = sum(1 for s in top_sellers if s['tag'] == '机构')
            connect_sell = sum(1 for s in top_sellers if s['tag'] == '北水')

            result.retail_buy_count = retail_buy
            result.institutional_sell_count = inst_sell

            # ========== 诱多陷阱判定 ==========
            # 条件：卖方有 ≥2 家机构/港股通 且 买方散户占比高
            if len(top_sellers) > 0 and len(top_buyers) > 0:
                inst_sell_total = inst_sell + connect_sell
                retail_buy_ratio = retail_buy / len(top_buyers) if top_buyers else 0

                # 判定条件
                trap_score = 0.0

                # 机构卖方密度越高，越可能是出货
                if inst_sell_total >= 3:
                    trap_score += 0.4
                elif inst_sell_total >= 2:
                    trap_score += 0.25
                elif inst_sell_total >= 1:
                    trap_score += 0.1

                # 散户买方密度越高，越确认是接盘
                if retail_buy_ratio >= 0.5:
                    trap_score += 0.3
                elif retail_buy_ratio >= 0.3:
                    trap_score += 0.15

                # 涨幅加成：高位出货比低位更危险
                if change_pct > 10:
                    trap_score += 0.2
                elif change_pct > 5:
                    trap_score += 0.1

                # 最终判定
                result.trap_confidence = min(trap_score, 1.0)
                result.is_trap = result.trap_confidence >= 0.5

                if result.is_trap:
                    inst_names = [s['name'] for s in top_sellers if s['tag'] in ('机构', '北水')][:3]
                    retail_names = [b['name'] for b in top_buyers if b['tag'] == '散户'][:3]
                    result.reason = (
                        f"机构出货陷阱(置信度{result.trap_confidence:.0%})："
                        f"卖方机构席位[{','.join(inst_names[:3])}]，"
                        f"买方散户席位[{','.join(retail_names[:3])}]"
                    )
                    logger.warning(f"[{stock_code}] ⚠️ {result.reason}")

        except Exception as e:
            logger.debug(f"[{stock_code}] 经纪商分析异常: {e}")

        return result

    def _ensure_subscription(self, stock_code: str, quote_ctx) -> None:
        """确保已订阅该股票的 BROKER 数据"""
        if stock_code in self._subscribed:
            return
        try:
            ret, err = quote_ctx.subscribe([stock_code], [SubType.BROKER])
            if ret == RET_OK:
                self._subscribed.add(stock_code)
            else:
                logger.debug(f"[{stock_code}] BROKER订阅失败: {err}")
        except Exception as e:
            logger.debug(f"[{stock_code}] BROKER订阅异常: {e}")

    @staticmethod
    def _extract_unique_brokers(
        df, name_col: str, pos_col: str, top_n: int = 10
    ) -> List[Dict]:
        """从 DataFrame 提取去重券商列表，带分类标签和排队位置"""
        if df is None or df.empty:
            return []
        try:
            sorted_df = df.sort_values(pos_col)
            seen = set()
            brokers = []
            for _, row in sorted_df.iterrows():
                name = str(row.get(name_col, '')).strip()
                if name and name != 'N/A' and name not in seen:
                    seen.add(name)
                    pos = int(row.get(pos_col, 0))
                    tag = '未知'
                    if any(kw in name for kw in RETAIL_BROKER_KEYWORDS):
                        tag = '散户'
                    elif any(kw in name for kw in INSTITUTIONAL_BROKER_KEYWORDS):
                        tag = '机构'
                    elif any(kw in name for kw in CONNECT_BROKER_KEYWORDS):
                        tag = '北水'
                    brokers.append({'name': name, 'pos': pos, 'tag': tag})
                    if len(brokers) >= top_n:
                        break
            return brokers
        except Exception:
            return []

    @staticmethod
    def _is_retail(broker_name: str) -> bool:
        """判断是否为散户通道券商"""
        return any(kw in broker_name for kw in RETAIL_BROKER_KEYWORDS)

    @staticmethod
    def _is_institutional(broker_name: str) -> bool:
        """判断是否为机构通道券商"""
        return any(kw in broker_name for kw in INSTITUTIONAL_BROKER_KEYWORDS)

    @staticmethod
    def _is_connect(broker_name: str) -> bool:
        """判断是否为港股通/沪深港通道"""
        return any(kw in broker_name for kw in CONNECT_BROKER_KEYWORDS)
