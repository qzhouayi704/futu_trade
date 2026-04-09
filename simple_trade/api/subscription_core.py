#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅核心管理器模块（向后兼容层）

实际实现已合并到 subscription_manager.py。
此文件保留向后兼容导入。
"""

from .subscription_manager import SubscriptionManager

# 向后兼容：SubscriptionCore 是 SubscriptionManager 的别名
SubscriptionCore = SubscriptionManager

__all__ = ['SubscriptionCore']
