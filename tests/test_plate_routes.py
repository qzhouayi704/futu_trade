#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plate_routes.py 持仓查询统一性单元测试

通过 AST 解析源文件，验证：
- plate_routes 模块不包含 _get_position_codes 私有函数 (Requirements 2.3)
- plate_routes 中使用的是 route_helpers.get_position_codes (Requirements 2.1, 2.2)

使用 AST 方式避免触发 simple_trade 的重量级初始化链。
"""

import ast
from pathlib import Path

import pytest

# 被测文件路径
PLATE_ROUTES_FILE = Path("simple_trade/routers/market/plate_routes.py")
ROUTE_HELPERS_FILE = Path("simple_trade/routers/data/helpers/route_helpers.py")


def _extract_function_names(filepath: Path) -> set[str]:
    """通过 AST 解析源文件，提取所有顶层函数名"""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _extract_imports_from(filepath: Path) -> list[dict]:
    """
    通过 AST 解析源文件，提取所有 from ... import ... 语句。

    Returns:
        [{"module": "...route_helpers", "names": ["get_position_codes", ...]}, ...]
    """
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            imports.append({"module": node.module or "", "names": names})
    return imports


def _extract_function_calls(filepath: Path) -> list[str]:
    """
    通过 AST 解析源文件，提取所有函数调用的名称（仅 Name 类型的简单调用）。

    Returns:
        ["get_position_codes", "get_state_manager", ...]
    """
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))

    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.append(node.func.id)
    return calls


# ---------- 持仓查询统一性验证 ----------


class TestPositionCodesUnified:
    """验证持仓查询逻辑已统一到 route_helpers"""

    def test_plate_routes_no_private_get_position_codes(self):
        """plate_routes.py 中不应存在 _get_position_codes 私有函数"""
        func_names = _extract_function_names(PLATE_ROUTES_FILE)
        assert "_get_position_codes" not in func_names, (
            "_get_position_codes 私有函数仍存在于 plate_routes.py 中，"
            "应使用 route_helpers.get_position_codes 替代"
        )

    def test_plate_routes_imports_from_route_helpers(self):
        """plate_routes.py 应从 route_helpers 导入 get_position_codes"""
        imports = _extract_imports_from(PLATE_ROUTES_FILE)
        route_helpers_import = [
            imp for imp in imports
            if "route_helpers" in imp["module"]
        ]
        assert route_helpers_import, (
            "plate_routes.py 中未找到从 route_helpers 的导入"
        )
        imported_names = []
        for imp in route_helpers_import:
            imported_names.extend(imp["names"])
        assert "get_position_codes" in imported_names, (
            "plate_routes.py 未从 route_helpers 导入 get_position_codes"
        )

    def test_plate_routes_calls_get_position_codes(self):
        """plate_routes.py 中应调用 get_position_codes（而非 _get_position_codes）"""
        calls = _extract_function_calls(PLATE_ROUTES_FILE)
        assert "get_position_codes" in calls, (
            "plate_routes.py 中未调用 get_position_codes"
        )
        assert "_get_position_codes" not in calls, (
            "plate_routes.py 中仍在调用 _get_position_codes"
        )

    def test_route_helpers_has_get_position_codes(self):
        """route_helpers.py 应提供 get_position_codes 函数作为统一入口"""
        func_names = _extract_function_names(ROUTE_HELPERS_FILE)
        assert "get_position_codes" in func_names, (
            "route_helpers.py 中未定义 get_position_codes 函数"
        )
