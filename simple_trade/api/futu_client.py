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

import time
import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from simple_trade.utils.api_protection import futu_api_protected
from simple_trade.utils.rate_limiter import get_global_rate_limiter, RateLimiter
from simple_trade.utils.metrics import get_metrics


class AdaptiveTimeoutManager:
    """P2-3: 自适应超时管理器

    - 报价类: max(5s, P95延迟 × 3)，上限 30s
    - 交易类: 固定 30s
    - 历史K线: 固定 60s
    - 每小时滚动重算
    """

    def __init__(self):
        self._latencies: deque = deque(maxlen=500)  # 最近 500 次调用
        self._lock = threading.Lock()
        self._cached_timeout = 15.0  # 默认
        self._last_recalc = 0.0
        self._recalc_interval = 3600  # 每小时重算

    def record(self, duration_s: float):
        """记录一次 API 调用耗时"""
        with self._lock:
            self._latencies.append(duration_s)

    def get_quote_timeout(self) -> float:
        """获取报价类超时（动态）"""
        now = time.monotonic()
        if now - self._last_recalc > self._recalc_interval:
            self._recalculate()
            self._last_recalc = now
        return self._cached_timeout

    @staticmethod
    def get_trade_timeout() -> float:
        return 30.0

    @staticmethod
    def get_kline_timeout() -> float:
        return 60.0

    def _recalculate(self):
        """重算 P95 超时"""
        with self._lock:
            if len(self._latencies) < 10:
                self._cached_timeout = 15.0
                return
            sorted_lats = sorted(self._latencies)
            p95_idx = int(len(sorted_lats) * 0.95)
            p95 = sorted_lats[min(p95_idx, len(sorted_lats) - 1)]
            self._cached_timeout = max(5.0, min(p95 * 3, 30.0))

