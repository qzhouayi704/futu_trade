#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票数据服务

重构说明：
- K线数据优先从数据库读取（历史数据）
- 只有数据不足时才调用API补充
- 当天报价数据使用实时API获取
"""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from .futu_client import FutuClient
from .market_types import ReturnCode
from ..utils.market_helper import MarketTimeHelper


class StockDataService:
    """股票数据服务"""

    def __init__(self, futu_client: FutuClient, realtime_service=None,
                 db_manager=None, quote_service=None):
        self.futu_client = futu_client
        self.realtime_service = realtime_service
        self.db_manager = db_manager
        self.quote_service = quote_service
    
    def get_real_quotes_from_subscribed(self, stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从已订阅股票获取实时报价 - 接收股票信息字典列表，直接使用富途API数据
        
        在非交易时间或实时报价为空时，会fallback到K线历史数据
        """
        quotes = []
        is_market_trading = MarketTimeHelper.is_any_market_trading()
        
        try:
            if not stocks:
                logging.warning("没有可用的股票数据")
                return quotes
            
            # 提取股票代码
            stock_codes = [stock.get('code', '') for stock in stocks if stock.get('code')]
            
            if not stock_codes:
                logging.warning("没有有效的股票代码需要获取报价")
                return quotes
            
            logging.debug(f"从已订阅股票中获取 {len(stock_codes)} 只股票的报价数据 (市场交易中: {is_market_trading})")

            # 尝试获取实时报价
            if self.quote_service:
                ret, data = self.quote_service.get_stock_quote(stock_codes)
                if ReturnCode.is_ok(ret) and data is not None and not data.empty:
                    logging.debug(f"成功获取 {len(data)} 条实时报价数据")
                    
                    for _, row in data.iterrows():
                        # 查找对应的股票信息
                        stock_info = None
                        for stock in stocks:
                            if stock.get('code') == row['code']:
                                stock_info = stock
                                break
                        
                        if stock_info:
                            try:
                                # 直接使用富途API返回的字段
                                code = row.get('code', '')
                                last_price = float(row.get('last_price', 0))
                                prev_close = float(row.get('prev_close_price', 0))
                                change_percent = ((last_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
                                change_amount = last_price - prev_close
                                
                                # 优先使用富途API的股票名称
                                stock_name = row.get('name', '').strip()
                                if not stock_name or stock_name == code:
                                    # 如果富途API没有名称或返回代码，使用数据库名称
                                    stock_name = stock_info.get('name', '').strip()
                                    if not stock_name:
                                        stock_name = code  # 最后才使用代码作为名称
                                
                                quote = {
                                    'id': stock_info.get('id', 0),
                                    'code': code,
                                    'name': stock_name,
                                    'market': stock_info.get('market', 'Unknown'),
                                    'plate_name': stock_info.get('plate_name', ''),
                                    'last_price': last_price,
                                    'current_price': last_price,  # 保持兼容性
                                    'prev_close': prev_close,
                                    'change_amount': change_amount,
                                    'change_percent': round(change_percent, 2),
                                    'high_price': float(row.get('high_price', 0)),
                                    'low_price': float(row.get('low_price', 0)),
                                    'open_price': float(row.get('open_price', 0)),
                                    'volume': int(row.get('volume', 0)),
                                    'turnover': float(row.get('turnover', 0)),
                                    'turnover_rate': float(row.get('turnover_rate', 0) or 0),  # 换手率
                                    'amplitude': float(row.get('amplitude', 0) or 0),  # 振幅
                                    'update_time': datetime.now().strftime('%H:%M:%S'),
                                    'last_update': datetime.now().isoformat(),
                                    'is_realtime': True  # 标识为实时数据
                                }
                                
                                quotes.append(quote)
                                logging.debug(f"处理报价: {quote['code']} ({quote['name']}) @ {quote['current_price']}")
                                
                            except Exception as e:
                                logging.error(f"处理报价数据失败 {row.get('code', 'unknown')}: {e}")
                else:
                    logging.warning(
                        f"获取实时报价失败: ret={ret}, 请求{len(stock_codes)}只股票, "
                        f"可能需要先订阅股票. 错误: {data}"
                    )
            else:
                logging.warning("富途API客户端不可用")
            
            # 如果实时报价为空或不完整，且不在交易时间，使用K线数据作为fallback
            if len(quotes) < len(stocks):
                # 获取已有报价的股票代码集合
                quoted_codes = {q['code'] for q in quotes}
                missing_stocks = [s for s in stocks if s.get('code') not in quoted_codes]
                
                if missing_stocks:
                    if not is_market_trading:
                        logging.info(f"非交易时间，使用K线数据补充 {len(missing_stocks)} 只股票的报价")
                        fallback_quotes = self._get_fallback_quotes_from_kline(missing_stocks)
                        quotes.extend(fallback_quotes)
                        logging.info(f"K线fallback补充了 {len(fallback_quotes)} 条报价")
                    else:
                        missing_codes = [s.get('code', '?') for s in missing_stocks]
                        logging.warning(
                            f"交易时间内有 {len(missing_stocks)} 只股票未获取到报价: "
                            f"{missing_codes[:15]}{'...' if len(missing_codes) > 15 else ''}"
                        )
                
        except Exception as e:
            logging.error(f"从已订阅股票获取实时报价失败: {e}")
            # 发生异常时，如果非交易时间，尝试使用K线数据
            if not is_market_trading and self.db_manager:
                logging.info("发生异常，尝试使用K线数据作为备用报价")
                quotes = self._get_fallback_quotes_from_kline(stocks)
        
        logging.debug(f"最终获取到 {len(quotes)} 条报价 (实时: {sum(1 for q in quotes if q.get('is_realtime', False))}, K线备用: {sum(1 for q in quotes if not q.get('is_realtime', True))})")
        return quotes
    
    def _get_fallback_quotes_from_kline(self, stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从K线数据获取备用报价（用于非交易时间）
        
        使用最近一个交易日的收盘价作为当前价格
        
        Args:
            stocks: 股票信息列表
            
        Returns:
            构建的报价数据列表
        """
        fallback_quotes = []
        
        if not self.db_manager:
            logging.warning("数据库管理器不可用，无法获取K线备用报价")
            return fallback_quotes
        
        for stock in stocks:
            try:
                code = stock.get('code', '')
                if not code:
                    continue
                
                # 从数据库获取最近的K线数据
                kline_data = self.db_manager.kline_queries.get_stock_kline(code, 2)  # 获取最近2条K线
                
                if not kline_data:
                    logging.debug(f"股票 {code} 无K线数据可用作备用报价")
                    continue
                
                # 使用最近一条K线（通常是最近一个交易日）
                latest_kline = kline_data[0]  # 假设按日期降序排列
                
                # 获取收盘价作为当前价格
                close_price = float(latest_kline.get('close', latest_kline.get('close_price', 0)))
                open_price = float(latest_kline.get('open', latest_kline.get('open_price', 0)))
                high_price = float(latest_kline.get('high', latest_kline.get('high_price', 0)))
                low_price = float(latest_kline.get('low', latest_kline.get('low_price', 0)))
                volume = int(latest_kline.get('volume', 0))
                
                # 如果有前一天的K线，计算涨跌幅
                prev_close = close_price  # 默认使用当天收盘价
                if len(kline_data) >= 2:
                    prev_kline = kline_data[1]
                    prev_close = float(prev_kline.get('close', prev_kline.get('close_price', close_price)))
                
                change_amount = close_price - prev_close
                change_percent = ((close_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
                
                quote = {
                    'id': stock.get('id', 0),
                    'code': code,
                    'name': stock.get('name', code),
                    'market': stock.get('market', 'Unknown'),
                    'plate_name': stock.get('plate_name', ''),
                    'last_price': close_price,
                    'current_price': close_price,  # 保持兼容性
                    'prev_close': prev_close,
                    'change_amount': change_amount,
                    'change_percent': round(change_percent, 2),
                    'high_price': high_price,
                    'low_price': low_price,
                    'open_price': open_price,
                    'volume': volume,
                    'turnover': 0,  # K线数据可能没有成交额
                    'update_time': datetime.now().strftime('%H:%M:%S'),
                    'last_update': datetime.now().isoformat(),
                    'is_realtime': False,  # 标识为非实时数据（K线备用）
                    'data_source': 'kline_fallback',  # 数据来源标识
                    'kline_date': latest_kline.get('date', latest_kline.get('time_key', ''))
                }
                
                fallback_quotes.append(quote)
                logging.debug(f"K线备用报价: {code} 收盘价={close_price}, 日期={quote['kline_date']}")
                
            except Exception as e:
                logging.error(f"获取股票 {stock.get('code', 'unknown')} 的K线备用报价失败: {e}")
                continue
        
        return fallback_quotes
    
    def _parse_quote_from_subscribed(self, row, stock_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """从已订阅股票信息中解析报价数据"""
        try:
            code = row.get('code', '')
            if not code:
                return None
            
            last_price = float(row.get('last_price', 0))
            prev_close = float(row.get('prev_close_price', 0))
            change_percent = ((last_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
            change_amount = last_price - prev_close
            
            # 智能获取股票名称：优先数据库，其次富途API，最后代码
            stock_name = stock_info.get('name', '').strip()
            if not stock_name or stock_name == code:
                # 如果数据库名称为空或等于代码，尝试富途API
                api_name = row.get('name', '').strip()
                if api_name and api_name != code:
                    stock_name = api_name
                else:
                    # 最后才使用代码作为名称
                    stock_name = code
            
            return {
                'id': stock_info.get('id', 0),
                'code': code,
                'name': stock_name,
                'market': stock_info.get('market', 'Unknown'),
                'plate_name': stock_info.get('plate_name', ''),
                'current_price': last_price,
                'prev_close': prev_close,
                'change_amount': change_amount,
                'change_percent': round(change_percent, 2),
                'high_price': float(row.get('high_price', 0)),
                'low_price': float(row.get('low_price', 0)),
                'open_price': float(row.get('open_price', 0)),
                'volume': int(row.get('volume', 0)),
                'turnover': float(row.get('turnover', 0)),
                'update_time': datetime.now().strftime('%H:%M:%S')
            }
            
        except Exception as e:
            logging.debug(f"解析订阅股票报价数据失败: {e}")
            return None
    
    def get_kline_data(self, stock_code: str, days: int = 12) -> List[Dict[str, Any]]:
        """获取股票的K线数据
        
        从数据库读取K线数据，K线应该通过kline_service提前准备好
        
        Args:
            stock_code: 股票代码
            days: 需要的天数
            
        Returns:
            K线数据列表
        """
        try:
            # 从数据库读取K线数据
            if self.db_manager:
                kline_data = self.db_manager.kline_queries.get_stock_kline(stock_code, days)
                if len(kline_data) >= days:
                    logging.debug(f"获取K线成功: {stock_code}, {len(kline_data)}条")
                    return kline_data
                elif len(kline_data) > 0:
                    logging.debug(f"K线数据不足: {stock_code}, 需要{days}条, 实际{len(kline_data)}条")
                    return kline_data
                else:
                    # 没有数据，记录调试信息
                    logging.debug(f"K线数据缺失: {stock_code}, 将在下次广播时自动下载")
                    return []
            else:
                logging.debug(f"数据库管理器不可用: {stock_code}")
                return []
                
        except Exception as e:
            logging.error(f"获取K线数据异常: {stock_code}, {e}")
            return []
    
    
    def get_stock_basic_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """获取股票基本信息"""
        try:
            if not self.quote_service:
                return None

            ret, data = self.quote_service.get_stock_quote([stock_code])
            if ReturnCode.is_ok(ret) and data is not None and not data.empty:
                row = data.iloc[0]
                return {
                    'code': row.get('code', stock_code),
                    'name': row.get('name', ''),
                    'last_price': float(row.get('last_price', 0)),
                    'prev_close_price': float(row.get('prev_close_price', 0)),
                    'market_value': row.get('market_val', 0)
                }
            else:
                logging.error(f"获取股票基本信息失败: {stock_code}")
                return None
                
        except Exception as e:
            logging.error(f"获取股票基本信息异常: {stock_code}, {e}")
            return None
    
    def batch_get_stock_info(self, stock_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取股票信息"""
        result = {}

        if not self.quote_service or not stock_codes:
            return result

        try:
            # 分批处理，避免API限制
            batch_size = 20
            for i in range(0, len(stock_codes), batch_size):
                batch_codes = stock_codes[i:i + batch_size]

                ret, data = self.quote_service.get_stock_quote(batch_codes)
                if ReturnCode.is_ok(ret) and data is not None and not data.empty:
                    for _, row in data.iterrows():
                        code = row.get('code', '')
                        if code:
                            result[code] = {
                                'code': code,
                                'name': row.get('name', ''),
                                'last_price': float(row.get('last_price', 0)),
                                'prev_close_price': float(row.get('prev_close_price', 0)),
                                'change_percent': float(row.get('change_rate', 0)) * 100,
                                'volume': int(row.get('volume', 0)),
                                'turnover': float(row.get('turnover', 0))
                            }
                
                time.sleep(0.2)  # 避免API频率限制
                
        except Exception as e:
            logging.error(f"批量获取股票信息失败: {e}")
        
        return result
    
    def is_market_open(self, market_code: str = 'HK') -> bool:
        """检查市场是否开市（简化版本）"""
        try:
            # 这里可以通过富途API获取市场状态
            # 暂时使用简单的时间判断
            now = datetime.now()
            hour = now.hour
            minute = now.minute
            weekday = now.weekday()
            
            # 周末不开市
            if weekday >= 5:  # 周六周日
                return False
            
            if market_code == 'HK':
                # 港股交易时间：9:30-12:00, 13:00-16:00
                morning_session = (9, 30) <= (hour, minute) <= (12, 0)
                afternoon_session = (13, 0) <= (hour, minute) <= (16, 0)
                return morning_session or afternoon_session
            elif market_code == 'US':
                # 美股交易时间（简化，不考虑夏令时）：21:30-4:00（北京时间）
                return hour >= 21 or hour <= 4
            else:
                return True  # 其他市场默认开市
                
        except Exception as e:
            logging.error(f"检查市场开市状态失败: {e}")
            return True  # 异常时默认开市
