#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股低换手率回测脚本（简化版）

这是一个简化的入口脚本，实际功能由统一的回测系统提供。

用法:
    # 交互式运行
    python scripts/run_low_turnover_backtest.py -i

    # 命令行模式 - 基准测试
    python scripts/run_low_turnover_backtest.py --start 2024-02-06 --end 2025-02-06

    # 命令行模式 - 参数优化
    python scripts/run_low_turnover_backtest.py --optimize --mode single

    # 推荐使用统一入口
    python scripts/backtest/run_backtest.py low-turnover -i
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入统一入口
from scripts.backtest.run_backtest import main as unified_main


if __name__ == '__main__':
    # 在参数前插入 'low-turnover' 命令
    sys.argv.insert(1, 'low-turnover')

    # 调用统一入口
    unified_main()
