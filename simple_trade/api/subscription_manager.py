#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订阅管理器模块

作为订阅状态的唯一数据源，统一管理股票订阅状态。
解决之前 futu_client、realtime_service、state_manager 三处状态不同步的问题。

合并自：
- subscription_core.py（核心订阅逻辑和状态管理）
- subscription_optimizer.py（批处理和额度优化，作为内部依赖）
- subscription_validator.py（错误检测和无效股票处理，作为内部依赖）
"""

import logging
import time
from typing import List, Set, Dict, Any, Callable

from .subscription_validator import SubscriptionValidator
from .subscription_optimizer import SubscriptionOptimizer

try:
    from futu import SubType, RET_OK
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    SubType = None
    RET_OK = None


class SubscriptionManager:
    """
    订阅管理器 - 订阅状态的唯一数据源

    职责：
    1. 维护已订阅股票集合（唯一数据源）
    2. 处理批量订阅逻辑
    3. 提供订阅状态查询接口
    4. 支持状态变更回调通知
    """

    def __init__(self, futu_client, db_manager=None, config=None):
        """
        初始化订阅管理器

        Args:
            futu_client: 富途客户端实例（用于调用底层API）
            db_manager: 数据库管理器实例（用于删除无效股票）
            config: 配置对象（用于读取订阅额度配置）
        """
        self._futu_client = futu_client
        self._db_manager = db_manager

        # 按订阅类型分离管理
        self._quote_subscribed: Set[str] = set()  # QUOTE 订阅（报价数据）
        self._ticker_subscribed: Set[str] = set()  # TICKER 订阅（逐笔成交）
        self._orderbook_subscribed: Set[str] = set()  # ORDER_BOOK 订阅（盘口深度）
        self._rt_data_subscribed: Set[str] = set()  # RT_DATA 订阅（分时数据）

        # 向后兼容：_subscribed_stocks 指向 _quote_subscribed
        self._subscribed_stocks = self._quote_subscribed

        # 订阅时间戳：stock_code -> 订阅时间（用于尊重富途1分钟最短订阅限制）
        self._subscribe_times: Dict[str, float] = {}

        # 订阅额度限制（从配置读取）
        if config and hasattr(config, 'subscription_config'):
            sub_cfg = config.subscription_config
            self._total_quota = sub_cfg.get('total_subscription_quota', 300)
            self._max_quote_subscription = sub_cfg.get('max_quote_subscription', 300)
            self._max_ticker_subscription = sub_cfg.get('max_ticker_subscription', 100)
            self._max_orderbook_subscription = sub_cfg.get('max_orderbook_subscription', 100)
            self._max_rt_data_subscription = sub_cfg.get('max_rt_data_subscription', 100)
        else:
            self._total_quota = 300
            self._max_quote_subscription = 300
            self._max_ticker_subscription = 100
            self._max_orderbook_subscription = 100
            self._max_rt_data_subscription = 100

        # 订阅变化回调
        self._on_change_callbacks: List[Callable] = []
        # 异步回调任务引用（防止 GC 回收和异常丢失）
        self._pending_tasks: set = set()
        self.logger = logging.getLogger(__name__)

        # P1-1: 订阅动作埋点
        self._sub_logger = None

        # 初始化验证器和优化器
        self._validator = SubscriptionValidator(futu_client, db_manager)
        self._optimizer = SubscriptionOptimizer(futu_client, self._validator)

    def switch_market(self, new_markets: List[str]) -> Dict[str, Any]:
        """市场切换时取消所有旧订阅

        注意：此方法只负责取消旧订阅，不执行新订阅。
        调用方需要自行调用 realtime_service.subscribe_target_stocks() 完成新订阅。

        Args:
            new_markets: 新的活跃市场列表，如 ['HK'], ['US'], ['HK', 'US']

        Returns:
            Dict: 结果，包含 success, message 等
        """
        self.logger.info(f"开始市场切换，目标市场: {new_markets}")

        # 取消所有旧订阅
        self.unsubscribe_all()

        self.logger.info(f"旧订阅已清除，目标市场: {new_markets}")

        return {
            'success': True,
            'message': f'旧订阅已清除，目标市场: {new_markets}',
            'subscribed_count': 0,
            'markets': new_markets
        }

    @property
    def subscribed_stocks(self) -> Set[str]:
        """获取已订阅股票集合（只读）"""
        return self._subscribed_stocks.copy()

    @property
    def subscribed_count(self) -> int:
        """获取已订阅股票数量"""
        return len(self._subscribed_stocks)

    def is_subscribed(self, stock_code: str) -> bool:
        """检查股票是否已订阅"""
        return stock_code in self._subscribed_stocks

    def get_subscribe_time(self, stock_code: str) -> float:
        """获取股票的订阅时间戳（unix timestamp），未记录则返回 0"""
        return self._subscribe_times.get(stock_code, 0)

    def add_change_callback(self, callback: Callable):
        """添加状态变更回调"""
        if callback not in self._on_change_callbacks:
            self._on_change_callbacks.append(callback)

    def _notify_change(self):
        """通知状态变更（支持异步回调，保存 task 引用）"""
        import asyncio
        import inspect

        for callback in self._on_change_callbacks:
            try:
                if inspect.iscoroutinefunction(callback):
                    # 异步回调：尝试在当前事件循环中调度
                    try:
                        loop = asyncio.get_running_loop()
                        task = asyncio.create_task(callback(self._subscribed_stocks.copy()))
                        self._pending_tasks.add(task)
                        task.add_done_callback(self._on_task_done)
                    except RuntimeError:
                        # 没有运行中的事件循环，记录警告
                        self.logger.warning(f"异步回调无法执行（无事件循环）: {callback}")
                else:
                    # 同步回调：直接调用
                    callback(self._subscribed_stocks.copy())
            except Exception as e:
                self.logger.warning(f"订阅状态回调执行失败: {e}")

    def _on_task_done(self, task: 'asyncio.Task'):
        """异步回调任务完成回调：移除引用 + 记录异常"""
        self._pending_tasks.discard(task)
        if not task.cancelled() and task.exception():
            self.logger.error(
                f"订阅变更异步回调异常: {task.exception()}",
                exc_info=task.exception()
            )

    def remove_change_callback(self, callback: Callable):
        """移除状态变更回调"""
        try:
            self._on_change_callbacks.remove(callback)
        except ValueError:
            pass

    def subscribe(self, stock_codes: List[str]) -> Dict[str, Any]:
        """
        订阅股票数据

        Args:
            stock_codes: 股票代码列表

        Returns:
            Dict: 订阅结果详情
        """
        result = self._init_result(len(stock_codes))

        if not self._validate_preconditions(result):
            return result

        if not stock_codes:
            result['success'] = True
            result['message'] = '没有需要订阅的股票'
            return result

        # 过滤已订阅的股票
        new_stocks, already_subscribed = self._filter_already_subscribed(stock_codes)
        result['already_subscribed'] = already_subscribed

        if not new_stocks:
            result['success'] = True
            result['message'] = f'所有 {len(stock_codes)} 只股票都已订阅'
            result['successful_stocks'] = list(stock_codes)
            return result

        # 分批处理订阅
        t0 = time.time()
        self._optimizer.process_batches(new_stocks, result)
        duration_ms = (time.time() - t0) * 1000

        # 更新内部状态
        if result['successful_stocks']:
            new_successful = set(result['successful_stocks']) - self._subscribed_stocks
            self._subscribed_stocks.update(new_successful)
            # 同步更新 QUOTE 订阅集合（subscribe 方法默认订阅 QUOTE 类型）
            self._quote_subscribed.update(new_successful)
            # 记录订阅时间
            now = time.time()
            for code in new_successful:
                self._subscribe_times[code] = now
            self._notify_change()

        # P1-1: 订阅埋点
        self._log_sub_action(
            action='subscribe',
            total=len(stock_codes),
            success=len(result['successful_stocks']),
            failed=len(result['failed_stocks']),
            duration_ms=duration_ms,
        )

        # 构建结果消息
        self._build_summary(result)

        return result

    def unsubscribe(self, stock_codes: List[str]) -> bool:
        """取消订阅股票"""
        if not self._is_client_available() or not stock_codes:
            return False

        try:
            stocks_to_unsub = [c for c in stock_codes if c in self._subscribed_stocks]
            if not stocks_to_unsub:
                return True

            ret, err_msg = self._futu_client.unsubscribe_stocks(
                stocks_to_unsub, [SubType.QUOTE]
            )

            if ret == RET_OK:
                self._subscribed_stocks.difference_update(stocks_to_unsub)
                # 同步更新 QUOTE 订阅集合
                self._quote_subscribed.difference_update(stocks_to_unsub)
                for code in stocks_to_unsub:
                    self._subscribe_times.pop(code, None)
                self._notify_change()
                self.logger.debug(f"成功取消订阅 {len(stocks_to_unsub)} 只股票")
                return True
            else:
                self.logger.error(f"取消订阅失败: {err_msg}")
                return False

        except Exception as e:
            self.logger.error(f"取消订阅异常: {e}")
            return False

    def force_clear_subscriptions(self, stock_codes: List[str]) -> None:
        """强制清除内存中的订阅状态（不调用 Futu API）

        用途：网络断开后 OpenD 侧订阅已丢失，需要清除内存状态
        以便后续 subscribe() 不会因"已订阅"而跳过这些股票。

        Args:
            stock_codes: 需要清除状态的股票代码列表
        """
        codes_set = set(stock_codes)
        cleared_quote = len(self._quote_subscribed & codes_set)
        cleared_ticker = len(self._ticker_subscribed & codes_set)
        cleared_orderbook = len(self._orderbook_subscribed & codes_set)
        cleared_rt_data = len(self._rt_data_subscribed & codes_set)

        self._quote_subscribed.difference_update(codes_set)
        self._ticker_subscribed.difference_update(codes_set)
        self._orderbook_subscribed.difference_update(codes_set)
        self._rt_data_subscribed.difference_update(codes_set)
        # _subscribed_stocks 指向 _quote_subscribed，无需单独更新

        for code in stock_codes:
            self._subscribe_times.pop(code, None)

        self.logger.info(
            f"[强制清除] 已清除 {len(stock_codes)} 只股票的内存订阅状态 "
            f"(QUOTE:{cleared_quote}, TICKER:{cleared_ticker}, "
            f"ORDER_BOOK:{cleared_orderbook}, RT_DATA:{cleared_rt_data})"
        )

    def unsubscribe_all(self):
        """取消所有订阅"""
        if not self._is_client_available() or not self._subscribed_stocks:
            return

        try:
            stock_list = list(self._subscribed_stocks)
            ret, err_msg = self._futu_client.unsubscribe_stocks(
                stock_list, [SubType.QUOTE]
            )

            if ret == RET_OK:
                self._subscribed_stocks.clear()
                # 同步清空 QUOTE 订阅集合
                self._quote_subscribed.clear()
                self._notify_change()
                self.logger.debug("已取消所有股票订阅")
            else:
                self.logger.error(f"取消全部订阅失败: {err_msg}")
        except Exception as e:
            self.logger.error(f"取消全部订阅异常: {e}")

    # ==================== P2-2: 分级订阅恢复 ====================

    def restore_subscriptions_by_priority(self) -> Dict[str, Any]:
        """P2-2: 分级恢复订阅（P0持仓 → P1策略目标 → P2其他）

        每批间隔 200ms，确保持仓股报价 <1s 恢复。

        Returns:
            恢复结果
        """
        result = {'total': 0, 'success': 0, 'failed': 0, 'batches': []}

        # 从持久化恢复订阅列表
        saved_codes = self._load_subscription_snapshot()
        if not saved_codes:
            self.logger.info("[分级恢复] 无持久化订阅快照，跳过")
            return result

        # P0: 持仓股（最高优先级）
        position_codes = self._get_position_codes()
        p0 = [c for c in saved_codes if c in position_codes]

        # P1: 策略监控目标
        strategy_codes = self._get_strategy_target_codes()
        p1 = [c for c in saved_codes if c in strategy_codes and c not in position_codes]

        # P2: 其他
        p0_p1 = set(p0) | set(p1)
        p2 = [c for c in saved_codes if c not in p0_p1]

        for priority, batch_name, codes in [(0, 'P0_持仓', p0), (1, 'P1_策略', p1), (2, 'P2_其他', p2)]:
            if not codes:
                continue
            batch_result = self.subscribe(codes)
            batch_info = {
                'name': batch_name,
                'total': len(codes),
                'success': len(batch_result.get('successful_stocks', [])),
                'failed': len(batch_result.get('failed_stocks', [])),
            }
            result['batches'].append(batch_info)
            result['total'] += len(codes)
            result['success'] += batch_info['success']
            result['failed'] += batch_info['failed']

            self.logger.info(f"[分级恢复] {batch_name}: {batch_info['success']}/{len(codes)}")
            if priority < 2:
                time.sleep(0.2)  # 批间间隔 200ms

        return result

    def _get_position_codes(self) -> set:
        """从数据库获取持仓股代码"""
        if not self._db_manager:
            return set()
        try:
            # 从 trade_signals 表查持仓
            conn = self._db_manager.get_connection()
            cursor = conn.execute(
                "SELECT DISTINCT stock_code FROM trade_signals WHERE signal_type='BUY' "
                "ORDER BY created_at DESC LIMIT 50"
            )
            return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            self.logger.debug(f"获取持仓股代码失败: {e}")
            return set()

    def _get_strategy_target_codes(self) -> set:
        """从数据库获取策略监控目标代码"""
        if not self._db_manager:
            return set()
        try:
            conn = self._db_manager.get_connection()
            cursor = conn.execute(
                "SELECT DISTINCT stock_code FROM stock_pool WHERE is_active=1"
            )
            return {row[0] for row in cursor.fetchall()}
        except Exception:
            return set()

    def save_subscription_snapshot(self):
        """P2-2: 将当前订阅状态持久化到 SQLite"""
        if not self._db_manager:
            return
        try:
            conn = self._db_manager.get_connection()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subscription_snapshot (
                    type TEXT PRIMARY KEY,
                    codes TEXT,
                    updated_at INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            import json
            now = int(time.time())
            snapshots = {
                'QUOTE': self._quote_subscribed,
                'TICKER': self._ticker_subscribed,
                'ORDER_BOOK': self._orderbook_subscribed,
                'RT_DATA': self._rt_data_subscribed,
            }
            for sub_type, codes in snapshots.items():
                codes_json = json.dumps(list(codes))
                conn.execute(
                    "INSERT OR REPLACE INTO subscription_snapshot (type, codes, updated_at) "
                    "VALUES (?, ?, ?)",
                    (sub_type, codes_json, now)
                )
            conn.commit()
            self.logger.debug(f"订阅快照已保存: {len(self._subscribed_stocks)} 只")
        except Exception as e:
            self.logger.warning(f"保存订阅快照失败: {e}")

    def _load_subscription_snapshot(self) -> list:
        """从 SQLite 恢复订阅列表"""
        if not self._db_manager:
            return []
        try:
            conn = self._db_manager.get_connection()
            cursor = conn.execute(
                "SELECT codes FROM subscription_snapshot WHERE type='QUOTE'"
            )
            row = cursor.fetchone()
            if row:
                import json
                return json.loads(row[0])
        except Exception as e:
            self.logger.debug(f"加载订阅快照失败: {e}")
        return []

    def _init_result(self, total: int) -> Dict[str, Any]:
        """初始化结果字典"""
        return {
            'success': False,
            'message': '',
            'total_requested': total,
            'successful_stocks': [],
            'failed_stocks': [],
            'deferred_stocks': [],  # 因额度不足而延迟的股票
            'already_subscribed': [],
            'otc_stocks': [],
            'errors': []
        }

    def _validate_preconditions(self, result: Dict) -> bool:
        """验证前置条件"""
        if not self._is_client_available():
            result['message'] = '富途API不可用'
            result['errors'].append('富途API不可用')
            return False
        return True

    def _is_client_available(self) -> bool:
        """检查客户端是否可用"""
        return (FUTU_AVAILABLE and
                self._futu_client is not None and
                self._futu_client.is_available())

    def _filter_already_subscribed(self, stock_codes: List[str]):
        """过滤已订阅的股票"""
        new_stocks = []
        already_subscribed = []

        for code in stock_codes:
            if code in self._subscribed_stocks:
                already_subscribed.append(code)
            else:
                new_stocks.append(code)

        return new_stocks, already_subscribed

    def _build_summary(self, result: Dict):
        """构建结果摘要"""
        total_success = len(result['successful_stocks']) + len(result['already_subscribed'])
        total_failed = len(result['failed_stocks'])
        total_otc = len(result['otc_stocks'])
        total_deferred = len(result.get('deferred_stocks', []))

        parts = []
        if total_success > 0:
            parts.append(f'成功 {total_success} 只')
        if total_failed > 0:
            parts.append(f'失败 {total_failed} 只')
        if total_otc > 0:
            parts.append(f'OTC股票 {total_otc} 只')
        if total_deferred > 0:
            parts.append(f'延迟 {total_deferred} 只')

        if total_failed == 0 and total_otc == 0 and total_deferred == 0:
            result['success'] = True
            result['message'] = f'成功订阅所有 {total_success} 只股票'
        elif total_success > 0 or total_deferred > 0:
            result['success'] = True
            result['message'] = f'订阅处理完成: {", ".join(parts)}'
        else:
            result['success'] = False
            result['message'] = f'订阅失败: {", ".join(parts)}'

        self.logger.debug(f"订阅完成: {result['message']}")

    # ==================== 多类型订阅支持 ====================

    def subscribe_multi_types(
        self,
        stock_codes: List[str],
        sub_types: List
    ) -> Dict[str, Any]:
        """订阅多种类型的数据

        Args:
            stock_codes: 股票代码列表
            sub_types: 订阅类型列表 [SubType.QUOTE, SubType.TICKER, SubType.ORDER_BOOK]

        Returns:
            {
                'success': bool,
                'subscribed_count': int,
                'failed_stocks': List[str],
                'by_type': {
                    'QUOTE': {'success': [...], 'failed': [...]},
                    'TICKER': {'success': [...], 'failed': [...]},
                    'ORDER_BOOK': {'success': [...], 'failed': [...]}
                }
            }
        """
        result = {
            'success': True,
            'subscribed_count': 0,
            'failed_stocks': [],
            'by_type': {}
        }

        # 收集所有成功订阅的股票（按类型）
        success_by_type = {st: set() for st in sub_types}

        for sub_type in sub_types:
            type_result = self._subscribe_by_type(stock_codes, sub_type)
            # SubType 的属性是字符串，直接使用
            result['by_type'][str(sub_type)] = type_result
            result['subscribed_count'] += len(type_result['success'])
            result['failed_stocks'].extend(type_result['failed'])

            # 记录成功订阅的股票
            success_by_type[sub_type].update(type_result['success'])

        # 只为所有类型都成功订阅的股票触发回调
        all_success = set(stock_codes)
        for success_set in success_by_type.values():
            all_success &= success_set

        if all_success:
            self._notify_subscription_change(list(all_success), sub_types)

        return result

    # 订阅分批大小（避免单次请求过大触发 Futu 频率限制）
    _SUBSCRIBE_BATCH_SIZE = 10

    def _subscribe_by_type(self, stock_codes: List[str], sub_type) -> Dict[str, List[str]]:
        """按类型分批订阅（内置频率控制）

        所有订阅调用（主进程/子进程/个股分析）都经过此方法，
        内置分批 + 全局频率控制确保不触发 Futu API 频率限制。

        Args:
            stock_codes: 股票代码列表
            sub_type: 订阅类型 (SubType.QUOTE/TICKER/ORDER_BOOK)

        Returns:
            {'success': [...], 'failed': [...]}
        """
        # SubType 的属性实际上是字符串，直接使用
        type_name = str(sub_type)

        # 获取对应的订阅集合和额度限制
        if type_name == 'QUOTE':
            subscribed_set = self._quote_subscribed
            max_quota = self._max_quote_subscription
        elif type_name == 'TICKER':
            subscribed_set = self._ticker_subscribed
            max_quota = self._max_ticker_subscription
        elif type_name == 'ORDER_BOOK':
            subscribed_set = self._orderbook_subscribed
            max_quota = self._max_orderbook_subscription
        elif type_name == 'RT_DATA':
            subscribed_set = self._rt_data_subscribed
            max_quota = self._max_rt_data_subscription
        else:
            self.logger.warning(f"不支持的订阅类型: {type_name}")
            return {'success': [], 'failed': stock_codes}

        # 过滤已订阅的股票
        to_subscribe = [code for code in stock_codes if code not in subscribed_set]

        if not to_subscribe:
            return {'success': stock_codes, 'failed': []}

        # 检查单类型额度限制
        available_quota = max_quota - len(subscribed_set)

        # 检查富途 API 总额度（所有类型共享）
        total_used = (len(self._quote_subscribed) + len(self._ticker_subscribed)
                      + len(self._orderbook_subscribed) + len(self._rt_data_subscribed))
        total_available = self._total_quota - total_used
        available_quota = min(available_quota, total_available)

        if available_quota <= 0:
            self.logger.warning(
                f"{type_name} 订阅额度耗尽: 单类型剩余 {max_quota - len(subscribed_set)}, "
                f"总额度剩余 {total_available} (已用 {total_used}/{self._total_quota})"
            )
            return {'success': [], 'failed': to_subscribe}

        if len(to_subscribe) > available_quota:
            self.logger.warning(
                f"{type_name} 订阅额度不足: 需要 {len(to_subscribe)} 只，"
                f"可用 {available_quota} 只 (总额度 {total_used}/{self._total_quota})"
            )
            to_subscribe = to_subscribe[:available_quota]

        # 分批订阅（内置频率控制）
        from ..utils.rate_limiter import wait_for_api

        success_stocks = []
        failed_stocks = []

        for i in range(0, len(to_subscribe), self._SUBSCRIBE_BATCH_SIZE):
            batch = to_subscribe[i:i + self._SUBSCRIBE_BATCH_SIZE]

            # 全局频率控制（与其他 Futu API 调用共享限流窗口）
            wait_for_api('subscribe')
            # 批间间隔，避免瞬间大量订阅请求冲击 OpenD
            if i > 0:
                time.sleep(0.5)

            try:
                ret, err = self._futu_client.subscribe_stocks(batch, [sub_type])

                if ret == RET_OK:
                    success_stocks.extend(batch)
                    subscribed_set.update(batch)
                else:
                    failed_stocks.extend(batch)
                    self.logger.warning(f"订阅 {type_name} 批次失败: {err}")
            except Exception as e:
                failed_stocks.extend(batch)
                self.logger.error(f"订阅 {type_name} 批次异常: {e}")

        if success_stocks:
            self.logger.info(f"订阅 {type_name} 成功: {len(success_stocks)} 只股票")

        return {'success': success_stocks, 'failed': failed_stocks}

    def unsubscribe_multi_types(
        self,
        stock_codes: List[str],
        sub_types: List
    ) -> Dict[str, Any]:
        """取消订阅多种类型的数据

        Args:
            stock_codes: 股票代码列表
            sub_types: 订阅类型列表

        Returns:
            {'success': bool, 'message': str}
        """
        for sub_type in sub_types:
            self._unsubscribe_by_type(stock_codes, sub_type)

        # 触发订阅变化回调
        self._notify_subscription_change(stock_codes, sub_types)

        return {
            'success': True,
            'message': f'已取消 {len(stock_codes)} 只股票的订阅'
        }

    def _unsubscribe_by_type(self, stock_codes: List[str], sub_type):
        """按类型取消订阅"""
        # SubType 的属性实际上是字符串，直接使用
        type_name = str(sub_type)

        # 获取对应的订阅集合
        if type_name == 'QUOTE':
            subscribed_set = self._quote_subscribed
        elif type_name == 'TICKER':
            subscribed_set = self._ticker_subscribed
        elif type_name == 'ORDER_BOOK':
            subscribed_set = self._orderbook_subscribed
        elif type_name == 'RT_DATA':
            subscribed_set = self._rt_data_subscribed
        else:
            return

        # 过滤出已订阅的股票
        to_unsubscribe = [code for code in stock_codes if code in subscribed_set]

        if not to_unsubscribe:
            return

        try:
            ret, err = self._futu_client.unsubscribe_stocks(to_unsubscribe, [sub_type])

            if ret == RET_OK:
                subscribed_set.difference_update(to_unsubscribe)
                self.logger.info(
                    f"取消订阅 {type_name} 成功: {len(to_unsubscribe)} 只股票"
                )
            else:
                self.logger.warning(f"取消订阅 {type_name} 失败: {err}")
        except Exception as e:
            self.logger.error(f"取消订阅 {type_name} 异常: {e}")

    def register_callback(self, callback: Callable):
        """注册订阅变化回调（新方法名，更清晰）"""
        self.add_change_callback(callback)

    def _notify_subscription_change(self, stock_codes: List[str], sub_types: List):
        """通知订阅变化（带类型信息）"""
        for callback in self._on_change_callbacks:
            try:
                callback(stock_codes, sub_types)
            except Exception as e:
                self.logger.error(f"订阅回调执行失败: {e}")

    @property
    def ticker_subscribed_stocks(self) -> Set[str]:
        """获取已订阅 TICKER 的股票"""
        return self._ticker_subscribed.copy()

    @property
    def orderbook_subscribed_stocks(self) -> Set[str]:
        """获取已订阅 ORDER_BOOK 的股票"""
        return self._orderbook_subscribed.copy()

    @property
    def rt_data_subscribed_stocks(self) -> Set[str]:
        """获取已订阅 RT_DATA 的股票"""
        return self._rt_data_subscribed.copy()

    def _log_sub_action(self, action: str, total: int, success: int,
                        failed: int, duration_ms: float):
        """P1-1: 记录订阅/取消订阅到独立日志文件"""
        import json
        if self._sub_logger is None:
            import os
            from ..utils.logger import create_dedicated_logger
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
            self._sub_logger = create_dedicated_logger(
                'subscription_trace', os.path.join(log_dir, 'subscription.log')
            )
        entry = {
            "flow": "subscription", "action": action,
            "total": total, "success": success, "failed": failed,
            "duration_ms": round(duration_ms, 1),
        }
        self._sub_logger.info(json.dumps(entry, ensure_ascii=False))


# 向后兼容别名
SubscriptionCore = SubscriptionManager

__all__ = ['SubscriptionManager', 'SubscriptionCore']
