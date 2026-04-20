#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""订阅管理辅助模块 - 负责股票订阅的核心逻辑（含活跃度筛选、Pipeline 集成）"""

import logging
from typing import Dict, Any, List, Optional

from ...database.core.db_manager import DatabaseManager
from ...api.futu_client import FutuClient
from ...api.subscription_manager import SubscriptionManager
from ...api.quote_service import QuoteService
from ...utils.market_helper import MarketTimeHelper
from ..market_data.activity_filter import ActivityFilterService
from ..core.stock_marker import StockMarkerService
from .subscription_version import SubscriptionVersionService
from ..realtime.realtime_stock_query_service import RealtimeStockQueryService
from ..realtime.realtime_kline_service import RealtimeKlineService
from .stock_filter_heat_pipeline import StockFilterHeatPipeline
from ..market_data.kline.background_kline_task import BackgroundKlineTask


class SubscriptionHelper:
    """订阅管理辅助服务 - 负责股票订阅的核心逻辑"""

    def __init__(self, db_manager: DatabaseManager, futu_client: FutuClient,
                 subscription_manager: SubscriptionManager = None,
                 quote_service: QuoteService = None, config=None, container=None):
        self.db_manager = db_manager
        self.futu_client = futu_client
        self.subscription_manager = subscription_manager
        self.config = config
        self.container = container
        self.priority_stocks = set()

        self.activity_filter = ActivityFilterService(
            subscription_manager=subscription_manager,
            quote_service=quote_service, config=config,
            db_manager=db_manager, container=container,
            quote_cache=getattr(container, 'quote_cache', None) if container else None
        )
        self.stock_marker = StockMarkerService(db_manager=db_manager)
        self.version_service = SubscriptionVersionService(db_manager=db_manager)
        self.stock_query_service = RealtimeStockQueryService(
            db_manager=db_manager, futu_client=futu_client, config=config
        )
        self.kline_service = RealtimeKlineService(
            db_manager=db_manager, futu_client=futu_client
        )

        # 初始化后台K线下载任务
        self.background_kline_task = BackgroundKlineTask(container) if container else None

        # 初始化筛选-热度管道
        self.pipeline = None
        self._init_pipeline()

    def _init_pipeline(self, heat_calculator=None):
        """初始化筛选-热度管道

        Args:
            heat_calculator: 热度计算器实例，为 None 时尝试从 container 获取
        """
        if not heat_calculator:
            # 尝试从 container.hot_stock_service.heat_calculator 获取
            if self.container and hasattr(self.container, 'hot_stock_service'):
                hot_service = self.container.hot_stock_service
                if hot_service and hasattr(hot_service, 'heat_calculator'):
                    heat_calculator = hot_service.heat_calculator

        if heat_calculator:
            config_dict = {}
            if self.config:
                config_dict = getattr(self.config, '__dict__', {}) if not isinstance(self.config, dict) else self.config

            self.pipeline = StockFilterHeatPipeline(
                activity_filter=self.activity_filter,
                heat_calculator=heat_calculator,
                config=config_dict,
            )
            logging.info("【Pipeline】筛选-热度管道初始化成功")
        else:
            logging.info("【Pipeline】heat_calculator 暂不可用，等待延迟注入")

    def set_priority_stocks(self, stock_codes: List[str]):
        """设置需要优先订阅的股票（如持仓股票），跳过活跃度筛选"""
        self.priority_stocks = set(stock_codes) if stock_codes else set()
        if self.priority_stocks:
            logging.info(f"【优先订阅】设置 {len(self.priority_stocks)} 只: {list(self.priority_stocks)[:5]}...")

    def get_priority_stocks(self) -> List[str]:
        return list(self.priority_stocks)

    def subscribe_target_stocks(self, markets: Optional[List[str]] = None) -> Dict[str, Any]:
        """订阅目标板块的所有股票行情 - 支持实时活跃度筛选和按市场数量限制"""
        result = {'success': False, 'message': '', 'subscribed_count': 0, 'market_info': {}, 'errors': []}
        try:
            if not self.futu_client.is_available():
                result['message'] = '富途API不可用，无法订阅行情'
                result['errors'].append('富途API不可用')
                return result

            result['market_info'] = self._resolve_markets(markets)
            markets = result['market_info']['selected_markets']

            market_limits = self._get_config_attr('monitor_stocks_limit_by_market', {'HK': 50, 'US': 50})
            af_config = self._get_config_attr('realtime_activity_filter', {})
            af_enabled = af_config.get('enabled', True) if af_config else True
            kline_priority = self._get_config_attr('kline_priority_enabled', True)

            target_stocks = self.stock_query_service.get_target_stocks(
                limit=None, markets=markets, kline_priority=kline_priority,
                position_codes=self.priority_stocks
            )
            if not target_stocks:
                result['message'] = f'未找到需要订阅的股票（市场: {", ".join(markets)}）'
                return result

            logging.info(f"【股票池】获取到 {len(target_stocks)} 只股票，准备活跃度筛选")
            target_stocks = self._apply_activity_filter(target_stocks, market_limits, af_enabled, af_config)

            # 订阅前清理不活跃订阅，释放额度
            target_codes = {s['code'] for s in target_stocks}
            self.cleanup_inactive_subscriptions(target_codes)

            # 订阅 QUOTE（必须）
            subscribe_result = self.subscription_manager.subscribe([s['code'] for s in target_stocks])
            if subscribe_result['success']:
                self._handle_subscribe_success(result, subscribe_result, target_stocks)

                # 如果 Scalping 引擎启用，同时订阅 TICKER 和 ORDER_BOOK
                if self._is_scalping_enabled():
                    # 限制 Scalping 订阅数量（从配置读取）
                    sub_cfg = self._get_config_attr('subscription_config', {})
                    scalping_max = sub_cfg.get('scalping_max_stocks', 50)
                    scalping_stocks = [s['code'] for s in target_stocks[:scalping_max]]

                    try:
                        from futu import SubType
                        multi_result = self.subscription_manager.subscribe_multi_types(
                            scalping_stocks,
                            [SubType.TICKER, SubType.ORDER_BOOK]
                        )

                        # SubType 的属性是字符串，直接使用字符串作为 key
                        ticker_success = len(multi_result['by_type'].get('TICKER', {}).get('success', []))
                        orderbook_success = len(multi_result['by_type'].get('ORDER_BOOK', {}).get('success', []))

                        logging.info(
                            f"【Scalping订阅】TICKER {ticker_success} 只, "
                            f"ORDER_BOOK {orderbook_success} 只"
                        )
                    except Exception as e:
                        logging.error(f"Scalping 多类型订阅失败: {e}", exc_info=True)

                # 订阅成功后，延迟提交后台K线下载任务（避免与启动阶段报价轮询争抢 OpenD）
                if self.background_kline_task:
                    import threading
                    def _delayed_kline_submit():
                        import time as _t
                        _t.sleep(120)  # 延迟 120 秒，等系统完全稳定
                        logging.info(f"[后台K线] 延迟期满，开始下载 {len(target_stocks)} 只股票的K线")
                        self.background_kline_task.submit(target_stocks)
                    threading.Thread(target=_delayed_kline_submit, daemon=True, name="kline-delay").start()
                    logging.info("[后台K线] 已安排 120 秒后开始下载（避免启动冲击）")
            else:
                self._handle_subscribe_failure(result, subscribe_result, len(target_stocks))
        except Exception as e:
            logging.error(f"订阅股票行情失败: {e}", exc_info=True)
            result.update({'success': False, 'message': f'订阅股票行情异常: {str(e)}'})
            result['errors'].append(str(e))
        return result

    def cleanup_inactive_subscriptions(self, active_codes: set) -> int:
        """清理不活跃订阅，释放订阅额度

        对比当前已订阅股票与最新目标股票池，取消不在目标池中的股票订阅。
        避免订阅集合只增不减，超出富途API 300只限制。

        注意：尊重富途 API 的 1 分钟最短订阅时间限制，跳过刚订阅不满 65 秒的股票。

        Args:
            active_codes: 当前筛选后应保留的股票代码集合

        Returns:
            清理掉的订阅数量
        """
        if not self.subscription_manager:
            return 0

        try:
            import time
            now = time.time()
            MIN_SUBSCRIPTION_SECONDS = 65  # 富途要求至少 1 分钟，留 5 秒余量

            currently_subscribed = self.subscription_manager.subscribed_stocks
            inactive_codes = currently_subscribed - active_codes - self.priority_stocks

            if not inactive_codes:
                return 0

            # 过滤掉订阅不满 65 秒的股票（尊重富途 API 限制）
            eligible_to_clean = set()
            too_recent = set()
            for code in inactive_codes:
                sub_time = self.subscription_manager.get_subscribe_time(code)
                if sub_time > 0 and (now - sub_time) < MIN_SUBSCRIPTION_SECONDS:
                    too_recent.add(code)
                else:
                    eligible_to_clean.add(code)

            if too_recent:
                logging.debug(
                    f"【订阅清理】跳过 {len(too_recent)} 只订阅不满1分钟的股票"
                )

            if not eligible_to_clean:
                return 0

            cleaned = 0
            success = self.subscription_manager.unsubscribe(list(eligible_to_clean))
            if success:
                cleaned = len(eligible_to_clean)
                logging.info(
                    f"【订阅清理】已取消 {cleaned} 只不活跃股票的订阅，"
                    f"当前剩余 {len(self.subscription_manager.subscribed_stocks)} 只，"
                    f"清理列表: {list(eligible_to_clean)[:10]}{'...' if len(eligible_to_clean) > 10 else ''}"
                )
            else:
                logging.warning(f"【订阅清理】取消订阅失败，目标清理 {len(eligible_to_clean)} 只")

            return cleaned
        except Exception as e:
            logging.error(f"【订阅清理】清理不活跃订阅异常: {e}", exc_info=True)
            return 0

    def initialize_realtime_data(self) -> Dict[str, Any]:
        """初始化实时数据服务（订阅 + K线下载）"""
        result = {'success': False, 'message': '', 'steps': [], 'errors': []}
        try:
            sub_result = self.subscribe_target_stocks()
            result['steps'].append(f"订阅行情: {sub_result['message']}")
            if not sub_result['success']:
                result['errors'].extend(sub_result['errors'])
                result['message'] = '订阅行情失败'
                return result

            codes = list(self.subscription_manager.subscribed_stocks) if self.subscription_manager else []
            kline_result = self.kline_service.fetch_and_save_kline_data(codes)
            result['steps'].append(f"K线数据: {kline_result['message']}")
            if kline_result['errors']:
                result['errors'].extend(kline_result['errors'])

            result.update({
                'success': True,
                'message': f'初始化完成: 订阅{sub_result["subscribed_count"]}只股票，保存{kline_result["saved_klines"]}条K线'
            })
            logging.info(result['message'])
        except Exception as e:
            logging.error(f"初始化实时数据服务失败: {e}", exc_info=True)
            result.update({'success': False, 'message': f'初始化异常: {str(e)}'})
            result['errors'].append(str(e))
        return result

    def unsubscribe_all(self) -> bool:
        """取消所有订阅"""
        try:
            if self.subscription_manager and self.subscription_manager.subscribed_stocks:
                self.subscription_manager.unsubscribe_all()
                logging.info("成功取消所有股票订阅")
                return True
            return False
        except Exception as e:
            logging.error(f"取消订阅失败: {e}", exc_info=True)
            return False

    def initialize_subscription_once(self) -> Dict[str, Any]:
        """一次性初始化订阅（系统启动时调用）"""
        result = {'success': False, 'message': '', 'subscribed_count': 0, 'version': '', 'errors': []}
        try:
            current_version = self.version_service.calculate_stock_pool_version()
            if self.version_service.is_initialized and self.version_service.current_version == current_version:
                count = len(self.subscription_manager.subscribed_stocks) if self.subscription_manager else 0
                result.update({
                    'success': True, 'subscribed_count': count, 'version': current_version,
                    'message': f'订阅已存在且版本一致 (版本: {current_version})'
                })
                logging.info(f"订阅状态无变化，跳过重新订阅，版本: {current_version}")
                return result

            sub_result = self.subscribe_target_stocks()
            if sub_result['success']:
                self.version_service.mark_initialized(current_version, sub_result['subscribed_count'])
                result.update({
                    'success': True, 'version': current_version,
                    'subscribed_count': sub_result['subscribed_count'],
                    'message': f'订阅初始化完成 (版本: {current_version})'
                })
                logging.info(f"订阅初始化完成: {sub_result['subscribed_count']}只股票，版本: {current_version}")
            else:
                result.update(sub_result)
                result['errors'].extend(sub_result.get('errors', []))
        except Exception as e:
            logging.error(f"初始化订阅失败: {e}", exc_info=True)
            result.update({'success': False, 'message': f'初始化订阅异常: {str(e)}'})
            result['errors'].append(str(e))
        return result

    # ========== 私有辅助方法 ==========

    def _get_config_attr(self, attr: str, default):
        """从 config 获取属性，不存在时返回默认值"""
        if self.config:
            return getattr(self.config, attr, default)
        return default

    def _resolve_markets(self, markets: Optional[List[str]]) -> Dict[str, Any]:
        """解析目标市场"""
        if markets is not None:
            return {'selected_markets': markets, 'time_based_selection': False}
        active = MarketTimeHelper.get_current_active_markets()
        primary = MarketTimeHelper.get_primary_market()
        MarketTimeHelper.log_market_info()
        selected = active if active else [primary]
        logging.info(f"【市场选择】活跃: {active}, 主要: {primary}, 最终: {selected}")
        return {
            'active_markets': active, 'primary_market': primary,
            'selected_markets': selected, 'time_based_selection': True
        }

    def _apply_activity_filter(self, target_stocks, market_limits, enabled, config) -> List[Dict[str, Any]]:
        """应用活跃度筛选（优先使用 Pipeline）"""
        if not enabled:
            # 未启用活跃度筛选，直接按市场限制截断
            target_stocks = self.activity_filter.calculator.apply_market_limits(target_stocks, market_limits)
            logging.info(f"按市场限制后剩余 {len(target_stocks)} 只股票")
            return target_stocks

        original_count = len(target_stocks)

        # 优先使用 Pipeline（活跃度筛选 → 热度计算 → 热度排序截断）
        if self.pipeline:
            logging.info(f"【Pipeline】开始执行，市场限制: {market_limits}")
            result = self.pipeline.execute(
                stocks=target_stocks,
                market_limits=market_limits,
                activity_config=config,
                priority_stocks=list(self.priority_stocks)
            )
            logging.info(
                f"【Pipeline】完成，{original_count} → 活跃 {result.active_count} → "
                f"最终 {result.final_count} 只"
            )
            return result.stocks

        # Pipeline 不可用，回退到原有流程
        logging.info(f"【活跃度筛选】Pipeline 不可用，使用原有流程，市场限制: {market_limits}")
        target_stocks = self.activity_filter.filter_by_realtime_activity(
            target_stocks, market_limits, config, priority_stocks=list(self.priority_stocks)
        )
        logging.info(f"【活跃度筛选】完成，剩余 {len(target_stocks)}/{original_count} 只股票")
        return target_stocks

    def _handle_subscribe_success(self, result, subscribe_result, target_stocks):
        """处理订阅成功的结果"""
        final = self.subscription_manager.subscribed_stocks

        # 处理 OTC 股票标记
        otc_stocks = subscribe_result.get('otc_stocks', [])
        if otc_stocks:
            marked = self.stock_marker.mark_otc_stocks(otc_stocks)
            logging.info(f"检测到 {len(otc_stocks)} 只OTC股票，已标记 {marked} 只")

        # 统计
        total_ok = len(final)
        total_fail = len(subscribe_result['failed_stocks'])
        total_otc = len(otc_stocks)
        market_stats = self._count_by_market(target_stocks, final)
        summary = ', '.join([f"{m}: {c}只" for m, c in market_stats.items()])

        if total_fail == 0 and total_otc == 0:
            msg = f'成功订阅所有 {total_ok} 只股票的行情 ({summary})'
        else:
            msg = f'订阅完成: 成功 {total_ok}, 失败 {total_fail}, OTC {total_otc} ({summary})'

        result.update({
            'success': True, 'message': msg,
            'subscribed_count': total_ok, 'failed_count': total_fail, 'otc_count': total_otc,
            'subscribed_stocks': [s for s in target_stocks if s['code'] in final],
            'subscription_details': {
                'successful_stocks': subscribe_result['successful_stocks'],
                'already_subscribed': subscribe_result['already_subscribed'],
                'failed_stocks': subscribe_result['failed_stocks'],
                'otc_stocks': otc_stocks
            }
        })
        if subscribe_result['failed_stocks']:
            result['errors'].append(f"订阅失败: {', '.join(subscribe_result['failed_stocks'])}")
            result['errors'].extend(subscribe_result.get('errors', []))
        logging.info(f"按优先级和市场筛选{msg}")

    def _handle_subscribe_failure(self, result, subscribe_result, stock_count):
        """处理订阅失败的结果"""
        result.update({
            'success': False, 'message': subscribe_result['message'],
            'subscribed_count': 0, 'failed_count': stock_count,
            'subscription_details': subscribe_result
        })
        result['errors'].append(subscribe_result['message'])
        result['errors'].extend(subscribe_result.get('errors', []))

    @staticmethod
    def _count_by_market(stocks, subscribed_set) -> Dict[str, int]:
        """按市场统计已订阅股票数量"""
        counts = {}
        for s in stocks:
            if s['code'] in subscribed_set:
                m = s.get('market', 'Unknown')
                counts[m] = counts.get(m, 0) + 1
        return counts

    def _is_scalping_enabled(self) -> bool:
        """检查 Scalping 引擎是否启用（基于配置）

        注意：SCALPING_MODE=process 时返回 False，因为子进程通过
        get_rt_ticker()/get_order_book() 独立轮询，不需要主进程的推送订阅。
        """
        try:
            # 进程模式：子进程独立轮询，主进程不需要订阅 TICKER/ORDER_BOOK
            import os
            if os.environ.get('SCALPING_MODE', '').lower() == 'process':
                logging.debug("Scalping 进程模式：跳过主进程 TICKER/ORDER_BOOK 订阅")
                return False

            # 从配置读取 scalping_max_stocks
            sub_cfg = self._get_config_attr('subscription_config', {})
            scalping_max = sub_cfg.get('scalping_max_stocks', 0)

            # 如果配置了 scalping_max_stocks > 0，则启用
            is_enabled = scalping_max > 0

            if is_enabled:
                logging.debug(f"Scalping 引擎已启用 (scalping_max_stocks: {scalping_max})")
            else:
                logging.debug("Scalping 引擎未启用 (scalping_max_stocks 配置为 0 或未配置)")

            return is_enabled
        except Exception as e:
            logging.debug(f"检查 Scalping 引擎状态失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 个股分析临时订阅
    # ------------------------------------------------------------------

    def subscribe_for_analysis(self, stock_code: str) -> Dict[str, Any]:
        """为个股分析临时订阅股票

        策略：
        1. 检查是否已订阅
        2. 如未订阅且额度已满，临时替换低优先级股票
        3. 订阅 TICKER 和 ORDER_BOOK

        Args:
            stock_code: 股票代码

        Returns:
            {
                'success': bool,
                'message': str,
                'replaced': str | None  # 被替换的股票代码
            }
        """
        try:
            from futu import SubType

            # 检查是否已订阅
            if stock_code in self.subscription_manager.ticker_subscribed_stocks:
                return {
                    'success': True,
                    'message': '股票已订阅',
                    'replaced': None
                }

            # 检查额度
            ticker_subscribed = self.subscription_manager.ticker_subscribed_stocks
            max_quota = self.subscription_manager._max_ticker_subscription

            replaced_stock = None
            if len(ticker_subscribed) >= max_quota:
                # 额度已满，需要替换
                replaced_stock = self._find_replaceable_stock(ticker_subscribed)
                if replaced_stock:
                    # 反订阅低优先级股票
                    self.subscription_manager.unsubscribe_multi_types(
                        [replaced_stock],
                        [SubType.TICKER, SubType.ORDER_BOOK]
                    )
                    logging.info(f"【临时订阅】替换: {replaced_stock} -> {stock_code}")
                else:
                    return {
                        'success': False,
                        'message': '订阅额度已满且无可替换的股票',
                        'replaced': None
                    }

            # 订阅新股票
            result = self.subscription_manager.subscribe_multi_types(
                [stock_code],
                [SubType.TICKER, SubType.ORDER_BOOK]
            )

            success = result['subscribed_count'] > 0
            return {
                'success': success,
                'message': '临时订阅成功' if success else '订阅失败',
                'replaced': replaced_stock
            }

        except Exception as e:
            logging.error(f"临时订阅失败: {e}")
            return {
                'success': False,
                'message': f'订阅异常: {str(e)}',
                'replaced': None
            }

    def _find_replaceable_stock(self, subscribed_stocks: set) -> Optional[str]:
        """查找可替换的低优先级股票

        优先级：
        1. 不在活跃个股列表中的股票
        2. 换手率最低的股票（避免影响活跃个股页面）

        Args:
            subscribed_stocks: 当前已订阅的股票集合

        Returns:
            可替换的股票代码，如果没有则返回 None
        """
        try:
            # 获取活跃个股列表
            active_stocks = set(self._get_active_stocks())

            # 查找不在活跃列表中的股票
            replaceable = subscribed_stocks - active_stocks
            if replaceable:
                # 返回第一个不在活跃列表中的股票
                return list(replaceable)[0]

            # 如果都在活跃列表中，返回 None（避免影响活跃个股页面）
            logging.warning("所有已订阅股票都在活跃列表中，无法替换")
            return None

        except Exception as e:
            logging.error(f"查找可替换股票失败: {e}")
            return None

    def _get_active_stocks(self) -> List[str]:
        """获取活跃个股列表

        Returns:
            活跃个股代码列表（按换手率排序，前50只）
        """
        try:
            # 从 state_manager 获取缓存的报价数据
            if not self.container or not hasattr(self.container, 'state_manager'):
                return []

            state_manager = self.container.state_manager
            quotes = state_manager.get_cached_quotes()

            if not quotes:
                return []

            # 按换手率排序，取前50只
            sorted_quotes = sorted(
                [q for q in quotes if isinstance(q, dict) and q.get('code')],
                key=lambda q: q.get('turnover_rate', 0) or 0,
                reverse=True
            )

            return [q['code'] for q in sorted_quotes[:50]]

        except Exception as e:
            logging.error(f"获取活跃个股列表失败: {e}")
            return []

