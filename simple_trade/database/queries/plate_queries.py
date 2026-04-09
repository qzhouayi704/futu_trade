#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块相关查询服务
负责所有板块数据的查询和更新操作
"""

import logging
from typing import List, Dict, Any
from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries


class PlateQueries(BaseQueries):
    """板块查询服务"""

    def __init__(self, conn_manager: ConnectionManager):
        """初始化板块查询服务

        Args:
            conn_manager: 连接管理器实例
        """
        super().__init__(conn_manager)

    def get_plates_with_stock_count(self) -> list:
        """获取板块列表（包含股票数量，使用stock_plates多对多关联）

        只返回目标板块且已启用的板块

        Returns:
            板块列表（含股票数量）
        """
        query = '''
            SELECT p.id, p.plate_code, p.plate_name, p.market,
                   COUNT(DISTINCT sp.stock_id) as stock_count
            FROM plates p
            LEFT JOIN stock_plates sp ON p.id = sp.plate_id
            WHERE p.is_target = 1 AND COALESCE(p.is_enabled, 1) = 1
            GROUP BY p.id
            ORDER BY p.plate_code
        '''
        return self.execute_query(query)
