#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收尾-5: DegradationManager 与 UnifiedDataCache 职责边界集成测试

测试场景：
1. 内存 85% 时，UnifiedDataCache 清理缓存，DegradationManager 保持独立决策
2. API 连续失败时，DegradationManager 进入 DEGRADED，UnifiedDataCache 不受影响
3. 两者同时触发时，行为互不干扰
"""

import unittest
from unittest.mock import patch, MagicMock


class TestDegradationBoundary(unittest.TestCase):
    """DegradationManager 与 UnifiedDataCache 职责边界测试"""

    def setUp(self):
        from simple_trade.core.cache.degradation_manager import DegradationManager
        self.dm = DegradationManager()

    def test_api_failure_does_not_affect_cache(self):
        """API 连续失败 → DegradationManager 升级，不触发缓存操作"""
        from simple_trade.core.cache.degradation_manager import DegradationLevel

        # 模拟 15 次 API 连续失败
        for _ in range(15):
            self.dm.report_api_failure()

        # 手动触发评估（mock psutil 内存为正常 50%）
        with patch('psutil.virtual_memory') as mock_mem:
            mock_mem.return_value = MagicMock(percent=50.0)
            self.dm._evaluate()

        self.assertEqual(self.dm.level, DegradationLevel.DEGRADED)

        # 确认 DegradationManager 没有 cache 相关属性或方法调用
        self.assertFalse(hasattr(self.dm, '_cache'))
        self.assertFalse(hasattr(self.dm, 'unified_cache'))

    def test_memory_pressure_independent(self):
        """内存 85% → DegradationManager 升级到 DEGRADED"""
        from simple_trade.core.cache.degradation_manager import DegradationLevel

        with patch('psutil.virtual_memory') as mock_mem:
            mock_mem.return_value = MagicMock(percent=85.0)
            self.dm._evaluate()

        self.assertEqual(self.dm.level, DegradationLevel.DEGRADED)

    def test_recovery_after_api_success(self):
        """API 恢复后，DegradationManager 回到 NORMAL"""
        from simple_trade.core.cache.degradation_manager import DegradationLevel

        # 先制造失败
        for _ in range(15):
            self.dm.report_api_failure()

        with patch('psutil.virtual_memory') as mock_mem:
            mock_mem.return_value = MagicMock(percent=50.0)
            self.dm._evaluate()
            self.assertEqual(self.dm.level, DegradationLevel.DEGRADED)

            # API 恢复
            self.dm.report_api_success()
            self.dm._evaluate()
            self.assertEqual(self.dm.level, DegradationLevel.NORMAL)

    def test_no_cross_dependency(self):
        """确认 DegradationManager 和 UnifiedDataCache 无交叉引用"""
        import inspect
        from simple_trade.core.cache.degradation_manager import DegradationManager
        from simple_trade.core.cache.unified_data_cache import UnifiedDataCache

        dm_source = inspect.getsource(DegradationManager)
        cache_source = inspect.getsource(UnifiedDataCache)

        self.assertNotIn('UnifiedDataCache', dm_source)
        self.assertNotIn('DegradationManager', cache_source)

    def test_status_api(self):
        """get_status 返回完整状态字典"""
        status = self.dm.get_status()
        self.assertIn('level', status)
        self.assertIn('is_degraded', status)
        self.assertIn('push_interval', status)
        self.assertIn('api_consecutive_failures', status)
        self.assertEqual(status['level'], 'NORMAL')


if __name__ == '__main__':
    unittest.main()
