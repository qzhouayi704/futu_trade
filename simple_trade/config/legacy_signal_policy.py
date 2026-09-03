#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旧交易系统运行模式的统一策略。

旧规则在 V2 接管决策后仍可保留检测和样本入库，但不能继续产生第二套
提醒、评分或交易动作。所有旧链路统一读取本模块，避免各自维护开关。
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional

from ..utils import parse_flag


class LegacySignalMode(str, Enum):
    """旧信号系统运行模式。"""

    ACTIVE = "active"
    OBSERVE = "observe"
    OFF = "off"


ALL_LEGACY_FLOW_RULE_IDS = frozenset(
    {"R1", "R2", "R3", "R4", "R5", "R7", "R10", "R11", "R12", "R13", "R14"}
)


@dataclass(frozen=True)
class LegacySignalPolicy:
    """旧系统的检测权和动作权。"""

    mode: LegacySignalMode

    @property
    def detection_enabled(self) -> bool:
        return self.mode is not LegacySignalMode.OFF

    @property
    def action_enabled(self) -> bool:
        return self.mode is LegacySignalMode.ACTIVE

    @property
    def observe_only(self) -> bool:
        return self.mode is LegacySignalMode.OBSERVE


def resolve_legacy_signal_policy(
    environ: Optional[Mapping[str, str]] = None,
) -> LegacySignalPolicy:
    """读取旧系统模式；V2 正式提醒时默认撤销旧系统动作权。"""

    env = environ if environ is not None else os.environ
    raw_mode = str(env.get("LEGACY_SIGNAL_MODE", "")).strip().lower()
    if raw_mode:
        try:
            return LegacySignalPolicy(LegacySignalMode(raw_mode))
        except ValueError:
            # 配置拼错时采用 observe，避免意外恢复旧交易权限。
            return LegacySignalPolicy(LegacySignalMode.OBSERVE)

    v2_enabled = parse_flag(env.get("V2_ENABLED", False))
    v2_mode = str(env.get("V2_MODE", "shadow")).strip().lower()
    if v2_enabled and v2_mode == "alert":
        return LegacySignalPolicy(LegacySignalMode.OBSERVE)
    return LegacySignalPolicy(LegacySignalMode.ACTIVE)


def legacy_flow_advisory_rule_ids(
    environ: Optional[Mapping[str, str]] = None,
) -> frozenset[str]:
    """返回只可展示和回测、不得参与决策的旧资金规则。"""

    env = environ if environ is not None else os.environ
    policy = resolve_legacy_signal_policy(env)
    if not policy.action_enabled:
        return ALL_LEGACY_FLOW_RULE_IDS

    configured = str(
        env.get("FLOW_ADVISORY_RULES", "R1,R4,R5,R11,R12,R14")
    )
    return frozenset(
        rule_id.strip().upper()
        for rule_id in configured.split(",")
        if rule_id.strip()
    )
