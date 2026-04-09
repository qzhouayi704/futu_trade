#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行 pytest 测试套件

用法:
    uv run scripts/run_pytest.py                    # 运行所有 pytest 测试
    uv run scripts/run_pytest.py --ticker           # 只运行逐笔成交分析测试
    uv run scripts/run_pytest.py --scalping         # 只运行 scalping 测试
    uv run scripts/run_pytest.py -k "test_name"     # 按名称过滤
"""

import subprocess
import sys


def main():
    args = sys.argv[1:]
    cmd = ["uv", "run", "pytest", "-v", "--tb=short"]

    # 解析自定义参数
    custom_args = []
    passthrough = []
    for arg in args:
        if arg == "--ticker":
            custom_args.extend([
                "tests/test_ticker_analysis.py",
                "tests/test_ticker_analysis_properties.py",
            ])
        elif arg == "--scalping":
            custom_args.append("tests/scalping/")
        else:
            passthrough.append(arg)

    cmd.extend(custom_args)
    cmd.extend(passthrough)

    # 没有指定范围时运行 tests/ 下所有
    if not custom_args and not any(a.startswith("tests/") for a in passthrough):
        cmd.append("tests/")

    print(f"执行: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
