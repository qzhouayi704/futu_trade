#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时报价服务包装器 - 负责获取和解析实时报价数据
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from ...api.futu_client import FutuClient
from ...api.quote_service import QuoteService
from ...api.market_types import ReturnCode


class RealtimeQuoteServiceWrapper:
    """实时报价服务包装器"""

    def __init__(self, futu_client: FutuClient, quote_service: QuoteService, config=None):
        self.futu_client = futu_client
        self.quote_service = quote_service
        self.config = config

    def get_realtime_quotes(self, stock_codes: List[str],
                           subscribed_stocks: set = None) -> Dict[str, Any]:
        """获取实时行情数据

        Args:
            stock_codes: 股票代码列表（如果为None，使用subscribed_stocks）
            subscribed_stocks: 已订阅股票集合（用于fallback）
        """
        result = {
            'success': False,
            'message': '',
            'quotes': [],
            'filtered_low_price': [],  # 被过滤的低价股
            'errors': []
        }

        try:
            if not self.futu_client.is_available():
                result['message'] = '富途API不可用'
                result['errors'].append('富途API不可用')
                return result

            # 如果没有指定股票代码，使用已订阅的股票
            if not stock_codes and subscribed_stocks:
                # 根据配置限制获取报价的股票数量
                max_quote_stocks = None
                if self.config:
                    max_quote_stocks = getattr(self.config, 'max_stocks_monitor', 100)

                subscribed_list = list(subscribed_stocks)
                if max_quote_stocks and len(subscribed_list) > max_quote_stocks:
                    stock_codes = subscribed_list[:max_quote_stocks]
                    logging.info(f"根据配置限制，从 {len(subscribed_list)} 只已订阅股票中取前 {max_quote_stocks} 只获取报价")
                else:
                    stock_codes = subscribed_list
                    logging.debug(f"获取所有 {len(subscribed_list)} 只已订阅股票的报价")

            if not stock_codes:
                result['message'] = '没有可获取行情的股票'
                return result

            # 获取最低价格配置
            min_price_config = {}
            if self.config:
                min_price_config = getattr(self.config, 'min_stock_price', {})

            # 获取实时报价
            ret, quote_data = self.quote_service.get_stock_quote(stock_codes)

            if ReturnCode.is_ok(ret) and quote_data is not None and not quote_data.empty:
                quotes = []
                filtered_low_price = []

                for _, row in quote_data.iterrows():
                    try:
                        quote = self._parse_quote_data(row)
                        if quote:
                            # 检查是否为低价股
                            if self._is_low_price_stock(quote, min_price_config):
                                filtered_low_price.append({
                                    'code': quote['code'],
                                    'name': quote['name'],
                                    'price': quote['last_price'],
                                    'market': 'HK' if quote['code'].startswith('HK.') else 'US'
                                })
                                logging.debug(f"过滤低价股: {quote['code']} {quote['name']} 价格={quote['last_price']}")
                            else:
                                quotes.append(quote)
                    except Exception as e:
                        logging.warning(f"解析行情数据失败 {row.get('code', 'unknown')}: {e}")
                        continue

                # 如果有低价股被过滤，记录日志
                if filtered_low_price:
                    logging.info(f"过滤了 {len(filtered_low_price)} 只低价股")

                result.update({
                    'success': True,
                    'message': f'获取到{len(quotes)}只股票的实时行情' + (f'，过滤{len(filtered_low_price)}只低价股' if filtered_low_price else ''),
                    'quotes': quotes,
                    'filtered_low_price': filtered_low_price
                })

            else:
                result['message'] = f'获取实时行情失败: ret={ret}, 请求{len(stock_codes)}只'
                result['errors'].append(
                    f'API返回错误: ret={ret}, 股票={stock_codes[:10]}, data={str(quote_data)[:200]}'
                )

        except Exception as e:
            logging.error(f"获取实时行情失败: {e}")
            result.update({
                'success': False,
                'message': f'获取实时行情异常: {str(e)}'
            })
            result['errors'].append(str(e))

        return result

    def _is_low_price_stock(self, quote: Dict[str, Any], min_price_config: Dict[str, float]) -> bool:
        """检查是否为低价股

        Args:
            quote: 报价数据
            min_price_config: 最低价格配置 {'HK': 1.0, 'US': 5.0}

        Returns:
            True 如果是低价股（应被过滤）
        """
        if not min_price_config:
            return False

        code = quote.get('code', '')
        price = quote.get('last_price', 0)

        # 判断市场
        if code.startswith('HK.'):
            market = 'HK'
        elif code.startswith('US.'):
            market = 'US'
        else:
            return False

        # 获取该市场的最低价格要求
        min_price = min_price_config.get(market, 0)

        # 如果设置了最低价格且当前价格低于阈值，则为低价股
        if min_price > 0 and price > 0 and price < min_price:
            return True

        return False

    def _parse_quote_data(self, row) -> Optional[Dict[str, Any]]:
        """解析行情数据"""
        try:
            code = row.get('code', '')
            if not code:
                return None

            last_price = float(row.get('last_price', 0))
            prev_close = float(row.get('prev_close_price', 0))
            change_percent = ((last_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
            change_amount = last_price - prev_close

            return {
                'code': code,
                'name': str(row.get('name', '')),
                'last_price': last_price,
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
                'update_time': datetime.now().strftime('%H:%M:%S')
            }

        except Exception as e:
            logging.debug(f"解析行情数据失败: {e}")
            return None
