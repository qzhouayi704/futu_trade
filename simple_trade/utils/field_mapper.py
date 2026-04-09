#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字段映射管理器 - 统一管理所有字段映射逻辑
"""

import logging
from typing import Any, Dict, List, Optional, Union


class FieldMapper:
    """统一的字段映射管理器"""
    
    # 预定义的字段映射规则
    FIELD_MAPPINGS = {
        # 板块相关字段映射
        'plate': {
            'code': ['plate_code', 'code', 'stock_code'],
            'name': ['plate_name', 'name', 'stock_name'],
            'market': ['market', 'market_code'],
            'type': ['type', 'plate_type']
        },
        
        # 股票相关字段映射
        'stock': {
            'code': ['code', 'stock_code'],
            'name': ['stock_name', 'name'],
            'market': ['market', 'market_code'],
            'last_price': ['last_price', 'current_price', 'price'],
            'prev_close_price': ['prev_close_price', 'prev_close', 'close_price'],
            'change_rate': ['change_rate', 'change_percent', 'pct_change'],
            'volume': ['volume', 'vol', 'trade_volume'],
            'turnover': ['turnover', 'amount', 'trade_amount'],
            'high_price': ['high_price', 'high', 'day_high'],
            'low_price': ['low_price', 'low', 'day_low'],
            'open_price': ['open_price', 'open', 'day_open']
        },
        
        # K线数据字段映射
        'kline': {
            'time': ['time_key', 'time', 'date', 'datetime'],
            'open': ['open', 'open_price'],
            'high': ['high', 'high_price'],
            'low': ['low', 'low_price'],
            'close': ['close', 'close_price'],
            'volume': ['volume', 'vol']
        },
        
        # 报价数据字段映射
        'quote': {
            'code': ['code', 'stock_code'],
            'stock_name': ['stock_name', 'name'],
            'last_price': ['last_price', 'current_price', 'price'],
            'change_percent': ['change_rate', 'change_percent', 'pct_change'],
            'volume': ['volume', 'vol'],
            'turnover': ['turnover', 'amount'],
            'high_price': ['high_price', 'high'],
            'low_price': ['low_price', 'low'],
            'open_price': ['open_price', 'open'],
            'prev_close_price': ['prev_close_price', 'prev_close']
        }
    }
    
    @classmethod
    def extract_field_value(cls, data_row: Union[Dict, Any], target_field: str, 
                           data_type: str = 'stock', default_value: Any = None) -> Any:
        """
        从数据行中提取指定字段的值
        
        Args:
            data_row: 数据行（字典或pandas Series）
            target_field: 目标字段名
            data_type: 数据类型 ('plate', 'stock', 'kline', 'quote')
            default_value: 默认值
            
        Returns:
            提取到的字段值，如果未找到则返回默认值
        """
        try:
            # 获取字段映射规则
            field_mappings = cls.FIELD_MAPPINGS.get(data_type, {})
            possible_fields = field_mappings.get(target_field, [target_field])
            
            # 如果possible_fields不是列表，转换为列表
            if not isinstance(possible_fields, list):
                possible_fields = [possible_fields]
            
            # 尝试从数据行中提取值
            for field_name in possible_fields:
                if hasattr(data_row, 'get'):
                    # 字典类型
                    value = data_row.get(field_name)
                elif hasattr(data_row, field_name):
                    # pandas Series或对象类型
                    value = getattr(data_row, field_name)
                elif isinstance(data_row, dict) and field_name in data_row:
                    # 普通字典
                    value = data_row[field_name]
                else:
                    continue
                
                # 检查值是否有效
                if value is not None and value != '':
                    return value
            
            # 如果所有字段都未找到，返回默认值
            return default_value
            
        except Exception as e:
            logging.debug(f"提取字段 {target_field} 失败: {e}")
            return default_value
    
    @classmethod
    def extract_plate_info(cls, plate_row: Union[Dict, Any], market_code: str = None) -> Optional[Dict[str, Any]]:
        """
        从板块数据行中提取板块信息
        
        Args:
            plate_row: 板块数据行
            market_code: 市场代码
            
        Returns:
            提取的板块信息字典，失败返回None
        """
        try:
            plate_code = cls.extract_field_value(plate_row, 'code', 'plate')
            plate_name = cls.extract_field_value(plate_row, 'name', 'plate')
            
            if not plate_code or not plate_name:
                return None
            
            return {
                'code': str(plate_code),
                'name': str(plate_name),
                'market': market_code or cls.extract_field_value(plate_row, 'market', 'plate', 'HK'),
                'type': cls.extract_field_value(plate_row, 'type', 'plate', 'INDUSTRY')
            }
            
        except Exception as e:
            logging.debug(f"提取板块信息失败: {e}")
            return None
    
    @classmethod
    def extract_stock_info(cls, stock_row: Union[Dict, Any], market_code: str = None) -> Optional[Dict[str, Any]]:
        """
        从股票数据行中提取股票信息
        
        Args:
            stock_row: 股票数据行
            market_code: 市场代码
            
        Returns:
            提取的股票信息字典，失败返回None
        """
        try:
            stock_code = cls.extract_field_value(stock_row, 'code', 'stock')
            
            if not stock_code:
                return None
            
            stock_name = cls.extract_field_value(stock_row, 'name', 'stock', '')
            
            # 如果没有提供市场代码，尝试从股票代码推断
            if not market_code:
                market_code = cls._infer_market_from_code(str(stock_code))
            
            return {
                'code': str(stock_code),
                'name': str(stock_name),
                'market': market_code
            }
            
        except Exception as e:
            logging.debug(f"提取股票信息失败: {e}")
            return None
    
    @classmethod
    def extract_quote_data(cls, quote_row: Union[Dict, Any], stock_info: tuple = None) -> Optional[Dict[str, Any]]:
        """
        从报价数据行中提取报价信息
        
        Args:
            quote_row: 报价数据行
            stock_info: 股票信息元组 (id, code, name, market, plate_name)
            
        Returns:
            提取的报价信息字典，失败返回None
        """
        try:
            code = cls.extract_field_value(quote_row, 'code', 'quote')
            if not code:
                return None
            
            # 提取价格信息
            current_price = float(cls.extract_field_value(quote_row, 'last_price', 'quote', 0))
            prev_close = float(cls.extract_field_value(quote_row, 'prev_close_price', 'quote', 0))
            
            # 计算涨跌幅
            change_percent = 0.0
            if prev_close > 0:
                change_percent = ((current_price - prev_close) / prev_close) * 100
            
            # 优先从富途API报价数据中获取股票名称
            stock_name = cls.extract_field_value(quote_row, 'stock_name', 'quote', None)
            if not stock_name:
                # 尝试其他可能的名称字段
                stock_name = cls.extract_field_value(quote_row, 'name', 'quote', None)
            
            quote_data = {
                'code': code,
                'current_price': current_price,
                'change_percent': change_percent,
                'volume': int(cls.extract_field_value(quote_row, 'volume', 'quote', 0)),
                'turnover': float(cls.extract_field_value(quote_row, 'turnover', 'quote', 0)),
                'high_price': float(cls.extract_field_value(quote_row, 'high_price', 'quote', 0)),
                'low_price': float(cls.extract_field_value(quote_row, 'low_price', 'quote', 0)),
                'open_price': float(cls.extract_field_value(quote_row, 'open_price', 'quote', 0))
            }
            
            # 补充股票基本信息，优先使用富途API数据中的名称
            if stock_info and len(stock_info) >= 5:
                quote_data.update({
                    'id': stock_info[0],
                    'name': stock_name or stock_info[2] or '',  # 优先使用富途API的股票名称
                    'market': stock_info[3] or '',
                    'plate_name': stock_info[4] or ''
                })
            else:
                # 没有stock_info时，也要设置name字段
                quote_data['name'] = stock_name or ''
            
            return quote_data
            
        except Exception as e:
            logging.debug(f"提取报价数据失败: {e}")
            return None
    
    @classmethod
    def extract_kline_data(cls, kline_row: Union[Dict, Any]) -> Optional[Dict[str, Any]]:
        """
        从K线数据行中提取K线信息
        
        Args:
            kline_row: K线数据行
            
        Returns:
            提取的K线信息字典，失败返回None
        """
        try:
            time_key = cls.extract_field_value(kline_row, 'time', 'kline')
            if not time_key:
                return None
            
            return {
                'date': time_key,
                'open': float(cls.extract_field_value(kline_row, 'open', 'kline', 0)),
                'high': float(cls.extract_field_value(kline_row, 'high', 'kline', 0)),
                'low': float(cls.extract_field_value(kline_row, 'low', 'kline', 0)),
                'close': float(cls.extract_field_value(kline_row, 'close', 'kline', 0)),
                'volume': int(cls.extract_field_value(kline_row, 'volume', 'kline', 0))
            }
            
        except Exception as e:
            logging.debug(f"提取K线数据失败: {e}")
            return None
    
    @classmethod
    def _infer_market_from_code(cls, stock_code: str) -> str:
        """根据股票代码推断市场"""
        try:
            if stock_code.startswith(('US.', 'us.')):
                return 'US'
            elif stock_code.startswith(('HK.', 'hk.')):
                return 'HK'
            elif len(stock_code) == 5 and stock_code.isdigit():
                return 'HK'  # 港股通常是5位数字
            elif stock_code.count('.') > 0:
                return 'US'  # 美股通常包含点号
            else:
                return 'HK'  # 默认港股
        except Exception:
            return 'HK'
    
    @classmethod
    def batch_extract_data(cls, data_rows: List[Union[Dict, Any]], 
                          data_type: str, market_code: str = None) -> List[Dict[str, Any]]:
        """
        批量提取数据
        
        Args:
            data_rows: 数据行列表
            data_type: 数据类型 ('plate', 'stock')
            market_code: 市场代码
            
        Returns:
            提取的数据信息列表
        """
        results = []
        
        try:
            for row in data_rows:
                if data_type == 'plate':
                    info = cls.extract_plate_info(row, market_code)
                elif data_type == 'stock':
                    info = cls.extract_stock_info(row, market_code)
                else:
                    continue
                
                if info:
                    results.append(info)
            
        except Exception as e:
            logging.error(f"批量提取{data_type}数据失败: {e}")
        
        return results
    
    @classmethod
    def add_custom_mapping(cls, data_type: str, field_name: str, field_aliases: List[str]):
        """
        添加自定义字段映射
        
        Args:
            data_type: 数据类型
            field_name: 字段名
            field_aliases: 字段别名列表
        """
        try:
            if data_type not in cls.FIELD_MAPPINGS:
                cls.FIELD_MAPPINGS[data_type] = {}
            
            cls.FIELD_MAPPINGS[data_type][field_name] = field_aliases
            logging.info(f"添加自定义字段映射: {data_type}.{field_name} -> {field_aliases}")
            
        except Exception as e:
            logging.error(f"添加自定义字段映射失败: {e}")
    
    @classmethod
    def get_available_mappings(cls) -> Dict[str, Dict[str, List[str]]]:
        """获取所有可用的字段映射"""
        return cls.FIELD_MAPPINGS.copy()
    
    @classmethod
    def validate_data_completeness(cls, data_row: Union[Dict, Any], 
                                  required_fields: List[str], data_type: str = 'stock') -> Dict[str, Any]:
        """
        验证数据完整性
        
        Args:
            data_row: 数据行
            required_fields: 必填字段列表
            data_type: 数据类型
            
        Returns:
            验证结果字典
        """
        result = {
            'is_complete': True,
            'missing_fields': [],
            'available_fields': [],
            'extracted_values': {}
        }
        
        try:
            for field in required_fields:
                value = cls.extract_field_value(data_row, field, data_type)
                if value is None or value == '':
                    result['missing_fields'].append(field)
                    result['is_complete'] = False
                else:
                    result['available_fields'].append(field)
                    result['extracted_values'][field] = value
            
        except Exception as e:
            logging.error(f"验证数据完整性失败: {e}")
            result['is_complete'] = False
        
        return result
