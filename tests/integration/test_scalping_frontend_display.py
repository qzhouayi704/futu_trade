#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scalping引擎前端数据展示测试

测试从数据库逐笔成交数据到前端展示的完整链路：
1. 数据库 ticker_data 表数据验证
2. 后端 API 响应验证
3. 数据一致性验证
4. 前端 TypeScript 格式兼容性验证
"""

import sys
import os
from pathlib import Path
import requests
from datetime import datetime
from typing import Optional, Dict, Any

# 设置控制台编码为UTF-8（Windows兼容）
if sys.platform == 'win32':
    os.system('chcp 65001 > nul')

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 测试配置
TEST_STOCK_CODE = "HK.02706"  # 默认测试股票代码
API_BASE_URL = "http://localhost:8000"  # 后端API地址
DB_PATH = "simple_trade/data/trade.db"  # 数据库路径


# ==================== 辅助函数 ====================


def find_stock_with_data(db_path: str, min_records: int = 100) -> Optional[str]:
    """自动查找数据库中有足够数据的股票代码"""
    from simple_trade.database.core.db_manager import DatabaseManager

    db = DatabaseManager(db_path)

    with db.conn_manager.get_connection() as conn:
        cursor = conn.cursor()
        # 查找今天有数据的股票，按记录数降序
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT stock_code, COUNT(*) as cnt
            FROM ticker_data
            WHERE trade_date = ?
            GROUP BY stock_code
            HAVING cnt >= ?
            ORDER BY cnt DESC
            LIMIT 1
        """, (today, min_records))

        result = cursor.fetchone()
        if result:
            return result[0]

    return None


# ==================== 测试函数 ====================


def test_database_data(stock_code: str, db_path: str) -> Dict[str, Any]:
    """测试A：数据库数据验证"""
    from simple_trade.database.core.db_manager import DatabaseManager

    db = DatabaseManager(db_path)

    # 1. 检查表是否存在
    with db.conn_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ticker_data'")
        table_exists = cursor.fetchone() is not None

    # 2. 获取统计信息
    stats = db.ticker_queries.get_ticker_statistics(stock_code)
    stats['stock_code'] = stock_code  # 添加股票代码到统计信息

    # 3. 获取最近数据样本
    recent_data = db.ticker_queries.get_ticker_data(stock_code, limit=10)

    return {
        'table_exists': table_exists,
        'stats': stats,
        'recent_data': recent_data,
        'has_data': stats.get('total_count', 0) > 0
    }


