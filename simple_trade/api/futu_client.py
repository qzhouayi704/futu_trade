#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
富途API客户端管理

职责：
1. 管理与富途OpenD的连接
2. 提供板块和K线数据获取接口
3. 暴露底层client供其他服务使用

订阅管理和报价获取已拆分到：
- subscription_manager.py: 订阅状态管理
- quote_service.py: 报价获取服务
"""

import logging
from simple_trade.utils.api_protection import futu_api_protected

# 富途API
try:
    from futu import (
        OpenQuoteContext, Market, KLType, AuType, KL_FIELD,
        RET_OK, RET_ERROR, PeriodType
    )
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    OpenQuoteContext = None
    Market = None
    KLType = None
    AuType = None
    KL_FIELD = None
    RET_OK = None
    RET_ERROR = None
    PeriodType = None


class FutuClient:
    """富途API客户端 - 连接管理"""

    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self.host = host
        self.port = port
        self.client = None  # OpenQuoteContext instance
        self.is_connected = False
        self._ticker_failed_stocks = set()  # 缓存订阅失败的股票，避免重复警告

    def connect(self) -> bool:
        """连接富途API"""
        if not FUTU_AVAILABLE:
            logging.error("富途API不可用，请安装futu-api包: pip install futu-api")
            return False

        try:
            logging.info(f"正在连接富途API - 地址: {self.host}:{self.port}")

            self.client = OpenQuoteContext(
                host=self.host,
                port=self.port,
                is_encrypt=False
            )

            # 测试连接
            logging.info("测试富途API连接...")
            ret, data = self.client.get_history_kl_quota(get_detail=True)

            if ret == RET_OK:
                self.is_connected = True
                logging.info("富途API连接成功")
                logging.debug(f"历史K线额度信息: {data}")

                # 测试板块列表
                test_ret, test_data = self.client.get_plate_list(Market.HK, 'ALL')
                if test_ret == RET_OK:
                    count = len(test_data) if test_data is not None else 0
                    logging.debug(f"港股板块列表测试成功，获取到 {count} 个板块")
                else:
                    logging.warning(f"港股板块列表测试失败: {test_data}")

                return True
            else:
                logging.error(f"富途API连接测试失败: ret={ret}, data={data}")
                logging.error("请检查: 1)富途客户端是否已登录 2)OpenD是否已启动")
                self._cleanup()
                return False

        except ConnectionRefusedError:
            logging.error(f"连接被拒绝 - 无法连接到 {self.host}:{self.port}")
            logging.error("请检查: 1)富途客户端是否已启动 2)OpenD服务是否运行")
            self._cleanup()
            return False
        except Exception as e:
            logging.error(f"富途API初始化异常: {type(e).__name__}: {e}")
            self._cleanup()
            return False

    def disconnect(self):
        """断开连接"""
        if self.client:
            try:
                self.client.close()
                logging.info("富途API连接已关闭")
            except Exception as e:
                logging.error(f"关闭富途API连接失败: {e}")
            finally:
                self._cleanup()

    def _cleanup(self):
        """清理连接状态"""
        self.client = None
        self.is_connected = False

    def is_available(self) -> bool:
        """检查富途API是否可用"""
        return FUTU_AVAILABLE and self.client is not None and self.is_connected

    def get_connection_status(self) -> dict:
        """获取连接状态信息"""
        return {
            'is_connected': self.is_connected,
            'is_available': self.is_available(),
            'futu_api_available': FUTU_AVAILABLE,
            'host': self.host,
            'port': self.port
        }

    # ========== 板块相关方法 ==========

    @futu_api_protected(max_retries=2, error_return_value=(RET_ERROR, "API调用失败"))
    def get_plate_list(self, market, plate_type):
        """获取板块列表"""
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        return self.client.get_plate_list(market, plate_type)

    @futu_api_protected(max_retries=2, error_return_value=(RET_ERROR, "API调用失败"))
    def get_plate_stock(self, plate_code: str):
        """获取板块股票"""
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        return self.client.get_plate_stock(plate_code)

    # ========== K线相关方法 ==========

    def request_history_kline(self, code: str, start: str, end: str,
                              ktype=None, autype=None, fields=None,
                              max_count: int = 1000, timeout: int = 30):
        """获取历史K线数据

        Args:
            code: 股票代码
            start: 开始日期
            end: 结束日期
            ktype: K线类型
            autype: 复权类型
            fields: 字段列表
            max_count: 最大返回条数
            timeout: 超时时间（秒），默认30秒
        """
        if not self.is_available():
            return RET_ERROR, None, None

        try:
            if ktype is None:
                ktype = KLType.K_DAY
            if autype is None:
                autype = AuType.QFQ
            if fields is None:
                fields = [KL_FIELD.ALL]

            import threading

            result = [RET_ERROR, None, None]
            exception_holder = [None]

            def _do_request():
                try:
                    result[0], result[1], result[2] = self.client.request_history_kline(
                        code=code,
                        start=start,
                        end=end,
                        ktype=ktype,
                        autype=autype,
                        fields=fields,
                        max_count=max_count
                    )
                except Exception as e:
                    exception_holder[0] = e

            logging.debug(f"开始请求K线: {code}, 超时={timeout}秒")
            thread = threading.Thread(target=_do_request, daemon=True)
            thread.start()
            thread.join(timeout=timeout)

            if thread.is_alive():
                logging.warning(f"获取K线数据超时({timeout}秒): {code}，跳过该股票")
                # 线程仍在运行但我们不再等待，daemon线程会在主线程退出时被清理
                return RET_ERROR, f"请求超时({timeout}秒)", None

            if exception_holder[0]:
                raise exception_holder[0]

            return result[0], result[1], result[2]
        except Exception as e:
            logging.error(f"获取历史K线数据失败: {e}")
            return RET_ERROR, None, None

    @futu_api_protected(max_retries=2, error_return_value=(RET_ERROR, "API调用失败"))
    def get_history_kl_quota(self, get_detail: bool = False):
        """获取K线额度"""
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        return self.client.get_history_kl_quota(get_detail=get_detail)

    def get_kline_quota_detail(self) -> dict:
        """获取K线额度详细信息"""
        result = {
            'success': False,
            'used_quota': 0,
            'remain_quota': 0,
            'kline_stocks': set(),
            'detail_list': [],
            'message': ''
        }

        if not self.is_available():
            result['message'] = '富途API不可用'
            return result

        try:
            ret, data = self.client.get_history_kl_quota(get_detail=True)
            logging.debug(f"K线额度API返回: ret={ret}, type={type(data)}")

            if ret == RET_OK and data is not None:
                if isinstance(data, tuple) and len(data) >= 3:
                    result['used_quota'] = int(data[0]) if data[0] else 0
                    result['remain_quota'] = int(data[1]) if data[1] else 0

                    detail_list = data[2] if data[2] else []
                    kline_stocks = set()
                    result['detail_list'] = []

                    if isinstance(detail_list, list):
                        for record in detail_list:
                            if isinstance(record, dict):
                                code = record.get('code', '')
                                if code:
                                    kline_stocks.add(code)
                                    result['detail_list'].append({
                                        'code': code,
                                        'name': record.get('name', ''),
                                        'request_time': record.get('request_time', '')
                                    })

                    result['kline_stocks'] = kline_stocks
                    result['success'] = True
                    result['message'] = (
                        f'已用{result["used_quota"]}, '
                        f'剩余{result["remain_quota"]}, '
                        f'已订阅{len(kline_stocks)}只'
                    )
                    logging.debug(f"K线额度: {result['message']}")
                else:
                    result['message'] = f'数据格式异常: {type(data)}'
                    logging.error(result['message'])
            else:
                result['message'] = f'获取失败: ret={ret}'
                logging.error(result['message'])

        except Exception as e:
            result['message'] = f"获取K线额度异常: {e}"
            logging.error(result['message'])

        return result

    # ========== 资金流向相关方法 ==========

    def get_capital_flow(self, stock_code: str, period_type='INTRADAY',
                         start: str = None, end: str = None):
        """获取资金流向数据

        Args:
            stock_code: 股票代码，如 'HK.00700'
            period_type: 周期类型，'INTRADAY'(日内) 或 'PERIOD'(按天)
            start: 开始日期，格式 'YYYY-MM-DD'（仅 PERIOD 模式有效）
            end: 结束日期，格式 'YYYY-MM-DD'（仅 PERIOD 模式有效）

        Returns:
            (ret_code, data) - 成功返回(RET_OK, DataFrame)，失败返回(RET_ERROR, error_msg)
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"

        try:
            period = PeriodType.INTRADAY if period_type == 'INTRADAY' else PeriodType.DAY
            kwargs = {'period_type': period}
            if start:
                kwargs['start'] = start
            if end:
                kwargs['end'] = end

            ret, data = self.client.get_capital_flow(stock_code, **kwargs)

            if ret == RET_OK:
                logging.debug(f"获取资金流向成功: {stock_code}")
                return ret, data
            else:
                logging.warning(f"获取资金流向失败: {stock_code}, {data}")
                return ret, data

        except AttributeError:
            logging.warning("当前富途API版本不支持get_capital_flow接口")
            return RET_ERROR, "API不支持资金流向功能"
        except Exception as e:
            logging.error(f"获取资金流向异常: {stock_code}, {e}")
            return RET_ERROR, str(e)

    def get_capital_distribution(self, stock_code: str):
        """获取资金分布数据（流入/流出分开）

        与 get_capital_flow 不同，此接口返回各级别的流入和流出分开数据。

        Args:
            stock_code: 股票代码，如 'HK.00700'

        Returns:
            (ret_code, data) - 成功返回(RET_OK, DataFrame)，失败返回(RET_ERROR, error_msg)
            DataFrame 字段：
            - capital_in_super / capital_out_super: 超大单流入/流出
            - capital_in_big / capital_out_big: 大单流入/流出
            - capital_in_mid / capital_out_mid: 中单流入/流出
            - capital_in_small / capital_out_small: 小单流入/流出
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"

        try:
            ret, data = self.client.get_capital_distribution(stock_code)

            if ret == RET_OK:
                logging.debug(f"获取资金分布成功: {stock_code}")
                return ret, data
            else:
                logging.warning(f"获取资金分布失败: {stock_code}, {data}")
                return ret, data

        except AttributeError:
            logging.warning("当前富途API版本不支持get_capital_distribution接口")
            return RET_ERROR, "API不支持资金分布功能"
        except Exception as e:
            logging.error(f"获取资金分布异常: {stock_code}, {e}")
            return RET_ERROR, str(e)

    def get_rt_ticker(self, stock_code: str, num: int = 500):
        """获取实时逐笔成交数据

        Args:
            stock_code: 股票代码，如 'HK.00700'
            num: 获取的成交笔数，最多1000笔

        Returns:
            (ret_code, data) - 成功返回(RET_OK, DataFrame)，失败返回(RET_ERROR, error_msg)
            DataFrame包含字段：
            - time: 成交时间
            - price: 成交价
            - volume: 成交量
            - turnover: 成交额
            - ticker_direction: 成交方向（BUY/SELL/NEUTRAL）
            - type: 成交类型
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"

        try:
            ret, data = self.client.get_rt_ticker(stock_code, num=num)

            if ret == RET_OK:
                # 调试：打印 DataFrame 列名和前几行数据（仅首次）
                if stock_code not in getattr(self, '_ticker_debug_logged', set()):
                    if not hasattr(self, '_ticker_debug_logged'):
                        self._ticker_debug_logged = set()
                    logging.info(f"[逐笔成交调试] {stock_code} DataFrame 列名: {list(data.columns)}")
                    if len(data) > 0:
                        logging.info(f"[逐笔成交调试] {stock_code} 前3行数据:\n{data.head(3).to_string()}")
                    self._ticker_debug_logged.add(stock_code)

                logging.debug(f"获取逐笔成交成功: {stock_code}, 共{len(data)}笔")
                return ret, data
            else:
                # 只在首次失败时输出 WARNING，避免重复日志
                if stock_code not in self._ticker_failed_stocks:
                    logging.warning(f"获取逐笔成交失败: {stock_code}, {data}")
                    self._ticker_failed_stocks.add(stock_code)
                else:
                    # 后续失败降级为 DEBUG
                    logging.debug(f"获取逐笔成交失败(已知): {stock_code}, {data}")
                return ret, None

        except Exception as e:
            logging.error(f"获取逐笔成交异常: {stock_code}, {e}")
            return RET_ERROR, str(e)

    def get_broker_queue(self, stock_code: str):
        """获取经纪队列（港股专用）

        Args:
            stock_code: 港股代码，如 'HK.00700'

        Returns:
            (ret_code, bid_frame, ask_frame) - 成功返回(RET_OK, 买盘DataFrame, 卖盘DataFrame)
            DataFrame包含字段：
            - broker_id: 经纪商ID
            - broker_name: 经纪商名称
            - broker_pos: 经纪商档位
            - order_volume: 挂单量
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用", None

        try:
            ret, bid_data, ask_data = self.client.get_broker_queue(stock_code)

            if ret == RET_OK:
                logging.debug(f"获取经纪队列成功: {stock_code}")
                return ret, bid_data, ask_data
            else:
                logging.warning(f"获取经纪队列失败: {stock_code}, {bid_data}")
                return ret, bid_data, ask_data

        except Exception as e:
            logging.error(f"获取经纪队列异常: {stock_code}, {e}")
            return RET_ERROR, str(e), None

    def get_order_book(self, stock_code: str):
        """获取买卖盘摆盘数据（1-10档）

        Args:
            stock_code: 股票代码，如 'HK.00700'

        Returns:
            (ret_code, data) - 成功返回(RET_OK, DataFrame)
            DataFrame包含字段：
            - code: 股票代码
            - Bid1~Bid10: 买盘价格
            - BidVol1~BidVol10: 买盘挂单量
            - Ask1~Ask10: 卖盘价格
            - AskVol1~AskVol10: 卖盘挂单量
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"

        try:
            ret, data = self.client.get_order_book(stock_code)

            if ret == RET_OK:
                logging.debug(f"获取摆盘数据成功: {stock_code}")
                return ret, data
            else:
                logging.warning(f"获取摆盘数据失败: {stock_code}, {data}")
                return ret, data

        except Exception as e:
            logging.error(f"获取摆盘数据异常: {stock_code}, {e}")
            return RET_ERROR, str(e)
