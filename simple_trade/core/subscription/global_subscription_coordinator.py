#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 向后兼容：已重构为 SubscriptionRecoveryHelper（P5-2）
from .subscription_recovery_helper import SubscriptionRecoveryHelper as GlobalSubscriptionCoordinator
__all__ = ['GlobalSubscriptionCoordinator']
