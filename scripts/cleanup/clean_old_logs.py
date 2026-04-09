#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
清理旧的日志文件

清理带时间戳的旧日志文件（backend_YYYYMMDD_HHMMSS.log），
保留新的按日期轮转的日志文件（backend.log 和 backend.log.YYYY-MM-DD）
"""

import os
import re
from pathlib import Path

def clean_old_logs():
    """清理旧的日志文件"""

    # 日志目录
    log_dir = Path(__file__).parent.parent.parent / 'logs'

    if not log_dir.exists():
        print(f"日志目录不存在: {log_dir}")
        return

    # 旧日志文件的模式：backend_YYYYMMDD_HHMMSS.log
    old_pattern = re.compile(r'^backend_\d{8}_\d{6}\.log$')

    # 统计
    total_files = 0
    deleted_files = 0
    total_size = 0

    print(f"扫描日志目录: {log_dir}")
    print("-" * 60)

    # 遍历日志目录
    for file_path in log_dir.iterdir():
        if file_path.is_file() and old_pattern.match(file_path.name):
            total_files += 1
            file_size = file_path.stat().st_size

            print(f"删除: {file_path.name} ({file_size:,} bytes)")

            try:
                file_path.unlink()
                deleted_files += 1
                total_size += file_size
            except Exception as e:
                print(f"  错误: {e}")

    print("-" * 60)
    print(f"扫描文件: {total_files}")
    print(f"删除文件: {deleted_files}")
    print(f"释放空间: {total_size:,} bytes ({total_size / 1024 / 1024:.2f} MB)")

    # 列出保留的日志文件
    print("\n保留的日志文件:")
    remaining_logs = sorted([f for f in log_dir.iterdir() if f.is_file() and f.name.startswith('backend')])
    for log_file in remaining_logs:
        size = log_file.stat().st_size
        print(f"  {log_file.name} ({size:,} bytes)")

if __name__ == '__main__':
    clean_old_logs()