def test_api_response(stock_code: str, api_url: str) -> Dict[str, Any]:
    """测试B：后端API验证"""
    try:
        url = f"{api_url}/api/enhanced-heat/ticker-analysis/{stock_code}"
        resp = requests.get(url, timeout=10)

        if resp.status_code != 200:
            return {'success': False, 'error': f'HTTP {resp.status_code}'}

        data = resp.json()

        # 验证响应格式
        required_fields = ['success', 'data', 'message']
        for field in required_fields:
            if field not in data:
                return {'success': False, 'error': f'缺少字段: {field}'}

        if not data['success']:
            return {'success': False, 'error': data.get('message')}

        # 验证数据字段
        analysis_data = data['data']
        if analysis_data is None:
            return {'success': True, 'data': None, 'message': '数据暂不可用'}

        required_data_fields = ['stock_code', 'dimensions', 'total_score', 'signal', 'label', 'summary']
        for field in required_data_fields:
            if field not in analysis_data:
                return {'success': False, 'error': f'数据缺少字段: {field}'}

        return {'success': True, 'data': analysis_data}

    except requests.exceptions.ConnectionError:
        return {'success': False, 'error': 'API服务未启动'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def test_data_consistency(db_stats: Dict, api_data: Dict) -> Dict[str, Any]:
    """测试C：数据一致性验证"""
    issues = []

    # 验证股票代码一致
    if api_data.get('stock_code') != db_stats.get('stock_code'):
        issues.append('股票代码不一致')

    # 验证数据维度存在
    dimensions = api_data.get('dimensions', [])
    if len(dimensions) == 0:
        issues.append('维度数据为空')

    # 验证信号类型有效
    valid_signals = ['bullish', 'slightly_bullish', 'neutral', 'slightly_bearish', 'bearish']
    if api_data.get('signal') not in valid_signals:
        issues.append(f"无效的信号类型: {api_data.get('signal')}")

    return {
        'consistent': len(issues) == 0,
        'issues': issues
    }


def test_frontend_format(api_data: Dict) -> Dict[str, Any]:
    """测试D：前端格式验证"""
    issues = []

    # TickerAnalysisData 必需字段
    required_fields = {
        'stock_code': str,
        'dimensions': list,
        'total_score': (int, float),
        'signal': str,
        'label': str,
        'summary': str
    }

    for field, expected_type in required_fields.items():
        if field not in api_data:
            issues.append(f'缺少字段: {field}')
        elif not isinstance(api_data[field], expected_type):
            issues.append(f'字段类型错误: {field} (期望 {expected_type}, 实际 {type(api_data[field])})')

    # 验证 dimensions 结构
    if 'dimensions' in api_data:
        for i, dim in enumerate(api_data['dimensions']):
            dim_required = ['name', 'signal', 'score', 'description', 'details']
            for field in dim_required:
                if field not in dim:
                    issues.append(f'dimensions[{i}] 缺少字段: {field}')

    return {
        'valid': len(issues) == 0,
        'issues': issues
    }


# ==================== 主测试流程 ====================


def run_all_tests(stock_code: Optional[str] = None, api_url: str = API_BASE_URL,
                  db_path: str = DB_PATH, verbose: bool = False) -> bool:
    """运行所有测试"""
    print("\n" + "="*60)
    print("=== Scalping引擎前端数据展示测试 ===")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    # 1. 确定测试股票代码
    if stock_code is None:
        stock_code = TEST_STOCK_CODE
        print(f"\n使用默认股票代码: {stock_code}")

    # 2. 测试A：数据库数据验证
    print("\n[测试A] 数据库数据验证")
    try:
        db_result = test_database_data(stock_code, db_path)
    except Exception as e:
        print(f"  [X] 数据库连接失败: {e}")
        print(f"  提示: 请检查数据库路径 {db_path}")
        return False

    if not db_result['table_exists']:
        print("  [X] ticker_data 表不存在")
        return False

    print("  [OK] ticker_data 表存在")

    if not db_result['has_data']:
        print(f"  [!] {stock_code} 没有数据，尝试自动查找...")
        stock_code = find_stock_with_data(db_path)
        if stock_code is None:
            print("  [X] 数据库中没有任何股票有逐笔数据")
            return False
        print(f"  [OK] 找到有数据的股票: {stock_code}")
        db_result = test_database_data(stock_code, db_path)

    stats = db_result['stats']
    print(f"  [OK] {stock_code} 有 {stats.get('total_count', 0)} 笔数据")
    print(f"  [OK] 买入: {stats.get('buy_count', 0)}笔, 卖出: {stats.get('sell_count', 0)}笔, 中性: {stats.get('neutral_count', 0)}笔")

    if stats.get('first_time'):
        first_time = datetime.fromtimestamp(stats['first_time'] / 1000)
        last_time = datetime.fromtimestamp(stats['last_time'] / 1000)
        print(f"  [OK] 时间范围: {first_time.strftime('%H:%M:%S')} ~ {last_time.strftime('%H:%M:%S')}")

    # 3. 测试B：后端API验证
    print("\n[测试B] 后端API验证")
    api_result = test_api_response(stock_code, api_url)

    if not api_result['success']:
        print(f"  [X] API请求失败: {api_result.get('error')}")
        if 'API服务未启动' in api_result.get('error', ''):
            print("  提示: 请先启动后端服务")
        return False

    print("  [OK] API响应成功 (200)")
    print("  [OK] 响应格式正确 {success: true, data: {...}}")

    api_data = api_result['data']
    if api_data is None:
        print("  [!] API返回数据为空（可能是订阅问题）")
        return False

    print(f"  [OK] 包含必需字段: stock_code, dimensions, signal, label, summary")
    print(f"  [OK] 信号类型: {api_data.get('signal')} ({api_data.get('label')})")
    print(f"  [OK] 总分: {api_data.get('total_score')}")

    if verbose:
        print(f"\n  详细信息:")
        print(f"    摘要: {api_data.get('summary')}")
        for dim in api_data.get('dimensions', []):
            print(f"    - {dim.get('name')}: {dim.get('signal')} (分数: {dim.get('score')})")

    # 4. 测试C：数据一致性验证
    print("\n[测试C] 数据一致性验证")
    consistency_result = test_data_consistency(stats, api_data)

    if not consistency_result['consistent']:
        print("  [X] 数据一致性检查失败:")
        for issue in consistency_result['issues']:
            print(f"    - {issue}")
        return False

    print("  [OK] 股票代码一致")
    print("  [OK] 维度数据完整")
    print("  [OK] 信号类型有效")

    # 5. 测试D：前端格式验证
    print("\n[测试D] 前端格式验证")
    format_result = test_frontend_format(api_data)

    if not format_result['valid']:
        print("  [X] 前端格式验证失败:")
        for issue in format_result['issues']:
            print(f"    - {issue}")
        return False

    print("  [OK] 所有TypeScript字段存在")
    print("  [OK] 数据类型匹配")
    print("  [OK] 嵌套对象结构正确")

    # 6. 测试总结
    print("\n" + "="*60)
    print("=== 测试结果 ===")
    print("[OK] 所有测试通过")
    print(f"测试股票: {stock_code}")
    print(f"数据笔数: {stats.get('total_count', 0)}")
    print(f"信号评级: {api_data.get('label')}")
    print("="*60)

    return True


# ==================== 主入口 ====================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description='Scalping引擎前端数据展示测试',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python tests/integration/test_scalping_frontend_display.py
  python tests/integration/test_scalping_frontend_display.py --stock-code HK.09988
  python tests/integration/test_scalping_frontend_display.py --verbose
  python tests/integration/test_scalping_frontend_display.py --api-url http://localhost:5000
        """
    )
    parser.add_argument('--stock-code', type=str, help='指定测试股票代码')
    parser.add_argument('--api-url', type=str, default=API_BASE_URL, help=f'API服务地址 (默认: {API_BASE_URL})')
    parser.add_argument('--db-path', type=str, default=DB_PATH, help=f'数据库路径 (默认: {DB_PATH})')
    parser.add_argument('--verbose', action='store_true', help='详细输出')

    args = parser.parse_args()

    success = run_all_tests(
        stock_code=args.stock_code,
        api_url=args.api_url,
        db_path=args.db_path,
        verbose=args.verbose
    )

    sys.exit(0 if success else 1)