# 富途API
try:
    from futu import (
        OpenQuoteContext, Market, KLType, AuType, KL_FIELD,
        RET_OK, RET_ERROR, PeriodType, TradeDateMarket
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
    TradeDateMarket = None


class FutuClient:
    """富途API客户端 - 连接管理"""

    # 专用线程池：防止 Futu 同步 API 调用占满默认 asyncio executor
    _futu_executor = ThreadPoolExecutor(
        max_workers=4,
        thread_name_prefix="futu-api",
    )

    # P1-1: 独立 API 调用日志
    _api_logger = None

    @classmethod
    def _get_api_logger(cls):
        """懒初始化 API 调用日志器"""
        if cls._api_logger is None:
            import os
            from simple_trade.utils.logger import create_dedicated_logger
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
            cls._api_logger = create_dedicated_logger(
                'futu_api_trace', os.path.join(log_dir, 'futu_api.log')
            )
        return cls._api_logger

    def __init__(self, host: str = "127.0.0.1", port: int = 11111):
        self.host = host
        self.port = port
        self.client = None  # OpenQuoteContext instance (主连接：报价/K线/板块)
        self.is_connected = False
        self._ticker_failed_stocks = set()  # 缓存订阅失败的股票，避免重复警告
        self._reconnect_lock = threading.Lock()  # 防止并发重连
        self._last_reconnect_time = 0.0  # 最后一次重连时间
        self._reconnect_cooldown = 10.0  # 重连冷却时间（秒）

        # P2-3: 自适应超时管理器
        self.timeout_manager = AdaptiveTimeoutManager()

        # 限流器：通用行情接口 60次/30秒（快照、报价共享）
        self._quote_limiter = get_global_rate_limiter(max_requests=60, time_window=30)
        # K线独立限流器 60次/30秒（不再与报价共享，避免K线下载阻塞报价获取）
        self._kline_limiter = RateLimiter(max_requests=60, time_window=30)
        # 板块接口专用限流器 10次/30秒
        self._plate_limiter = RateLimiter(max_requests=10, time_window=30)
        # 资金流向专用限流器 28次/30秒（API限制30次/30秒，预留安全余量）
        self._capital_flow_limiter = RateLimiter(max_requests=28, time_window=30)
        # 全局 QPS 限流：所有 OpenD 请求共享 5 req/s 上限
        self._global_qps_interval = 0.2  # 200ms 最小间隔
        self._last_request_time = 0.0
        self._qps_lock = threading.Lock()

        # Ticker 推送处理器
        self._ticker_push_handler = None

    @property
    def executor(self) -> ThreadPoolExecutor:
        """获取专用线程池（供 run_in_executor 使用）"""
        return self._futu_executor

    def _throttle(self):
        """全局 QPS 限流：确保每次 OpenD 请求至少间隔 200ms"""
        with self._qps_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._global_qps_interval:
                time.sleep(self._global_qps_interval - elapsed)
            self._last_request_time = time.monotonic()
        # P2-3: 记录调用间隔用于自适应超时计算
        self.timeout_manager.record(time.monotonic() - self._last_request_time + 0.2)
        # metrics 埋点
        get_metrics().counter("api.futu.calls").inc()
        get_metrics().rate("api.futu.qps", window_seconds=60).inc()

    def _log_api_call(self, api_name: str, duration_ms: float,
                      success: bool, retry: int = 0, detail: str = ""):
        """P1-1: 记录 API 调用到独立日志文件"""
        import json
        entry = {
            "flow": "futu_api", "api": api_name,
            "duration_ms": round(duration_ms, 1), "retry": retry,
            "success": success, "detail": detail,
        }
        self._get_api_logger().info(json.dumps(entry, ensure_ascii=False))

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

                # 注册 Ticker 推送处理器
                self._register_ticker_handler()

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
        # 关闭主连接
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

    @staticmethod
    def _is_connection_error(data) -> bool:
        """判断返回数据是否为连接断开错误"""
        if data is None:
            return False
        error_str = str(data).lower()
        return any(kw in error_str for kw in (
            'connection closed', 'connection reset', 'broken pipe',
            'not connected', 'timed out', 'connection refused',
        ))

    def _reconnect_opend(self) -> bool:
        """纯连接恢复（不触发回调）

        带冷却时间，防止频繁重连。
        线程安全：使用 Lock 防止并发重连。
        回调通知统一由 GlobalConnectionManager 管理。

        Returns:
            是否重连成功
        """
        now = time.monotonic()
        if now - self._last_reconnect_time < self._reconnect_cooldown:
            logging.debug("重连冷却中，跳过")
            return self.is_connected

        if not self._reconnect_lock.acquire(blocking=False):
            logging.debug("其他线程正在重连，跳过")
            return self.is_connected

        try:
            self._last_reconnect_time = now
            logging.warning("检测到连接断开，尝试自动重连 OpenD...")

            # 先关闭旧连接
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass
            self._cleanup()
            # 重新建立连接
            success = self.connect()
            if success:
                logging.info("自动重连 OpenD 成功")
                # 清空 ticker 失败缓存，让重连后重试
                self._ticker_failed_stocks.clear()
                # 注意：不触发回调，回调通知统一由 GlobalConnectionManager 管理
            else:
                logging.error("自动重连 OpenD 失败")
            return success

        except Exception as e:
            logging.error(f"自动重连异常: {e}")
            return False
        finally:
            self._reconnect_lock.release()

    def is_available(self) -> bool:
        """检查富途API是否可用"""
        return FUTU_AVAILABLE and self.client is not None and self.is_connected

    def _register_ticker_handler(self):
        """注册 Ticker 推送回调处理器"""
        try:
            from .ticker_push_handler import TickerPushHandler, FUTU_AVAILABLE as TH_AVAIL
            if not TH_AVAIL:
                return
            self._ticker_push_handler = TickerPushHandler()
            self.client.set_handler(self._ticker_push_handler)
            logging.info("[TickerPush] 推送处理器已注册到 OpenQuoteContext")
        except Exception as e:
            logging.warning(f"[TickerPush] 注册推送处理器失败: {e}")

    def set_container_for_push(self, container):
        """注入容器到推送处理器（延迟注入，在container构建完成后调用）"""
        if self._ticker_push_handler:
            self._ticker_push_handler.set_container(container)
            logging.info("[TickerPush] 容器已注入推送处理器")

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
        """获取板块列表（10次/30秒）"""
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        self._throttle()  # 全局QPS限流
        self._plate_limiter.wait_if_needed()
        return self.client.get_plate_list(market, plate_type)

    @futu_api_protected(max_retries=2, error_return_value=(RET_ERROR, "API调用失败"))
    def get_plate_stock(self, plate_code: str):
        """获取板块股票（10次/30秒）"""
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        self._throttle()  # 全局QPS限流
        self._plate_limiter.wait_if_needed()
        return self.client.get_plate_stock(plate_code)

    def request_trading_days(self, market=None, start=None, end=None, code=None):
        """获取交易日历（含节假日）

        低频接口（约每自然日一次，由 TradingCalendar 缓存复用），故单次调用、
        不挂重试装饰器，避免 OpenD 抖动时多次退避重试阻塞调用方；失败交由
        调用方 fail-open 兜底。

        Args:
            market: 市场枚举 TradeDateMarket.HK / TradeDateMarket.US（即字符串 'HK'/'US'）
            start/end: 日期字符串 'YYYY-MM-DD'，留空按 FUTU 默认 365 天窗口

        Returns:
            (ret, data)。成功时 data 为 [{'time': 'YYYY-MM-DD', 'trade_date_type': ...}, ...]
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        if market is None:
            market = TradeDateMarket.HK
        self._throttle()  # 全局QPS限流
        self._quote_limiter.wait_if_needed()
        return self.client.request_trading_days(
            market=market, start=start, end=end, code=code
        )

    # ========== K线相关方法 ==========

    def request_history_kline(self, code: str, start: str, end: str,
                              ktype=None, autype=None, fields=None,
                              max_count: int = 1000, timeout: int = None):
        """获取历史K线数据

        Args:
            code: 股票代码
            start: 开始日期
            end: 结束日期
            ktype: K线类型
            autype: 复权类型
            fields: 字段列表
            max_count: 最大返回条数
            timeout: 超时时间（秒），None 时使用自适应超时
        """
        if timeout is None:
            timeout = int(self.timeout_manager.get_kline_timeout())
        if not self.is_available():
            return RET_ERROR, None, None

        try:
            self._throttle()  # 全局QPS限流
            self._kline_limiter.wait_if_needed()  # K线独立限流（不再与报价共享）
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
        """获取K线额度（60次/30秒）"""
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        self._throttle()  # 全局QPS限流
        self._kline_limiter.wait_if_needed()  # K线独立限流
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
            self._throttle()  # 全局QPS限流
            self._capital_flow_limiter.wait_if_needed()
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
            self._throttle()  # 全局QPS限流
            self._capital_flow_limiter.wait_if_needed()
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
            self._throttle()
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
                    logging.warning(
                        f"获取逐笔成交失败: {stock_code}, "
                        f"错误: {data}"
                    )
                    self._ticker_failed_stocks.add(stock_code)
                else:
                    # 后续失败降级为 DEBUG
                    logging.debug(f"获取逐笔成交失败(已知): {stock_code}, {data}")
                return ret, None

        except Exception as e:
            logging.error(f"获取逐笔成交异常: {stock_code}, {e}")
            return RET_ERROR, str(e)

    def get_rt_data(self, stock_code: str):
        """获取分时数据 (Intraday Data)
        
        Args:
            stock_code: 股票代码，如 'HK.00700'
            
        Returns:
            (ret_code, data) - 成功返回(RET_OK, DataFrame)，失败返回(RET_ERROR, error_msg)
            DataFrame包含字段：
            - time: 时间
            - cur_price: 当前价格
            - avg_price: 均价 (VWAP)
            - volume: 成交量
            - turnover: 成交额
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"

        try:
            self._throttle()
            ret, data = self.client.get_rt_data(stock_code)

            if ret == RET_OK:
                logging.debug(f"获取分时数据成功: {stock_code}, 共{len(data)}条")
                return ret, data
            else:
                logging.debug(f"获取分时数据失败: {stock_code}, 错误: {data}")
                return ret, None

        except Exception as e:
            logging.error(f"获取分时数据异常: {stock_code}, {e}")
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
            self._throttle()  # 全局QPS限流
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
            self._throttle()
            ret, data = self.client.get_order_book(stock_code)

            if ret == RET_OK:
                logging.debug(f"获取摆盘数据成功: {stock_code}")
                return ret, data
            else:
                logging.warning(
                    f"获取摆盘数据失败: {stock_code}, "
                    f"错误: {data}"
                )
                return ret, data

        except Exception as e:
            logging.error(f"获取摆盘数据异常: {stock_code}, {e}")
            return RET_ERROR, str(e)

    # ========== 集中入口：快照和报价（60次/30秒） ==========

    def get_market_snapshot(self, codes):
        """获取市场快照（60次/30秒，带自动重连）

        所有调用方应通过此方法获取快照数据，不要直接调用 self.client.get_market_snapshot。

        Args:
            codes: 股票代码列表

        Returns:
            (ret_code, data)
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        try:
            if not codes:
                return RET_ERROR, "股票代码列表不能为空"
            self._throttle()  # 全局QPS限流
            self._quote_limiter.wait_if_needed()
            ret, data = self.client.get_market_snapshot(codes)

            # 检测连接断开，自动重连后重试一次
            if ret != RET_OK and self._is_connection_error(data):
                if self._reconnect_opend():
                    self._throttle()  # 重连后也需要限流
                    self._quote_limiter.wait_if_needed()
                    ret, data = self.client.get_market_snapshot(codes)

            return ret, data
        except Exception as e:
            logging.error(f"获取市场快照异常: {e}")
            return RET_ERROR, str(e)

    def get_stock_quote(self, stock_codes):
        """获取股票报价（60次/30秒，带自动重连）

        所有调用方应通过此方法获取报价，不要直接调用 self.client.get_stock_quote。

        Args:
            stock_codes: 股票代码列表

        Returns:
            (ret_code, data)
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        try:
            if not stock_codes:
                return RET_ERROR, "股票代码列表不能为空"
            self._quote_limiter.wait_if_needed()
            self._throttle()
            ret, data = self.client.get_stock_quote(stock_codes)

            # 检测连接断开，自动重连后重试一次
            if ret != RET_OK and self._is_connection_error(data):
                if self._reconnect_opend():
                    self._quote_limiter.wait_if_needed()
                    self._throttle()
                    ret, data = self.client.get_stock_quote(stock_codes)

            return ret, data
        except Exception as e:
            logging.error(f"获取股票报价异常: {e}")
            return RET_ERROR, str(e)

    # ========== 受保护的订阅/反订阅入口 ==========

    def subscribe_stocks(self, stock_codes: list, sub_types: list):
        """受保护的订阅入口（带限流+自动重连）

        所有订阅操作应通过此方法，不要直接调用 self.client.subscribe()。
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        try:
            self._throttle()
            ret, err = self.client.subscribe(stock_codes, sub_types)
            if ret != RET_OK and self._is_connection_error(err):
                if self._reconnect_opend():
                    self._throttle()
                    ret, err = self.client.subscribe(stock_codes, sub_types)
            return ret, err
        except Exception as e:
            logging.error(f"订阅异常: {stock_codes}, {e}")
            return RET_ERROR, str(e)

    def unsubscribe_stocks(self, stock_codes: list, sub_types: list):
        """受保护的反订阅入口（带限流+自动重连）

        所有反订阅操作应通过此方法，不要直接调用 self.client.unsubscribe()。
        """
        if not self.is_available():
            return RET_ERROR, "富途API不可用"
        try:
            self._throttle()
            ret, err = self.client.unsubscribe(stock_codes, sub_types)
            if ret != RET_OK and self._is_connection_error(err):
                if self._reconnect_opend():
                    self._throttle()
                    ret, err = self.client.unsubscribe(stock_codes, sub_types)
            return ret, err
        except Exception as e:
            logging.error(f"反订阅异常: {stock_codes}, {e}")
            return RET_ERROR, str(e)

    # ========== 重连回调机制 ==========

    def register_reconnect_callback(self, callback):
        """注册重连成功后的回调函数"""
        if not hasattr(self, '_on_reconnect_callbacks'):
            self._on_reconnect_callbacks = []
        self._on_reconnect_callbacks.append(callback)
