#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途API连接稳定性独立测试（不依赖futu库导入）

测试内容：
1. TCP连接稳定性（连续20次连接）
2. 有代理 vs 无代理对比
3. 连接延迟分布
"""

import os
import sys
import time
import socket
import struct
import hashlib
import logging
import statistics

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

HOST = '127.0.0.1'
PORT = 11111


def check_proxy_env():
    """检查代理环境变量"""
    logger.info(f"\n{'='*60}")
    logger.info(f"[代理环境变量检查]")
    logger.info(f"{'='*60}")
    
    proxy_vars = ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 
                  'http_proxy', 'https_proxy', 'all_proxy',
                  'NO_PROXY', 'no_proxy']
    found = {}
    for var in proxy_vars:
        val = os.environ.get(var)
        if val:
            found[var] = val
            logger.info(f"  {var} = {val}")
    
    if not found:
        logger.info("  ✅ 未检测到任何代理环境变量")
    
    return found


def test_tcp_round(host, port, rounds=20, label=""):
    """TCP连接测试：连续N轮"""
    logger.info(f"\n{'='*60}")
    logger.info(f"[TCP连接测试] {label} - 连续{rounds}轮")
    logger.info(f"  目标: {host}:{port}")
    logger.info(f"{'='*60}")
    
    results = []
    for i in range(rounds):
        start = time.perf_counter()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            latency_ms = (time.perf_counter() - start) * 1000
            
            # 尝试读取一点数据（看OpenD是否响应）
            sock.settimeout(2)
            try:
                # 发送一个简单的futu协议初始化包头看是否有响应
                sock.sendall(b'\x00' * 4)  # dummy probe
                time.sleep(0.05)
            except:
                pass
            
            sock.close()
            results.append(('OK', latency_ms))
            status = "✅"
        except socket.timeout:
            latency_ms = (time.perf_counter() - start) * 1000
            results.append(('TIMEOUT', latency_ms))
            status = "⏱️ TIMEOUT"
        except ConnectionRefusedError:
            latency_ms = (time.perf_counter() - start) * 1000
            results.append(('REFUSED', latency_ms))
            status = "❌ REFUSED"
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            results.append(('ERROR', latency_ms, str(e)))
            status = f"❌ {e}"
        
        logger.info(f"  #{i+1:2d}: {status} ({latency_ms:.1f}ms)")
        time.sleep(0.2)  # 间隔200ms
    
    # 统计
    ok_results = [r[1] for r in results if r[0] == 'OK']
    fail_count = len([r for r in results if r[0] != 'OK'])
    
    logger.info(f"\n  --- 统计 ---")
    logger.info(f"  成功: {len(ok_results)}/{rounds}")
    logger.info(f"  失败: {fail_count}/{rounds}")
    if ok_results:
        logger.info(f"  延迟: 平均={statistics.mean(ok_results):.1f}ms, "
                     f"中位={statistics.median(ok_results):.1f}ms, "
                     f"最大={max(ok_results):.1f}ms, "
                     f"最小={min(ok_results):.1f}ms")
        if len(ok_results) > 1:
            logger.info(f"  标准差: {statistics.stdev(ok_results):.1f}ms")
    
    return results


def test_futu_protocol(host, port, rounds=10, label=""):
    """使用futu协议测试（设置环境变量绕过protobuf问题）"""
    logger.info(f"\n{'='*60}")
    logger.info(f"[Futu协议测试] {label} - 连续{rounds}轮")
    logger.info(f"{'='*60}")
    
    # 设置环境变量绕过protobuf兼容性问题
    os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'
    
    try:
        from futu import OpenQuoteContext, RET_OK
        
        results = []
        for i in range(rounds):
            start = time.perf_counter()
            ctx = None
            try:
                ctx = OpenQuoteContext(host=host, port=port)
                ret, data = ctx.get_stock_quote(['HK.00700'])
                latency_ms = (time.perf_counter() - start) * 1000
                
                if ret == RET_OK and data is not None and len(data) > 0:
                    last_price = data['last_price'].iloc[0]
                    results.append(('OK', latency_ms))
                    logger.info(f"  #{i+1:2d}: ✅ 腾讯报价={last_price} ({latency_ms:.0f}ms)")
                else:
                    results.append(('FAIL', latency_ms))
                    logger.error(f"  #{i+1:2d}: ❌ 返回异常 ret={ret} ({latency_ms:.0f}ms)")
            except Exception as e:
                latency_ms = (time.perf_counter() - start) * 1000
                results.append(('ERROR', latency_ms, str(e)))
                logger.error(f"  #{i+1:2d}: ❌ {type(e).__name__}: {e} ({latency_ms:.0f}ms)")
            finally:
                if ctx:
                    try:
                        ctx.close()
                    except:
                        pass
            
            time.sleep(1)  # futu协议测试间隔长一点
        
        # 统计
        ok_results = [r[1] for r in results if r[0] == 'OK']
        fail_count = len([r for r in results if r[0] != 'OK'])
        
        logger.info(f"\n  --- 统计 ---")
        logger.info(f"  成功: {len(ok_results)}/{rounds}")
        logger.info(f"  失败: {fail_count}/{rounds}")
        if ok_results:
            logger.info(f"  延迟: 平均={statistics.mean(ok_results):.0f}ms, "
                         f"最大={max(ok_results):.0f}ms, "
                         f"最小={min(ok_results):.0f}ms")
        
        return results
        
    except ImportError as e:
        logger.error(f"  ❌ 无法导入futu库: {e}")
        return []


def main():
    logger.info("=" * 60)
    logger.info("  富途API连接稳定性测试")
    logger.info("=" * 60)
    
    # 1. 检查代理
    proxies = check_proxy_env()
    
    # 2. TCP测试（当前环境）
    current_label = "当前环境" + (" (有代理)" if proxies else " (无代理)")
    tcp_results = test_tcp_round(HOST, PORT, rounds=20, label=current_label)
    
    tcp_ok = all(r[0] == 'OK' for r in tcp_results)
    if not tcp_ok:
        fail_count = len([r for r in tcp_results if r[0] != 'OK'])
        logger.warning(f"\n  ⚠️ TCP测试有{fail_count}次失败，请确认OpenD是否稳定运行")
        if any(r[0] == 'REFUSED' for r in tcp_results):
            logger.error("  ❌ OpenD可能未启动！请检查FutuOpenD进程")
            return
    
    # 3. Futu协议测试（带报价）
    logger.info(f"\n{'='*60}")
    logger.info(f"开始Futu协议级别测试...")
    logger.info(f"{'='*60}")
    
    proto_results = test_futu_protocol(HOST, PORT, rounds=10, label=current_label)
    
    # 4. 如果有代理，测试清除代理后的效果
    if proxies:
        logger.info(f"\n\n{'#'*60}")
        logger.info(f"  对比测试：清除代理环境变量后重新测试")
        logger.info(f"{'#'*60}")
        
        # 保存并清除代理
        saved = {}
        for var in proxies:
            saved[var] = os.environ.pop(var, None)
        
        # 再次TCP测试
        tcp_results_no_proxy = test_tcp_round(HOST, PORT, rounds=20, label="无代理")
        
        # 再次协议测试
        proto_results_no_proxy = test_futu_protocol(HOST, PORT, rounds=10, label="无代理")
        
        # 恢复代理
        for var, val in saved.items():
            if val:
                os.environ[var] = val
        
        # 对比总结
        logger.info(f"\n\n{'='*60}")
        logger.info(f"[对比总结]")
        logger.info(f"{'='*60}")
        
        proxy_ok = len([r for r in tcp_results if r[0] == 'OK'])
        no_proxy_ok = len([r for r in tcp_results_no_proxy if r[0] == 'OK'])
        logger.info(f"  TCP测试 (有代理):  {proxy_ok}/20 成功")
        logger.info(f"  TCP测试 (无代理):  {no_proxy_ok}/20 成功")
        
        if proto_results and proto_results_no_proxy:
            p_ok = len([r for r in proto_results if r[0] == 'OK'])
            np_ok = len([r for r in proto_results_no_proxy if r[0] == 'OK'])
            logger.info(f"  协议测试(有代理):  {p_ok}/10 成功")
            logger.info(f"  协议测试(无代理):  {np_ok}/10 成功")
            
            p_lat = [r[1] for r in proto_results if r[0] == 'OK']
            np_lat = [r[1] for r in proto_results_no_proxy if r[0] == 'OK']
            if p_lat and np_lat:
                logger.info(f"  协议延迟(有代理):  平均 {statistics.mean(p_lat):.0f}ms")
                logger.info(f"  协议延迟(无代理):  平均 {statistics.mean(np_lat):.0f}ms")
        
        if proxy_ok < no_proxy_ok or (proto_results and proto_results_no_proxy and p_ok < np_ok):
            logger.warning(f"\n  ⚠️ 代理可能影响了连接稳定性！")
            logger.warning(f"  建议在.env中添加: NO_PROXY=127.0.0.1,localhost")
        else:
            logger.info(f"\n  ✅ 代理未明显影响连接稳定性")
    
    logger.info(f"\n测试完成。")


if __name__ == '__main__':
    main()
