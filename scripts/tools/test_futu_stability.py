#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途API连接稳定性测试

测试内容：
1. TCP连接测试（直连 vs 代理）
2. 连续API调用稳定性（模拟启动时的高频调用）
3. 连接延迟测量
"""

import os
import sys
import time
import socket
import logging

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def test_tcp_connection(host, port, timeout=5):
    """测试TCP连接"""
    logger.info(f"\n{'='*60}")
    logger.info(f"[TCP测试] 目标: {host}:{port}")
    logger.info(f"{'='*60}")

    # 检查代理环境变量
    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'NO_PROXY', 'no_proxy']
    has_proxy = False
    for var in proxy_vars:
        val = os.environ.get(var)
        if val:
            logger.info(f"  代理环境变量 {var} = {val}")
            has_proxy = True
    if not has_proxy:
        logger.info("  未检测到代理环境变量")

    # TCP直连测试
    results = []
    for i in range(5):
        start = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            latency = (time.time() - start) * 1000
            results.append(('OK', latency))
            sock.close()
        except Exception as e:
            latency = (time.time() - start) * 1000
            results.append(('FAIL', latency, str(e)))

    for i, r in enumerate(results):
        if r[0] == 'OK':
            logger.info(f"  TCP #{i+1}: ✅ 连接成功 ({r[1]:.1f}ms)")
        else:
            logger.error(f"  TCP #{i+1}: ❌ 连接失败 ({r[1]:.1f}ms) - {r[2]}")

    return all(r[0] == 'OK' for r in results)


def test_api_stability(host, port, rounds=10):
    """测试API调用稳定性（模拟启动时高频调用）"""
    logger.info(f"\n{'='*60}")
    logger.info(f"[API稳定性测试] 连续{rounds}轮调用")
    logger.info(f"{'='*60}")

    from simple_trade.api.futu_client import FutuClient

    client = FutuClient(host=host, port=port)
    if not client.connect():
        logger.error("❌ 无法连接富途API，跳过稳定性测试")
        return

    logger.info("✅ 连接成功，开始稳定性测试...\n")

    success_count = 0
    fail_count = 0
    latencies = []

    for i in range(rounds):
        start = time.time()
        try:
            # 测试1: get_stock_quote（活跃度检查的核心调用）
            ret, data = client.client.get_stock_quote(['HK.00700'])
            latency = (time.time() - start) * 1000

            from futu import RET_OK
            if ret == RET_OK and data is not None:
                success_count += 1
                latencies.append(latency)
                logger.info(f"  轮次 {i+1:2d}/{rounds}: ✅ 报价获取成功 ({latency:.0f}ms)")
            else:
                fail_count += 1
                logger.error(f"  轮次 {i+1:2d}/{rounds}: ❌ 报价获取失败 ret={ret} ({latency:.0f}ms)")

        except Exception as e:
            latency = (time.time() - start) * 1000
            fail_count += 1
            logger.error(f"  轮次 {i+1:2d}/{rounds}: ❌ 异常 {type(e).__name__}: {e} ({latency:.0f}ms)")

        # 模拟真实调用间隔
        time.sleep(0.5)

    # 测试2: 订阅/反订阅（活跃度检查的另一个核心操作）
    logger.info(f"\n--- 订阅/反订阅测试 ---")
    sub_codes = ['HK.09988', 'HK.01810', 'HK.02318']
    try:
        from futu import SubType
        start = time.time()
        ret, err = client.client.subscribe(sub_codes, [SubType.QUOTE])
        latency = (time.time() - start) * 1000
        if ret == RET_OK:
            logger.info(f"  订阅 {len(sub_codes)} 只: ✅ 成功 ({latency:.0f}ms)")
        else:
            logger.error(f"  订阅 {len(sub_codes)} 只: ❌ 失败 ret={ret} err={err} ({latency:.0f}ms)")

        time.sleep(2)

        start = time.time()
        ret, err = client.client.unsubscribe(sub_codes, [SubType.QUOTE])
        latency = (time.time() - start) * 1000
        if ret == RET_OK:
            logger.info(f"  反订阅 {len(sub_codes)} 只: ✅ 成功 ({latency:.0f}ms)")
        else:
            logger.error(f"  反订阅 {len(sub_codes)} 只: ❌ 失败 ret={ret} err={err} ({latency:.0f}ms)")
    except Exception as e:
        logger.error(f"  订阅/反订阅测试异常: {e}")

    # 汇总
    logger.info(f"\n{'='*60}")
    logger.info(f"[测试汇总]")
    logger.info(f"{'='*60}")
    logger.info(f"  报价测试: {success_count}/{rounds} 成功, {fail_count}/{rounds} 失败")
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)
        min_latency = min(latencies)
        logger.info(f"  延迟: 平均 {avg_latency:.0f}ms, 最小 {min_latency:.0f}ms, 最大 {max_latency:.0f}ms")

    if fail_count > 0:
        logger.warning(f"\n  ⚠️ 存在失败调用！如果是代理问题，尝试:")
        logger.warning(f"     set NO_PROXY=127.0.0.1,localhost")
        logger.warning(f"     或检查富途OpenD是否稳定运行")
    else:
        logger.info(f"\n  ✅ 所有测试通过，API连接稳定")

    client.disconnect()


def main():
    from simple_trade.config.config import Config
    config = Config()
    host = config.futu_host
    port = config.futu_port

    logger.info(f"富途API稳定性测试")
    logger.info(f"配置: host={host}, port={port}")

    # 1. TCP连接测试
    tcp_ok = test_tcp_connection(host, port)

    if not tcp_ok:
        logger.error("TCP连接不稳定，可能是网络/代理问题")
        return

    # 2. API稳定性测试
    test_api_stability(host, port, rounds=10)


if __name__ == '__main__':
    main()
