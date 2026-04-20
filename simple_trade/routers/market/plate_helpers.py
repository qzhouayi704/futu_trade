#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
板块路由共享辅助函数

供 routers/plate.py 使用，
避免代码重复。
"""

import logging
from typing import List, Optional

from ...core import get_state_manager
from ...core.exceptions import BusinessError


def fetch_available_plates(
    container,
    search: Optional[str] = None,
    market: Optional[str] = None,
    status: Optional[str] = None,
) -> List[dict]:
    """获取可用板块列表（核心逻辑）

    Args:
        container: 服务容器
        search: 搜索关键词
        market: 市场过滤 (HK/US)
        status: 状态过滤 (added/not-added)

    Returns:
        过滤后的板块列表
    """
    state = get_state_manager()

    if not container.futu_client or not container.futu_client.is_available():
        raise BusinessError("富途API客户端不可用")

    from futu import Market
    available_plates = []

    # 获取港股板块
    if not market or market == 'HK':
        ret, hk_plates = container.futu_client.get_plate_list(Market.HK, 'ALL')
        if ret == 0 and hk_plates is not None:
            for plate in hk_plates.to_dict('records'):
                available_plates.append({
                    'plate_code': plate['code'],
                    'plate_name': plate['plate_name'],
                    'market': 'HK'
                })

    # 获取美股板块
    if not market or market == 'US':
        ret, us_plates = container.futu_client.get_plate_list(Market.US, 'ALL')
        if ret == 0 and us_plates is not None:
            for plate in us_plates.to_dict('records'):
                available_plates.append({
                    'plate_code': plate['code'],
                    'plate_name': plate['plate_name'],
                    'market': 'US'
                })

    # 获取已添加的板块
    pool_data = state.get_stock_pool()
    added_plates = {p['code']: True for p in pool_data['plates']}

    # 过滤和处理
    result_plates = []
    for plate in available_plates:
        plate_code = plate['plate_code']
        is_added = plate_code in added_plates

        # 搜索过滤
        if search:
            search_lower = search.lower()
            if (search_lower not in plate_code.lower() and
                    search_lower not in plate['plate_name'].lower()):
                continue

        # 状态过滤
        if status == 'added' and not is_added:
            continue
        elif status == 'not-added' and is_added:
            continue

        result_plates.append({
            'plate_code': plate_code,
            'plate_name': plate['plate_name'],
            'market': plate['market'],
            'is_added': is_added,
            'status': '已添加' if is_added else '未添加'
        })

    return result_plates
