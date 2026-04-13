#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易服务
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from ...database.core.db_manager import DatabaseManager
from ...config.config import Config
from ...core.coordination.strategy_dispatcher import StrategyDispatcher


class TradeService:
    """交易服务"""
    
    def __init__(self, db_manager: DatabaseManager, config: Config, realtime_service,
                 strategy_dispatcher: 'StrategyDispatcher' = None):
        self.db_manager = db_manager
        self.config = config
        self.realtime_service = realtime_service
        # 通过统一调度器执行策略
        self.strategy_dispatcher = strategy_dispatcher
    
    def _get_enhanced_stock_data(self, stock_pool: List[Dict[str, Any]]) -> List[tuple]:
        """获取包含实时报价的增强股票数据"""
        enhanced_stocks = []
        try:
            stock_codes = [stock['code'] for stock in stock_pool]
            if not stock_codes:
                logging.warning("股票池为空，无法获取股票数据")
                return enhanced_stocks

            realtime_result = self.realtime_service.get_realtime_quotes(stock_codes)
            if not realtime_result['success']:
                logging.error(f"获取实时报价失败: {realtime_result['message']}")
                return enhanced_stocks

            quotes_map = {q['code']: q for q in realtime_result['quotes']}
            # 报价返回空数据诊断
            if not quotes_map:
                logging.warning(f"实时报价返回空数据，请求了 {len(stock_codes)} 只股票")
                return enhanced_stocks

            for stock in stock_pool:
                code = stock['code']
                if code not in quotes_map:
                    continue
                q = quotes_map[code]
                enhanced_stocks.append((
                    stock['id'], code, stock['name'],
                    q['last_price'], q['change_percent'], q['volume'],
                    q['high_price'], q['low_price'], q['open_price'],
                    stock.get('plate_name', '')
                ))

            # 报价匹配为零诊断
            if len(enhanced_stocks) == 0:
                logging.warning(
                    f"报价匹配为零: 请求 {len(stock_codes)} 只，"
                    f"报价返回 {len(quotes_map)} 只，无交集"
                )
        except Exception as e:
            logging.error(f"获取增强股票数据失败: {e}")
        return enhanced_stocks

    def _build_trade_action(self, signal_type: str, stock_id, code, name,
                            current_price, strategy_id, strategy_display,
                            reason, strategy_data, realtime_data,
                            strategy_result) -> Dict[str, Any]:
        """构建交易信号动作并写入数据库"""
        condition_text = f"{strategy_display}触发 - {reason} (实时价格: {current_price:.2f})"
        signal_id = self.db_manager.trade_queries.insert_trade_signal_with_dedup(
            stock_id, signal_type, current_price, condition_text,
            strategy_id=strategy_id, strategy_name=strategy_display
        )
        return {
            'action': f'{signal_type.lower()}_signal_generated',
            'stock_code': code, 'stock_name': name,
            'signal_type': signal_type, 'signal_id': signal_id,
            'strategy_id': strategy_id, 'price': current_price,
            'message': f"生成{('买入' if signal_type == 'BUY' else '卖出')}信号: {name}({code}) @ {current_price:.2f}",
            'reason': reason, 'strategy_data': strategy_data,
            'realtime_data': realtime_data,
            'timestamp': datetime.now().isoformat(),
            '_strategy_result': strategy_result,
        }
    
    def auto_trade(self, stock_pool: List[Dict[str, Any]]) -> Dict[str, Any]:
        """策略条件检测 + 自动交易信号生成

        条件检测始终执行（供交易条件页面展示），
        交易信号仅在 auto_trade 开启时才生成。
        """
        trade_actions = []
        conditions_data = {}

        try:
            enhanced_stocks = self._get_enhanced_stock_data(stock_pool)
            if not enhanced_stocks:
                logging.warning("无可用的股票数据，跳过策略条件检测")
                return {'trade_actions': trade_actions, 'conditions_data': conditions_data}

            auto_trade_enabled = self.config.auto_trade

            for es in enhanced_stocks:
                stock_id, code, name, price, chg_pct, vol, high, low, opn, plate = es
                try:
                    self._process_stock_signals(
                        es, trade_actions, conditions_data,
                        generate_signals=auto_trade_enabled
                    )
                except Exception as e:
                    logging.error(f"检查股票 {code} 策略失败: {e}")
                    conditions_data[code] = {
                        'stock_code': code, 'stock_name': name,
                        'plate_name': plate, 'strategy_name': '策略调度',
                        'condition_passed': False,
                        'reason': f'策略检查异常: {str(e)}', 'details': []
                    }

            if trade_actions:
                self._rank_by_signal_strength(trade_actions)
                logging.info(f"生成了 {len(trade_actions)} 个交易信号，已按信号强度排序")

            if conditions_data:
                logging.info(f"检查了 {len(conditions_data)} 只股票的交易条件")
            else:
                logging.debug("检查了 0 只股票的交易条件")

        except Exception as e:
            logging.error(f"自动交易处理失败: {e}")
            import traceback
            logging.error(f"详细错误信息: {traceback.format_exc()}")

        return {'trade_actions': trade_actions, 'conditions_data': conditions_data}

    def _process_stock_signals(self, enhanced_stock: tuple,
                               trade_actions: list, conditions_data: dict,
                               generate_signals: bool = True):
        """处理单只股票的所有策略信号

        Args:
            enhanced_stock: 增强的股票数据元组
            trade_actions: 交易动作列表（会被追加）
            conditions_data: 条件数据字典（会被更新）
            generate_signals: 是否生成交易信号（False 时只做条件检测）
        """
        stock_id, code, name, price, chg_pct, vol, high, low, opn, plate = enhanced_stock
        realtime_data = {
            'code': code, 'last_price': price,
            'high_price': high, 'low_price': low, 'open_price': opn,
            'change_percent': chg_pct, 'volume': vol
        }

        condition_results = self.strategy_dispatcher.dispatch_conditions(enhanced_stock)
        for cr in condition_results:
            conditions_data.setdefault(code, {})
            conditions_data[code][cr.strategy_name] = cr.to_dict()

            if not generate_signals:
                continue

            if not (cr.buy_signal or cr.sell_signal):
                continue

            sr = cr.strategy_result
            reason = (sr.buy_reason if cr.buy_signal else sr.sell_reason) if sr else ''
            signal_type = 'BUY' if cr.buy_signal else 'SELL'
            strategy_display = cr.strategy_name or '未知策略'

            action = self._build_trade_action(
                signal_type, stock_id, code, name, price,
                strategy_id=strategy_display, strategy_display=strategy_display,
                reason=reason, strategy_data=cr.strategy_data,
                realtime_data=realtime_data, strategy_result=sr,
            )
            trade_actions.append(action)
            logging.info(f"生成{signal_type}信号: {code} - {reason} @ {price:.2f}")

    def _rank_by_signal_strength(self, trade_actions: list):
        """按信号强度降序排序，并清理内部引用"""
        for action in trade_actions:
            sr = action.get('_strategy_result')
            action['signal_strength'] = sr.signal_strength if (sr and sr.signal_strength > 0) else 0.0
        trade_actions.sort(key=lambda x: x.get('signal_strength', 0), reverse=True)
        for action in trade_actions:
            action.pop('_strategy_result', None)
    
    
    def execute_trade_signal(self, signal_id: int) -> Dict[str, Any]:
        """执行交易信号（模拟）"""
        result = {'success': False, 'message': ''}
        
        try:
            # 获取信号详情（使用明确字段名避免索引错位）
            signal_data = self.db_manager.execute_query('''
                SELECT ts.id, ts.signal_type, ts.signal_price,
                       s.code, s.name
                FROM trade_signals ts
                JOIN stocks s ON ts.stock_id = s.id
                WHERE ts.id = ?
            ''', (signal_id,))
            
            if not signal_data:
                result['message'] = '信号不存在'
                return result
            
            sig_id, signal_type, signal_price, stock_code, stock_name = signal_data[0]
            
            # 模拟执行交易
            logging.info(f"模拟执行交易: {signal_type} {stock_code}({stock_name}) @ {signal_price}")
            
            # 更新信号状态为已执行
            self.db_manager.execute_update('''
                UPDATE trade_signals 
                SET is_executed = 1, executed_time = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), signal_id))
            
            result.update({
                'success': True,
                'message': f'交易信号已执行: {signal_type} {stock_code} @ {signal_price:.2f}'
            })
            
        except Exception as e:
            logging.error(f"执行交易信号失败: {e}")
            result['message'] = f'执行失败: {str(e)}'
        
        return result
    
    def get_trade_performance(self) -> Dict[str, Any]:
        """获取交易表现统计"""
        performance = {
            'total_signals': 0,
            'executed_signals': 0,
            'buy_signals': 0,
            'sell_signals': 0,
            'success_rate': 0.0,
            'recent_signals': []
        }
        
        try:
            # 总信号数
            total_result = self.db_manager.execute_query('SELECT COUNT(*) FROM trade_signals')
            performance['total_signals'] = total_result[0][0] if total_result else 0
            
            # 已执行信号数
            executed_result = self.db_manager.execute_query('SELECT COUNT(*) FROM trade_signals WHERE is_executed = 1')
            performance['executed_signals'] = executed_result[0][0] if executed_result else 0
            
            # 买入信号数
            buy_result = self.db_manager.execute_query('SELECT COUNT(*) FROM trade_signals WHERE signal_type = "BUY"')
            performance['buy_signals'] = buy_result[0][0] if buy_result else 0
            
            # 卖出信号数
            sell_result = self.db_manager.execute_query('SELECT COUNT(*) FROM trade_signals WHERE signal_type = "SELL"')
            performance['sell_signals'] = sell_result[0][0] if sell_result else 0
            
            # 执行率（已执行 / 总信号数）
            if performance['total_signals'] > 0:
                performance['success_rate'] = round((performance['executed_signals'] / performance['total_signals']) * 100, 1)
            
            # 最近信号 - 使用配置中的数量而不是硬编码
            recent_signals = self.db_manager.trade_history_queries.get_recent_trade_signals(hours=24, limit=self.config.max_recent_signals)
            performance['recent_signals'] = [
                {
                    'id': signal.id,
                    'stock_code': signal.stock_code,
                    'stock_name': signal.stock_name,
                    'signal_type': signal.signal_type,
                    'price': signal.signal_price,
                    'is_executed': signal.is_executed,
                    'created_at': signal.created_at
                }
                for signal in recent_signals
            ]
            
        except Exception as e:
            logging.error(f"获取交易表现失败: {e}")
        
        return performance
    
    def cancel_trade_signal(self, signal_id: int) -> Dict[str, Any]:
        """取消交易信号"""
        result = {'success': False, 'message': ''}
        
        try:
            # 检查信号是否存在且未执行
            signal_data = self.db_manager.execute_query('''
                SELECT is_executed FROM trade_signals WHERE id = ?
            ''', (signal_id,))
            
            if not signal_data:
                result['message'] = '信号不存在'
                return result
            
            if signal_data[0][0]:  # 已执行
                result['message'] = '信号已执行，无法取消'
                return result
            
            # 删除信号
            self.db_manager.execute_update('DELETE FROM trade_signals WHERE id = ?', (signal_id,))
            
            result.update({
                'success': True,
                'message': '交易信号已取消'
            })
            
        except Exception as e:
            logging.error(f"取消交易信号失败: {e}")
            result['message'] = f'取消失败: {str(e)}'
        
        return result
    
    def get_signal_details(self, signal_id: int) -> Optional[Dict[str, Any]]:
        """获取信号详情"""
        try:
            signal_data = self.db_manager.execute_query('''
                SELECT ts.id, ts.stock_id, ts.signal_type, ts.signal_price,
                       ts.target_price, ts.stop_loss_price, ts.condition_text,
                       ts.is_executed, ts.executed_time, ts.created_at,
                       s.code, s.name
                FROM trade_signals ts
                JOIN stocks s ON ts.stock_id = s.id
                WHERE ts.id = ?
            ''', (signal_id,))
            
            if signal_data:
                (sig_id, stock_id, signal_type, signal_price,
                 target_price, stop_loss_price, condition_text,
                 is_executed, executed_time, created_at,
                 stock_code, stock_name) = signal_data[0]
                return {
                    'id': sig_id,
                    'stock_id': stock_id,
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'signal_type': signal_type,
                    'signal_price': signal_price,
                    'target_price': target_price,
                    'stop_loss_price': stop_loss_price,
                    'condition_text': condition_text,
                    'is_executed': bool(is_executed),
                    'executed_time': executed_time,
                    'created_at': created_at
                }
                
        except Exception as e:
            logging.error(f"获取信号详情失败: {e}")
        
        return None
