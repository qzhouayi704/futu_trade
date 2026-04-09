#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路由层异常处理属性测试

Property 1: 路由层异常处理始终返回标准格式
**Validates: Requirements 1.1, 6.5**
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch
from hypothesis import given, settings
from hypothesis import strategies as st
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from simple_trade.routers.trading.advisor import router


def _create_test_app():
    app = FastAPI()
    app.include_router(router)
    return app


exception_types = st.sampled_from([
    ValueError, KeyError, AttributeError, RuntimeError,
    TypeError, IndexError, ZeroDivisionError, OSError,
])
exception_messages = st.text(min_size=0, max_size=50)


def _make_mock_container(side_effect=None):
    """创建 mock container，可注入异常到 _build_evaluation_context"""
    container = MagicMock()
    container.decision_advisor = MagicMock()
    container.decision_advisor._ai_enhanced = False
    container.decision_advisor.evaluate.return_value = []
    container.futu_trade_service = MagicMock()
    container.db_manager = MagicMock()
    return container


def _run_async(coro):
    """同步运行异步函数，兼容 hypothesis"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _post_evaluate(app, container, build_ctx_side_effect=None):
    """发送 POST /api/advisor/evaluate 请求"""
    from simple_trade.dependencies import get_container as dep_fn
    app.dependency_overrides[dep_fn] = lambda: container

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        if build_ctx_side_effect:
            with patch(
                'simple_trade.routers.trading.advisor._build_evaluation_context',
                side_effect=build_ctx_side_effect,
            ):
                return await client.post("/api/advisor/evaluate")
        else:
            return await client.post("/api/advisor/evaluate")


# ==================== Property 1 属性测试 ====================

@given(exc_type=exception_types, msg=exception_messages)
@settings(max_examples=100)
def test_any_exception_returns_standard_format(exc_type, msg):
    """Property 1: 任意异常类型都应返回 {success: false, message: "评估失败: ..."}

    **Validates: Requirements 1.1, 6.5**
    """
    app = _create_test_app()
    container = _make_mock_container()
    exc = exc_type(msg)

    resp = _run_async(_post_evaluate(app, container, build_ctx_side_effect=exc))

    assert resp.status_code == 200
    data = resp.json()
    assert data['success'] is False
    assert '评估失败' in data['message']


# ==================== 单元测试 ====================

@pytest.mark.anyio
async def test_service_not_initialized():
    """服务未初始化时返回标准格式"""
    app = _create_test_app()
    container = MagicMock()
    container.decision_advisor = None

    resp = await _post_evaluate(app, container)

    assert resp.status_code == 200
    data = resp.json()
    assert data['success'] is False
    assert '未初始化' in data['message']


@pytest.mark.anyio
async def test_no_positions_returns_empty():
    """无持仓时返回空列表"""
    app = _create_test_app()
    container = _make_mock_container()

    from simple_trade.services.advisor.models import EvaluationContext
    empty_ctx = EvaluationContext(positions=[], quotes=[], signals=[], kline_cache={})

    with patch(
        'simple_trade.routers.trading.advisor._build_evaluation_context',
        return_value=empty_ctx,
    ):
        resp = await _post_evaluate(app, container)

    assert resp.status_code == 200
    data = resp.json()
    assert data['success'] is True
