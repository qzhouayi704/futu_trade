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
# 券商画像分类（5层分类）
# ============================================================

# 散户/游资通道 — 互联网券商和中小券商，客户几乎全是散户
RETAIL_BROKER_KEYWORDS = [
    # 互联网券商
    '富途', '华盛', '长桥', '盈立', '尊嘉', '微牛',
    '老虎', '雪盈', '艾德', '利弗莫尔',
    # 香港本地中小券商
    '耀才', '致富', '信诚', '亨达', '恒盛',
    '时富', '辉立', '国元', '英皇',
    # 互联网/零售券商（海外）
    '盈透',  # Interactive Brokers，偏专业散户
]

# 机构/投行通道 — 大型中资、外资投行，代客+自营
INSTITUTIONAL_BROKER_KEYWORDS = [
    # 外资大行
    '高盛', '摩根', '瑞银', '巴克莱', '花旗', '美林',
    '麦格理', '渣打', '法兴', '德银', '野村',
    '法国巴黎',  # BNP Paribas
    '星展',      # DBS
    '大和',      # Daiwa
    'Jefferies', 'CLSA',
    # 中资大券商
    '中金', '中信', '华泰', '银河', '中国国际金融',
    '招银', '国泰君安', '海通', '广发',
    '凯基', '交银', '中银国际',
    '建银', '工银', '光大', '申万',
    # 银行系（注意：汇丰在港有大量零售客户，但券商部门偏机构）
    '汇丰',
    # 其他机构券商
    '复星', '恒生证券', '东方证券',
    '国信', '兴证', '安信', '方正',
]

# 清算通道 — 对冲基金和专业机构的清算代理
# 这些券商本身不做方向性交易，但背后客户是对冲基金/专业资金
# 出现在卖方时信号最强（代表专业资金在出货）
CLEARING_BROKER_KEYWORDS = [
    '荷银',       # ABN AMRO Clearing，港股最大清算通道
    'Pershing',   # BNY Mellon旗下清算
    'Nomura',     # 野村清算部分客户
]

# 做市商/量化通道 — 高频交易和量化基金
# 通常双向操作提供流动性，方向性信号较弱
MARKET_MAKER_KEYWORDS = [
    'Eclipse',    # Eclipse Options
    'Jump',       # Jump Trading
    '万邦',       # 万邦亚太，做市商
    'Optiver',    # 量化做市商
    'Susquehanna', 'SIG',  # Susquehanna
    'Citadel',    # Citadel Securities
    'Flow Traders',
    'IMC',
    'Virtu',
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
            clearing_sell = sum(1 for s in top_sellers if s['tag'] == '清算通道')
            mm_sell = sum(1 for s in top_sellers if s['tag'] == '做市商')

            result.retail_buy_count = retail_buy
            result.institutional_sell_count = inst_sell + clearing_sell  # 清算通道也算专业卖方

            # ========== 诱多陷阱判定 ==========
            if len(top_sellers) > 0 and len(top_buyers) > 0:
                # 专业资金卖方 = 机构 + 清算通道 + 北水（做市商不算，因为双向操作）
                smart_sell = inst_sell + clearing_sell + connect_sell
                retail_buy_ratio = retail_buy / len(top_buyers) if top_buyers else 0

                trap_score = 0.0

                # --- 卖方专业资金密度 ---
                # 清算通道（荷银等）权重最高：背后是对冲基金
                if clearing_sell >= 2:
                    trap_score += 0.35
                elif clearing_sell >= 1:
                    trap_score += 0.2

                # 机构卖方
                if inst_sell >= 3:
                    trap_score += 0.3
                elif inst_sell >= 2:
                    trap_score += 0.2
                elif inst_sell >= 1:
                    trap_score += 0.1

                # 北水卖出也是专业资金信号
                if connect_sell >= 1:
                    trap_score += 0.1

                # --- 买方散户密度 ---
                if retail_buy_ratio >= 0.5:
                    trap_score += 0.3
                elif retail_buy_ratio >= 0.3:
                    trap_score += 0.15

                # --- 涨幅加成 ---
                if change_pct > 10:
                    trap_score += 0.2
                elif change_pct > 5:
                    trap_score += 0.1

                # 最终判定
                result.trap_confidence = min(trap_score, 1.0)
                result.is_trap = result.trap_confidence >= 0.5

                if result.is_trap:
                    # 构建更详细的原因描述
                    smart_names = []
                    for s in top_sellers:
                        if s['tag'] in ('机构', '清算通道', '北水'):
                            label = f"{s['name']}({s['tag']})"
                            smart_names.append(label)
                            if len(smart_names) >= 3:
                                break
                    retail_names = [b['name'] for b in top_buyers if b['tag'] == '散户'][:3]
                    result.reason = (
                        f"出货陷阱(置信度{result.trap_confidence:.0%})："
                        f"卖方专业资金[{','.join(smart_names)}]，"
                        f"买方散户[{','.join(retail_names)}]"
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
                    tag = _classify_broker(name)
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


def _classify_broker(name: str) -> str:
    """对券商名称进行5层分类

    优先级：北水 > 清算通道 > 做市商 > 散户 > 机构 > 未知
    北水和清算通道优先匹配，因为它们的信号意义最明确。
    """
    # 1. 北水（最高优先级，席位固定）
    if any(kw in name for kw in CONNECT_BROKER_KEYWORDS):
        return '北水'
    # 2. 清算通道（对冲基金代理）
    if any(kw in name for kw in CLEARING_BROKER_KEYWORDS):
        return '清算通道'
    # 3. 做市商/量化
    if any(kw in name for kw in MARKET_MAKER_KEYWORDS):
        return '做市商'
    # 4. 散户券商
    if any(kw in name for kw in RETAIL_BROKER_KEYWORDS):
        return '散户'
    # 5. 机构券商
    if any(kw in name for kw in INSTITUTIONAL_BROKER_KEYWORDS):
        return '机构'
    return '未知'

