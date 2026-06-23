#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开盘持仓即时风险判读（纯函数·只读）

专治"开盘想卖却干等信号"——持仓股的资金流/狙击/动量卖出信号都要盘中累计数据
(20min 流、VWAP、5min 动量)，开盘头几分钟根本算不出来，于是用户只能被动等一个
等不来的信号。这里只用**第一笔报价就能算的特征**(昨收/开盘价/现价)，在 09:30 就能给出
"该不该按纪律减/观察"。

设计口径(与 entry_timing / coach 一致的诚实定位)：
- **纯展示/告警，绝不下单、绝不门控、绝不做预测断语**(不说"必跌")。
- 只回答"开盘是否明显走弱、是否触及你盘前设的离场计划"，把被动等信号变成执行计划。
- 阈值全部可调(frozen dataclass)，便于回测/单测/复跑。
"""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class OpenCheckThresholds:
    gap_down_pct: float = -0.03          # 低开 ≤ -3% → red(硬跳空)
    gap_down_mild_pct: float = -0.01     # 低开 ≤ -1% → amber(温和低开)
    gap_up_fade_pct: float = -0.005      # 高开低走 last/open-1 ≤ -0.5% → amber
    fade_hard_pct: float = -0.02         # 高开低走 ≤ -2% → 升 red
    break_prevclose_pct: float = -0.002  # 跌破昨收(0.2% 容差) → amber
    vwap_break_pct: float = -0.003       # 跌破开盘均价(0.3% 容差) → amber(v1 暂不喂 VWAP)
    vwap_min_secs: int = 120             # 开盘满 2min 才用 VWAP(预留)
    open_window_min: int = 45            # 即时风险快路径只在开盘后 N 分钟内生效(之后交回常规规则)
    push_on_amber: bool = False          # 黄灯默认只进卡片不推企微(防刷屏)


def _pct(x: Optional[float]) -> str:
    return "%+.1f%%" % (x * 100) if x is not None else "—"


def _f(x) -> Optional[float]:
    """转正数 float；非法/<=0 → None。开盘首笔前 open 可能为 0，须 None-safe。"""
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def compute_open_features(prev_close, open_price, last_price,
                          opening_vwap=None, secs_since_open=None) -> dict:
    """只用昨收/开盘价/现价(可选开盘均价)算开盘特征，全部 None-safe。

    gap_pct=开盘相对昨收；intraday_chg=现价相对昨收；fade_pct=现价相对开盘(高开低走)。
    """
    pc, op, lp, vw = _f(prev_close), _f(open_price), _f(last_price), _f(opening_vwap)
    gap_pct = (op / pc - 1) if (pc and op) else None
    intraday_chg = (lp / pc - 1) if (pc and lp) else None
    fade_pct = (lp / op - 1) if (op and lp) else None
    vwap_break = None
    if vw and lp and (secs_since_open is None or secs_since_open >= 0):
        vwap_break = lp / vw - 1
    return {
        "gap_pct": gap_pct,
        "intraday_chg": intraday_chg,
        "fade_pct": fade_pct,
        "below_prev": (intraday_chg is not None and intraday_chg < 0),
        "vwap_break": vwap_break,
        "last": lp, "prev_close": pc, "open": op,
    }


def _plan_triggered(plan: Optional[dict], feat: dict,
                    th: OpenCheckThresholds) -> Tuple[bool, str]:
    """预设离场计划是否被开盘特征命中。返回 (matched, desc)。"""
    if not plan:
        return (False, "")
    tt = plan.get("trigger_type")
    tv = plan.get("trigger_value")
    gap = feat.get("gap_pct")
    chg = feat.get("intraday_chg")
    if tt == "at_open_unconditional":
        return (True, "开盘无条件执行")
    if tt == "gap_down_pct" and gap is not None and tv is not None:
        if gap <= float(tv):
            return (True, f"低开{_pct(gap)}≤计划线{_pct(float(tv))}")
    if tt == "below_prev_close" and chg is not None:
        if chg <= th.break_prevclose_pct:
            return (True, f"跌破昨收({_pct(chg)})")
    return (False, "")


def judge_open_risk(feat: dict, pl_pct: Optional[float], plan: Optional[dict],
                    regime: Optional[dict] = None,
                    th: OpenCheckThresholds = OpenCheckThresholds(),
                    secs_since_open: Optional[int] = None) -> Tuple[str, str, str]:
    """纯函数：给出 (light, label, reason)。light ∈ {red, amber, green}。

    优先级：命中预设计划(sell/trim) > 硬跳空/高开低走(red) > 温和低开/跌破昨收/破均价(amber) > green。
    regime=='down' 仅收紧 amber 措辞，不改变 light、不下单。
    """
    gap = feat.get("gap_pct")
    chg = feat.get("intraday_chg")
    fade = feat.get("fade_pct")
    vb = feat.get("vwap_break")

    # 数据不足：开盘首笔前 prev_close/open 缺失 → 不报警(green·数据不足)
    if gap is None and chg is None and fade is None:
        return ("green", "数据不足", "暂无开盘报价(昨收/开盘价缺失)")

    # 1) 预设离场计划命中(sell/trim)——把"被动等信号"变成"执行计划"
    if plan:
        action = plan.get("planned_action")
        matched, desc = _plan_triggered(plan, feat, th)
        if action in ("sell", "trim") and matched:
            verb = "清/减" if action == "sell" else "减"
            note = plan.get("note") or "无备注"
            return ("red", f"按计划{verb}", f"{desc}——按你盘前设的离场计划执行({note})")
        # hold 计划 / 未命中的 sell 计划：落到特征判读，has_plan 在卡片另标

    # 2) 硬风险(red)
    reds = []
    if gap is not None and gap <= th.gap_down_pct:
        reds.append(f"低开{_pct(gap)}")
    if fade is not None and fade <= th.fade_hard_pct:
        reds.append(f"高开低走{_pct(fade)}")
    if reds:
        return ("red", "开盘走弱",
                "、".join(reds) + "——开盘明显走弱，按你的纪律该减/观察(非预测必跌)")

    # 3) 偏弱(amber)
    ambers = []
    if gap is not None and gap <= th.gap_down_mild_pct:
        ambers.append(f"温和低开{_pct(gap)}")
    if chg is not None and chg <= th.break_prevclose_pct:
        ambers.append(f"跌破昨收{_pct(chg)}")
    if fade is not None and fade <= th.gap_up_fade_pct:
        ambers.append(f"冲高回落{_pct(fade)}")
    if vb is not None and vb <= th.vwap_break_pct:
        ambers.append(f"跌破开盘均价{_pct(vb)}")
    if ambers:
        tail = "；防守日尤需留意" if (regime and regime.get("regime") == "down") else ""
        return ("amber", "留意",
                "、".join(ambers) + "——偏弱，留意是否触及你的离场线" + tail)

    # 4) 平稳(green)
    return ("green", "平稳", "开盘未见明显走弱(未破昨收/未低开)")
