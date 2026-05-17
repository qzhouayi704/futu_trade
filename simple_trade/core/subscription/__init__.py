#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订阅恢复管理模块（P5-2 重构）"""

from .subscription_recovery_helper import SubscriptionRecoveryHelper

# 向后兼容别名
GlobalSubscriptionCoordinator = SubscriptionRecoveryHelper

__all__ = ['SubscriptionRecoveryHelper', 'GlobalSubscriptionCoordinator']
