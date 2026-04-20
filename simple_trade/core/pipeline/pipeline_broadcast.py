#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情管道广播与状态更新模块 - 从 QuotePipeline 提取的广播和信号更新逻辑"""

import logging
from datetime import datetime
from typing import List, Dict

from ...websocket import SocketEvent
from ...utils.logger import print_status


class PipelineBroadcast:
    """管道广播处理器 - 负责 WebSocket 广播和交易状态更新"""

    def __init__(self, container, socket_manager, state_manager, alert_service=None, kline_service=None):
        self.container = container
        self.socket_manager = socket_manager
        self.state_manager = state_manager
        # A6: 显式依赖注入
        self.alert_service = alert_service or getattr(container, 'alert_service', None)
        self.kline_service = kline_service or getattr(container, 'kline_service', None)

    async def broadcast(self, quotes: List[Dict], trade_actions: List[Dict],
                        conditions: List[Dict]):
        """统一广播到前端，确保 quotes_update 事件仅广播一次"""
        try:
            alerts = await self._check_alerts(quotes)

            # 累积预警到状态管理器（供 HTTP API 查询）
            if alerts:
                self.state_manager.accumulate_alerts(alerts)

            signals_by_strategy = self.state_manager.get_signals_by_strategy() \
                if hasattr(self.state_manager, 'get_signals_by_strategy') else {}
            await self.socket_manager.emit_to_all(SocketEvent.QUOTES_UPDATE, {
                'quotes': quotes,
                'alerts': alerts,
                'conditions': conditions,
                'trade_actions': trade_actions,
                'signals_by_strategy': signals_by_strategy,
                'timestamp': datetime.now().isoformat()
            })

            if trade_actions:
                await self._broadcast_strategy_signals(trade_actions)

            await self._broadcast_conditions_page()

        except Exception as e:
            logging.error(f"【行情管道】广播失败: {e}", exc_info=True)

    async def _check_alerts(self, quotes: List[Dict]) -> List[Dict]:
        """检查预警（纯内存计算）"""
        try:
            return self.alert_service.check_alerts(quotes)
        except Exception as e:
            logging.error(f"【行情管道】检查预警异常: {e}")
            return []

    async def _broadcast_strategy_signals(self, trade_actions: List[Dict]):
        """广播策略信号到前端（关键信号含重试）"""
        import asyncio
        for action in trade_actions:
            signal_data = {
                'stock_code': action['stock_code'],
                'stock_name': action['stock_name'],
                'signal_type': action['signal_type'].lower(),
                'price': action['price'],
                'reason': action['reason'],
                'timestamp': action.get('timestamp', datetime.now().isoformat()),
                'strategy_name': action.get('strategy_id', '未知策略'),
                'preset_name': ''
            }
            # 关键信号重试（最多2次）
            for attempt in range(3):
                try:
                    await self.socket_manager.emit_to_all(
                        SocketEvent.STRATEGY_SIGNAL, signal_data
                    )
                    break
                except Exception as e:
                    if attempt < 2:
                        logging.warning(
                            f"策略信号广播失败(第{attempt+1}次)，0.5s后重试: {e}"
                        )
                        await asyncio.sleep(0.5)
                    else:
                        logging.error(
                            f"策略信号广播失败(3次均失败) "
                            f"{action['stock_code']}: {e}"
                        )

    async def _broadcast_conditions_page(self):
        """广播数据到交易条件页面（格式与 HTTP API /quotes/conditions 一致）"""
        try:
            quota_data = self.kline_service.get_cached_quota_info()
            if not quota_data:
                quota_data = {
                    'used': 0, 'remaining': 0, 'total': 0,
                    'status': 'cache_miss',
                    'last_update': datetime.now().isoformat()
                }
            conditions_data = self.state_manager.get_trading_conditions()
            formatted = self._format_conditions_for_frontend(conditions_data)
            await self.socket_manager.emit_to_all(SocketEvent.CONDITIONS_UPDATE, {
                'conditions': formatted,
                'quota': quota_data,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logging.error(f"【行情管道】广播条件页面异常: {e}")

    @staticmethod
    def _format_conditions_for_frontend(conditions_data: Dict) -> List[Dict]:
        """将 state_manager 的条件数据转换为前端期望的格式

        与 routers/market/quote.py 的 get_conditions() 保持一致。
        """
        result = []
        for stock_code, cond in conditions_data.items():
            buy_signal = cond.get('buy_signal', False)
            sell_signal = cond.get('sell_signal', False)
            details = cond.get('details', [])

            # 格式化条件明细
            conditions = []
            if details:
                for d in details:
                    if isinstance(d, dict):
                        conditions.append({
                            'name': d.get('name', ''),
                            'description': d.get('description', '') or
                                f"当前值: {d.get('current_value', '')}, 目标值: {d.get('target_value', '')}",
                            'passed': d.get('passed', False),
                            'value': d.get('current_value'),
                            'threshold': d.get('target_value'),
                        })
            else:
                reason = cond.get('reason', '')
                for part in reason.split(' | '):
                    part = part.strip()
                    if not part:
                        continue
                    passed = part.startswith('✅')
                    text = part.replace('✅', '').replace('❌', '').strip()
                    if ':' in text:
                        name, desc = text.split(':', 1)
                        name, desc = name.strip(), desc.strip()
                    else:
                        name, desc = text, text
                    conditions.append({
                        'name': name, 'description': desc, 'passed': passed
                    })

            if buy_signal:
                condition_type = 'buy'
            elif sell_signal:
                condition_type = 'sell'
            else:
                condition_type = 'watch'

            result.append({
                'stock_code': stock_code,
                'stock_name': cond.get('stock_name', ''),
                'condition_type': condition_type,
                'conditions': conditions,
                'all_passed': buy_signal or sell_signal,
            })
        return result

    def update_trading_conditions(self, conditions_data: Dict):
        """更新交易条件数据到状态管理器"""
        updated = {}
        for stock_code, strategies_dict in conditions_data.items():
            if not strategies_dict:
                continue
            first = next(iter(strategies_dict.values()))
            updated[stock_code] = {
                'stock_code': first['stock_code'],
                'stock_name': first['stock_name'],
                'plate_name': first.get('plate_name', ''),
                'strategy_name': first.get('strategy_name', '低吸高抛策略'),
                'condition_passed': first['condition_passed'],
                'reason': first['reason'],
                'details': first.get('details', []),
                'timestamp': datetime.now().isoformat(),
                'buy_signal': first.get('buy_signal', False),
                'sell_signal': first.get('sell_signal', False),
                'strategy_data': first.get('strategy_data', {}),
                'all_strategies': strategies_dict
            }
        self.state_manager.update_trading_conditions(updated)

    def update_trade_signals(self, trade_actions: List[Dict], quotes: List[Dict]):
        """更新交易信号数据到状态管理器"""
        trade_signals = []
        for action in trade_actions:
            quote = next((q for q in quotes if q['code'] == action['stock_code']), {})
            trade_signals.append({
                'id': len(trade_signals) + 1,
                'stock_id': action.get('stock_id', 0),
                'code': action['stock_code'],
                'name': action['stock_name'],
                'market': action.get('market', 'HK'),
                'signal_type': action['signal_type'],
                'signal_price': action['price'],
                'condition_text': action['message'],
                'created_at': action['timestamp'],
                'last_price': quote.get('last_price', action['price']),
                'change_percent': quote.get('change_percent', 0),
                'volume': quote.get('volume', 0),
                'high_price': quote.get('high_price'),
                'low_price': quote.get('low_price')
            })
        self.state_manager.set_trade_signals(trade_signals)
        if trade_signals:
            print_status(f"产生交易信号: {len(trade_signals)} 个", "ok")
