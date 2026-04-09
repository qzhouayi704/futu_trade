#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓管理服务
负责持仓的查询、统计和同步
"""

import logging
from typing import Dict, Any, List

from ....database.core.db_manager import DatabaseManager
from ...pool.stock_pool import refresh_global_stock_pool_from_db

# 富途交易API
try:
    from futu import RET_OK, RET_ERROR
    FUTU_TRADE_AVAILABLE = True
except ImportError:
    FUTU_TRADE_AVAILABLE = False
    RET_OK = None
    RET_ERROR = None


class PositionManager:
    """持仓管理器"""

    def __init__(self, db_manager: DatabaseManager, trade_client=None):
        """
        初始化持仓管理器

        Args:
            db_manager: 数据库管理器
            trade_client: 富途交易客户端
        """
        self.db_manager = db_manager
        self.trade_client = trade_client

    def set_trade_client(self, trade_client):
        """设置富途交易客户端"""
        self.trade_client = trade_client

    def get_positions(self) -> Dict[str, Any]:
        """
        获取持仓信息

        Returns:
            包含持仓列表的字典
        """
        result = {
            'success': False,
            'message': '',
            'positions': []
        }

        if not self.trade_client:
            result['message'] = "交易客户端未初始化"
            return result

        try:
            ret, data = self.trade_client.position_list_query()

            if ret == RET_OK and data is not None:
                positions = []
                for _, row in data.iterrows():
                    # 获取原始数据
                    pl_ratio = row.get('pl_ratio', 0)

                    positions.append({
                        'stock_code': row.get('code', ''),
                        'stock_name': row.get('stock_name', ''),
                        # 兼容前端字段名
                        'quantity': row.get('qty', 0),
                        'avg_price': row.get('cost_price', 0),
                        'current_price': row.get('nominal_price', 0),
                        'market_value': row.get('market_val', 0),
                        'profit_loss': row.get('pl_val', 0),
                        'profit_loss_pct': pl_ratio * 100 if pl_ratio else 0,  # 转换为百分比
                        # 保留原始字段名（向后兼容）
                        'qty': row.get('qty', 0),
                        'can_sell_qty': row.get('can_sell_qty', 0),
                        'market_val': row.get('market_val', 0),
                        'nominal_price': row.get('nominal_price', 0),
                        'cost_price': row.get('cost_price', 0),
                        'pl_ratio': pl_ratio,
                        'pl_val': row.get('pl_val', 0)
                    })

                result.update({
                    'success': True,
                    'message': f"获取到 {len(positions)} 个持仓",
                    'positions': positions
                })

            else:
                result['message'] = f"获取持仓信息失败: ret={ret}, data={data}"

        except Exception as e:
            logging.error(f"获取持仓信息异常: {e}")
            result['message'] = f"获取持仓信息异常: {str(e)}"

        return result

    def sync_positions_to_stock_pool(self, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        将持仓股票同步到监控股票池

        创建或更新"持仓监控"板块，将当前持仓股票加入监控

        Args:
            positions: 持仓列表

        Returns:
            同步结果字典
        """
        result = {
            'success': False,
            'message': '',
            'added_count': 0,
            'removed_count': 0
        }

        if not positions:
            result['success'] = True
            result['message'] = '没有持仓股票需要同步'
            return result

        try:
            # 持仓监控板块的固定信息
            POSITION_PLATE_CODE = 'POSITION_MONITOR'
            POSITION_PLATE_NAME = '持仓监控'

            # 1. 确保"持仓监控"板块存在
            plate_result = self.db_manager.execute_query(
                'SELECT id FROM plates WHERE plate_code = ?', (POSITION_PLATE_CODE,)
            )

            if plate_result:
                plate_id = plate_result[0][0]
                logging.debug(f"持仓监控板块已存在，ID: {plate_id}")
            else:
                # 创建持仓监控板块
                self.db_manager.execute_update('''
                    INSERT INTO plates (plate_code, plate_name, market, category, stock_count, is_target, is_enabled, priority)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (POSITION_PLATE_CODE, POSITION_PLATE_NAME, 'HK', '持仓', 0, 1, 1, 999))

                plate_result = self.db_manager.execute_query(
                    'SELECT id FROM plates WHERE plate_code = ?', (POSITION_PLATE_CODE,)
                )
                plate_id = plate_result[0][0]
                logging.info(f"创建持仓监控板块，ID: {plate_id}")

            # 2. 获取当前持仓股票代码列表
            position_codes = set()
            for pos in positions:
                if pos.get('qty', 0) > 0:  # 只同步有持仓的股票
                    position_codes.add(pos.get('stock_code', ''))

            # 3. 获取板块中现有的股票
            existing_stocks = self.db_manager.execute_query('''
                SELECT s.id, s.code FROM stocks s
                INNER JOIN stock_plates sp ON s.id = sp.stock_id
                WHERE sp.plate_id = ?
            ''', (plate_id,))

            existing_codes = {row[1]: row[0] for row in existing_stocks}  # code -> stock_id

            # 4. 添加新的持仓股票
            added_count = 0
            skipped_count = 0  # 记录跳过的低价股数量

            for pos in positions:
                stock_code = pos.get('stock_code', '')
                stock_name = pos.get('stock_name', '')
                qty = pos.get('qty', 0)
                nominal_price = pos.get('nominal_price', 0)  # 获取现价

                if not stock_code or qty <= 0:
                    continue

                # 港股低于1元的股票不加入监控池
                if stock_code.startswith('HK.') and nominal_price < 1.0:
                    logging.info(f"跳过低价港股: {stock_code} ({stock_name}), 现价: {nominal_price}")
                    skipped_count += 1
                    continue

                if stock_code not in existing_codes:
                    # 检查股票是否已存在
                    stock_result = self.db_manager.execute_query(
                        'SELECT id FROM stocks WHERE code = ?', (stock_code,)
                    )

                    if stock_result:
                        stock_id = stock_result[0][0]
                        # 更新股票名称（如果需要）
                        if stock_name:
                            self.db_manager.execute_update(
                                'UPDATE stocks SET name = ? WHERE id = ? AND (name IS NULL OR name = "")',
                                (stock_name, stock_id)
                            )
                    else:
                        # 创建新股票
                        market = 'HK' if stock_code.startswith('HK.') else 'US'
                        self.db_manager.execute_update('''
                            INSERT INTO stocks (code, name, market)
                            VALUES (?, ?, ?)
                        ''', (stock_code, stock_name or stock_code, market))

                        stock_result = self.db_manager.execute_query(
                            'SELECT id FROM stocks WHERE code = ?', (stock_code,)
                        )
                        stock_id = stock_result[0][0]

                    # 添加到持仓监控板块
                    self.db_manager.execute_update('''
                        INSERT OR IGNORE INTO stock_plates (stock_id, plate_id)
                        VALUES (?, ?)
                    ''', (stock_id, plate_id))

                    added_count += 1
                    logging.info(f"添加持仓股票到监控: {stock_code} ({stock_name})")

            # 5. 移除已清仓的股票
            removed_count = 0
            for code, stock_id in existing_codes.items():
                if code not in position_codes:
                    # 从持仓监控板块移除
                    self.db_manager.execute_update('''
                        DELETE FROM stock_plates WHERE stock_id = ? AND plate_id = ?
                    ''', (stock_id, plate_id))

                    removed_count += 1
                    logging.info(f"移除已清仓股票: {code}")

            # 6. 更新板块股票数量
            self.db_manager.execute_update('''
                UPDATE plates SET stock_count = (
                    SELECT COUNT(DISTINCT stock_id) FROM stock_plates WHERE plate_id = ?
                ) WHERE id = ?
            ''', (plate_id, plate_id))

            # 7. 根据变化情况决定是否刷新全局股票池
            if added_count == 0 and removed_count == 0:
                logging.debug(f"持仓同步无变化，跳过股票池刷新")
            else:
                refresh_global_stock_pool_from_db(self.db_manager)
                logging.info(f"持仓同步完成: 添加 {added_count} 只，移除 {removed_count} 只")

            result.update({
                'success': True,
                'message': f'持仓同步完成: 添加 {added_count} 只，移除 {removed_count} 只',
                'added_count': added_count,
                'removed_count': removed_count
            })

        except Exception as e:
            logging.error(f"同步持仓到股票池失败: {e}")
            result['message'] = f"同步失败: {str(e)}"

        return result
