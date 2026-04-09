#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强热度分析 - 首页数据复用接口单元测试

测试 get_hot_plates_summary 和 get_hot_stocks_summary 接口逻辑。
"""

import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from fastapi import FastAPI

from simple_trade.routers.data.enhanced_heat_summary import router
from simple_trade.dependencies import get_container


@pytest.fixture
def mock_container():
    """模拟服务容器"""
    container = MagicMock()
    container.config = None
    return container


@pytest.fixture
def app(mock_container):
    """创建测试用 FastAPI 应用，覆盖 get_container 依赖"""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.dependency_overrides[get_container] = lambda: mock_container
    return test_app


@pytest.fixture
def mock_quotes():
    """模拟实时报价数据"""
    return [
        {'code': 'HK.00700', 'stock_name': '腾讯控股', 'change_pct': 5.0,
         'volume': 1000000, 'volume_ratio': 2.0, 'turnover_rate': 3.0,
         'last_price': 380.0, 'net_inflow_ratio': 0.1},
        {'code': 'HK.09988', 'stock_name': '阿里巴巴', 'change_pct': 3.5,
         'volume': 800000, 'volume_ratio': 1.8, 'turnover_rate': 2.5,
         'last_price': 85.0, 'net_inflow_ratio': 0.05},
        {'code': 'HK.03690', 'stock_name': '美团', 'change_pct': -1.0,
         'volume': 500000, 'volume_ratio': 0.8, 'turnover_rate': 1.5,
         'last_price': 120.0, 'net_inflow_ratio': -0.02},
        {'code': 'HK.00005', 'stock_name': '汇丰控股', 'change_pct': 1.0,
         'volume': 600000, 'volume_ratio': 1.2, 'turnover_rate': 1.0,
         'last_price': 60.0, 'net_inflow_ratio': 0.03},
    ]


@pytest.fixture
def plates_monitor():
    """板块数据（MonitorHeatMonitor 格式，stocks 为代码列表）"""
    return [
        {'plate_code': 'TECH', 'plate_name': '科技板块',
         'stock_count': 3, 'stocks': ['HK.00700', 'HK.09988', 'HK.03690']},
        {'plate_code': 'FIN', 'plate_name': '金融板块',
         'stock_count': 1, 'stocks': ['HK.00005']},
    ]


@pytest.fixture
def plates_filter():
    """板块数据（HotStockFilter 格式，stocks 为字典列表）"""
    return [
        {'plate_code': 'TECH', 'plate_name': '科技板块',
         'stocks': [
             {'stock_code': 'HK.00700', 'stock_name': '腾讯控股', 'market': 'HK'},
             {'stock_code': 'HK.09988', 'stock_name': '阿里巴巴', 'market': 'HK'},
             {'stock_code': 'HK.03690', 'stock_name': '美团', 'market': 'HK'},
         ]},
        {'plate_code': 'FIN', 'plate_name': '金融板块',
         'stocks': [
             {'stock_code': 'HK.00005', 'stock_name': '汇丰控股', 'market': 'HK'},
         ]},
    ]


def _mock_realtime(mock_quotes, plates_monitor, plates_filter):
    """构造 _get_realtime_data 的返回值"""
    quotes_map = {q['code']: q for q in mock_quotes}
    all_codes = set(quotes_map.keys())
    return (mock_quotes, quotes_map, plates_monitor, plates_filter, all_codes)


class TestHotPlatesSummary:
    """热门板块摘要接口测试"""

    def test_returns_success_with_plates(self, app, mock_quotes, plates_monitor, plates_filter):
        """正常返回热门板块数据，按热度分降序排列"""
        rt_data = _mock_realtime(mock_quotes, plates_monitor, plates_filter)

        with patch('simple_trade.routers.data.enhanced_heat_summary._get_realtime_data', return_value=rt_data):
            client = TestClient(app)
            resp = client.get("/api/enhanced-heat/hot-plates-summary")

        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['data']['total'] == 2

        plates = data['data']['hot_plates']
        assert plates[0]['heat_score'] >= plates[1]['heat_score']

        # 每个板块包含必要字段
        required_fields = ['plate_code', 'plate_name', 'avg_change_pct',
                           'up_ratio', 'hot_stock_count', 'leading_stock_name', 'heat_score']
        for plate in plates:
            for field in required_fields:
                assert field in plate, f"缺少字段: {field}"

    def test_empty_data_returns_empty_list(self, app):
        """无数据时返回空列表"""
        with patch('simple_trade.routers.data.enhanced_heat_summary._get_realtime_data',
                   return_value=([], {}, [], [], set())):
            client = TestClient(app)
            resp = client.get("/api/enhanced-heat/hot-plates-summary")

        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['data']['hot_plates'] == []
        assert data['data']['total'] == 0


class TestHotStocksSummary:
    """热门股票摘要接口测试"""

    def test_returns_sorted_hot_stocks(self, app, mock_quotes, plates_monitor, plates_filter):
        """返回按 heat_score 降序排列的热门股票"""
        rt_data = _mock_realtime(mock_quotes, plates_monitor, plates_filter)

        with patch('simple_trade.routers.data.enhanced_heat_summary._get_realtime_data', return_value=rt_data):
            client = TestClient(app)
            resp = client.get("/api/enhanced-heat/hot-stocks-summary?limit=20")

        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert 'hot_stocks' in data['data']

        stocks = data['data']['hot_stocks']
        if len(stocks) > 1:
            for i in range(len(stocks) - 1):
                assert stocks[i]['heat_score'] >= stocks[i + 1]['heat_score']

    def test_limit_parameter(self, app, mock_quotes, plates_monitor, plates_filter):
        """limit 参数限制返回数量"""
        rt_data = _mock_realtime(mock_quotes, plates_monitor, plates_filter)

        with patch('simple_trade.routers.data.enhanced_heat_summary._get_realtime_data', return_value=rt_data):
            client = TestClient(app)
            resp = client.get("/api/enhanced-heat/hot-stocks-summary?limit=1")

        assert resp.status_code == 200
        assert resp.json()['data']['total'] <= 1

    def test_empty_data_returns_empty(self, app):
        """无数据时返回空列表"""
        with patch('simple_trade.routers.data.enhanced_heat_summary._get_realtime_data',
                   return_value=([], {}, [], [], set())):
            client = TestClient(app)
            resp = client.get("/api/enhanced-heat/hot-stocks-summary")

        assert resp.status_code == 200
        data = resp.json()
        assert data['success'] is True
        assert data['data']['hot_stocks'] == []
        assert data['data']['total'] == 0
