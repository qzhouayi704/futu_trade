#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分时数据查询服务
负责分时数据的保存和获取
"""

import logging
from typing import List, Dict, Any
import pandas as pd
from datetime import datetime

from ..core.connection_manager import ConnectionManager
from ..core.base_queries import BaseQueries


class RtDataQueries(BaseQueries):
    """分时数据查询服务"""

    def __init__(self, conn_manager: ConnectionManager):
        super().__init__(conn_manager)

    def batch_upsert_rt_data(self, stock_code: str, df: pd.DataFrame) -> bool:
        """批量保存分时数据（存在则忽略）
        
        Args:
            stock_code: 股票代码
            df: 富途接口返回的分时数据DataFrame
                包含字段: time, cur_price, avg_price, volume, turnover
                
        Returns:
            是否保存成功
        """
        if df is None or df.empty:
            return False
            
        try:
            today_str = datetime.now().strftime('%Y-%m-%d')
            params_list = []
            
            for _, row in df.iterrows():
                time_val = str(row.get('time', ''))
                cur_price = float(row.get('cur_price', 0))
                avg_price = float(row.get('avg_price', 0))
                volume = int(row.get('volume', 0))
                turnover = float(row.get('turnover', 0))
                
                if not time_val:
                    continue
                    
                # 尝试从 time 中提取 trade_date，如果包含空格则取前半部分，否则使用今天
                parts = time_val.split(' ')
                trade_date = parts[0] if len(parts) > 1 and '-' in parts[0] else today_str
                
                params_list.append((
                    stock_code, time_val, cur_price, avg_price, volume, turnover, trade_date
                ))
            
            if not params_list:
                return False
                
            query = '''
                INSERT OR IGNORE INTO rt_data 
                (stock_code, time, cur_price, avg_price, volume, turnover, trade_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            '''
            
            success_count = self.execute_batch(query, params_list)
            if success_count >= 0:
                logging.debug(f"成功保存 {stock_code} 的 {success_count} 条分时数据")
                return True
            return False
            
        except Exception as e:
            logging.error(f"批量保存分时数据失败 {stock_code}: {e}")
            return False

    def get_rt_data(self, stock_code: str, trade_date: str = None) -> List[Dict[str, Any]]:
        """获取指定日期的分时数据
        
        Args:
            stock_code: 股票代码
            trade_date: 交易日期 (YYYY-MM-DD)，默认为今天
            
        Returns:
            分时数据列表，按时间升序排列
        """
        try:
            if trade_date is None:
                trade_date = datetime.now().strftime('%Y-%m-%d')
                
            query = '''
                SELECT time, cur_price as price, avg_price, volume, turnover
                FROM rt_data
                WHERE stock_code = ? AND trade_date = ?
                ORDER BY time ASC
            '''
            
            rows = self.execute_query(query, (stock_code, trade_date))
            
            result = []
            for row in rows:
                result.append({
                    "time": row[0],
                    "price": float(row[1]) if row[1] is not None else 0.0,
                    "avg_price": float(row[2]) if row[2] is not None else 0.0,
                    "volume": float(row[3]) if row[3] is not None else 0.0,
                    "turnover": float(row[4]) if row[4] is not None else 0.0
                })
                
            return result
            
        except Exception as e:
            logging.error(f"获取分时数据失败 {stock_code} ({trade_date}): {e}")
            return []
