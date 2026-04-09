#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并发写入压力测试
验证 DatabaseWriteQueue 能否消除 "database is locked" 错误
"""

import sys
import os
import threading
import time
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# 解决 protobuf 版本冲突
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'


def test_concurrent_writes():
    """10个线程同时写入，验证无 database is locked 错误"""
    from simple_trade.database.core.db_manager import DatabaseManager

    # 使用临时数据库
    db_path = os.path.join(tempfile.gettempdir(), 'test_write_queue.db')
    if os.path.exists(db_path):
        os.remove(db_path)

    db = DatabaseManager(db_path)

    # 创建测试表
    with db.get_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS test_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_name TEXT,
                value INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()

    NUM_THREADS = 10
    WRITES_PER_THREAD = 50
    errors = []
    success_counts = [0] * NUM_THREADS

    def writer(thread_idx):
        """每个线程执行多次写入"""
        for i in range(WRITES_PER_THREAD):
            try:
                db.execute_update(
                    'INSERT INTO test_data (thread_name, value) VALUES (?, ?)',
                    (f'thread-{thread_idx}', thread_idx * 1000 + i)
                )
                success_counts[thread_idx] += 1
            except Exception as e:
                errors.append(f"thread-{thread_idx} write {i}: {e}")

    # 启动所有线程
    print(f"  启动 {NUM_THREADS} 个线程，每个写入 {WRITES_PER_THREAD} 次...")
    start_time = time.time()

    threads = []
    for idx in range(NUM_THREADS):
        t = threading.Thread(target=writer, args=(idx,))
        threads.append(t)
        t.start()

    # 等待所有线程完成
    for t in threads:
        t.join(timeout=60)

    elapsed = time.time() - start_time
    total_success = sum(success_counts)
    expected_total = NUM_THREADS * WRITES_PER_THREAD

    # 验证结果
    count_result = db.execute_query('SELECT COUNT(*) FROM test_data')
    actual_rows = count_result[0][0] if count_result else 0

    print(f"  耗时: {elapsed:.2f}s")
    print(f"  成功写入: {total_success}/{expected_total}")
    print(f"  数据库实际行数: {actual_rows}")
    print(f"  错误数: {len(errors)}")

    if errors:
        for e in errors[:5]:
            print(f"    错误: {e}")

    # 清理
    db.close_all_connections()
    try:
        os.remove(db_path)
    except OSError:
        pass  # Windows 文件锁

    assert len(errors) == 0, f"存在 {len(errors)} 个错误"
    assert total_success == expected_total, f"成功数 {total_success} != 期望 {expected_total}"
    assert actual_rows == expected_total, f"行数 {actual_rows} != 期望 {expected_total}"

    return True


def test_concurrent_batch_writes():
    """多线程批量写入测试"""
    from simple_trade.database.core.db_manager import DatabaseManager

    db_path = os.path.join(tempfile.gettempdir(), 'test_write_queue_batch.db')
    if os.path.exists(db_path):
        os.remove(db_path)

    db = DatabaseManager(db_path)

    with db.get_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS test_batch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT,
                value INTEGER
            )
        ''')
        conn.commit()

    NUM_THREADS = 5
    BATCH_SIZE = 100
    errors = []

    def batch_writer(thread_idx):
        try:
            params = [(f'batch-{thread_idx}', thread_idx * 1000 + i) for i in range(BATCH_SIZE)]
            db.execute_many(
                'INSERT INTO test_batch (batch_id, value) VALUES (?, ?)',
                params
            )
        except Exception as e:
            errors.append(f"batch-thread-{thread_idx}: {e}")

    print(f"  启动 {NUM_THREADS} 个线程，每个批量写入 {BATCH_SIZE} 条...")
    start_time = time.time()

    threads = [threading.Thread(target=batch_writer, args=(i,)) for i in range(NUM_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    elapsed = time.time() - start_time
    expected = NUM_THREADS * BATCH_SIZE

    count_result = db.execute_query('SELECT COUNT(*) FROM test_batch')
    actual_rows = count_result[0][0] if count_result else 0

    print(f"  耗时: {elapsed:.2f}s")
    print(f"  数据库实际行数: {actual_rows}/{expected}")
    print(f"  错误数: {len(errors)}")

    db.close_all_connections()
    try:
        os.remove(db_path)
    except OSError:
        pass  # Windows 文件锁

    assert len(errors) == 0, f"存在 {len(errors)} 个错误"
    assert actual_rows == expected, f"行数 {actual_rows} != 期望 {expected}"

    return True


if __name__ == '__main__':
    tests = [
        ("并发单条写入测试", test_concurrent_writes),
        ("并发批量写入测试", test_concurrent_batch_writes),
    ]

    print("\n" + "=" * 60)
    print("WriteQueue 并发压力测试")
    print("=" * 60)

    all_passed = True
    for name, func in tests:
        try:
            print(f"\n[测试] {name}")
            func()
            print(f"  [通过]")
        except AssertionError as e:
            print(f"  [失败]: {e}")
            all_passed = False
        except Exception as e:
            print(f"  [错误]: {e}")
            all_passed = False

    print("\n" + "-" * 60)
    if all_passed:
        print("[成功] 所有并发测试通过！WriteQueue 工作正常。")
    else:
        print("[失败] 部分测试失败！")

    sys.exit(0 if all_passed else 1)
