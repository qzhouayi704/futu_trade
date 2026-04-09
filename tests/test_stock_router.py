#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stock.py 路由注册与端点回归单元测试

通过 AST 解析源文件中的路由装饰器，验证：
- stock.py 的 router 不包含 /stocks/top-hot 路径 (Requirements 1.1)
- stock.py 保留的所有端点仍然可达 (Requirements 1.2, 1.3)

使用 AST 方式避免触发 simple_trade 的重量级初始化链。
"""

import ast
from pathlib import Path

import pytest

# 被测文件路径
STOCK_ROUTER_FILE = Path("simple_trade/routers/data/stock.py")


def _extract_routes_from_source(filepath: Path) -> list[tuple[str, str]]:
    """
    通过 AST 解析源文件，提取所有 @router.<method>("<path>") 装饰器信息。

    Returns:
        [(http_method, path), ...] 例如 [("GET", "/stocks/pool"), ("POST", "/init")]
    """
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))

    routes: list[tuple[str, str]] = []

    for node in ast.walk(tree):
        # 查找函数定义上的装饰器
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        for decorator in node.decorator_list:
            # 匹配 @router.get("/path") 或 @router.post("/path") 形式
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute):
                continue
            if not isinstance(func.value, ast.Name):
                continue
            if func.value.id != "router":
                continue

            http_method = func.attr.upper()  # get -> GET, post -> POST
            # 第一个位置参数是路径
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                path = decorator.args[0].value
                routes.append((http_method, path))

    return routes


@pytest.fixture(scope="module")
def registered_routes() -> list[tuple[str, str]]:
    """模块级 fixture：解析 stock.py 中的所有路由"""
    assert STOCK_ROUTER_FILE.exists(), f"被测文件不存在: {STOCK_ROUTER_FILE}"
    return _extract_routes_from_source(STOCK_ROUTER_FILE)


@pytest.fixture(scope="module")
def route_paths(registered_routes) -> set[str]:
    """所有已注册路由的路径集合"""
    return {path for _, path in registered_routes}


@pytest.fixture(scope="module")
def route_method_map(registered_routes) -> dict[str, str]:
    """路径 -> HTTP 方法的映射"""
    return {path: method for method, path in registered_routes}


# ---------- 路由冲突修复验证 ----------


class TestTopHotRemoved:
    """验证 /stocks/top-hot 端点已从 stock.py 中移除"""

    def test_router_does_not_contain_top_hot(self, route_paths):
        """/stocks/top-hot 不应出现在 stock.py 的路由中"""
        assert "/stocks/top-hot" not in route_paths, (
            "/stocks/top-hot 仍然注册在 stock.py 中，路由冲突未修复"
        )

    def test_no_get_top_hot_stocks_function(self):
        """stock.py 中不应存在 get_top_hot_stocks 函数定义"""
        source = STOCK_ROUTER_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        func_names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "get_top_hot_stocks" not in func_names, (
            "get_top_hot_stocks 函数仍存在于 stock.py 中"
        )


# ---------- 保留端点回归验证 ----------

# 设计文档中明确列出的保留端点
EXPECTED_ENDPOINTS = {
    ("/stocks/pool", "GET"),
    ("/data", "GET"),
    ("/init", "POST"),
    ("/refresh", "POST"),
    ("/init/status", "GET"),
    ("/stocks/unsubscribed", "GET"),
    ("/stocks/activity/reset", "POST"),
}


class TestRetainedEndpoints:
    """验证 stock.py 保留的所有端点仍然可达"""

    @pytest.mark.parametrize(
        "path,method",
        sorted(EXPECTED_ENDPOINTS),
        ids=[f"{m} {p}" for p, m in sorted(EXPECTED_ENDPOINTS)],
    )
    def test_endpoint_registered(self, registered_routes, path, method):
        """端点 {method} {path} 应存在于 router 中"""
        assert (method, path) in registered_routes, (
            f"端点 {method} {path} 未在 stock.py 的 router 中注册"
        )

    def test_expected_endpoint_count(self, registered_routes):
        """router 中的端点数量应与预期一致（不多不少）"""
        expected_count = len(EXPECTED_ENDPOINTS)
        actual_count = len(registered_routes)
        assert actual_count == expected_count, (
            f"预期 {expected_count} 个端点，实际 {actual_count} 个。"
            f"已注册: {registered_routes}"
        )
