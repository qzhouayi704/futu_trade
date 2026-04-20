"""
Scalping 子进程入口

在独立进程中运行完整的 ScalpingEngine，拥有独立的：
- asyncio 事件循环
- FutuClient 连接
- CentralScheduler 数据轮询
- 全部计算器和检测器

与主进程通过 multiprocessing.Queue 通信：
- cmd_queue (主→子): start/stop/snapshot 等命令
- event_queue (子→主): socket 事件转发
"""

import asyncio
import logging
import os
import sys
import threading
import time
from multiprocessing import Queue
from typing import Optional

logger = logging.getLogger("scalping.worker")


class QueueSocketProxy:
    """Socket 代理 - 将 emit 调用序列化后放入 Queue 传给主进程

    替代真实 SocketManager，子进程中的所有计算器/检测器通过此代理
    发送 WebSocket 事件，主进程从 event_queue 读取后转发到真实 SocketIO。
    """

    def __init__(self, event_queue: Queue):
        self._queue = event_queue

    async def emit_to_all(self, event: str, data: dict):
        """广播事件（兼容 SocketManager 接口）"""
        try:
            # 处理 enum 类型
            event_name = event.value if hasattr(event, 'value') else str(event)
            self._queue.put_nowait({
                "type": "socket_event",
                "event": event_name,
                "data": data,
            })
        except Exception as e:
            logger.error(f"事件序列化失败: {event_name}, 错误: {e}", exc_info=True)
            # 尝试发送降级事件
            try:
                self._queue.put_nowait({
                    "type": "socket_event",
                    "event": "scalping_error",
                    "data": {"error": f"事件序列化失败: {event_name}"}
                })
            except:
                pass

    async def emit_to_client(self, sid: str, event: str, data: dict):
        """单播事件（子进程中不支持，静默忽略）"""
        pass

    async def emit_error(self, sid: str, error_message: str, error_code: str = ""):
        """错误事件（子进程中不支持，静默忽略）"""
        pass


def _init_scalping_engine(config_dict: dict, socket_proxy: QueueSocketProxy, event_queue: Queue):
    """在子进程中初始化完整的 ScalpingEngine

    Args:
        config_dict: 配置字典（从主进程序列化传入）
        socket_proxy: QueueSocketProxy 实例
        event_queue: 事件队列

    Returns:
        (engine, futu_client) 元组
    """
    from simple_trade.config.config import ConfigManager
    from simple_trade.api.futu_client import FutuClient
    from simple_trade.api.subscription_manager import SubscriptionManager
    from simple_trade.database.core.db_manager import DatabaseManager
    from simple_trade.services.scalping import (
        ScalpingEngine,
        DeltaCalculator,
        TapeVelocityMonitor,
        SpoofingFilter,
        POCCalculator,
        SignalEngine,
        OrderFlowDivergenceDetector,
        BreakoutSurvivalMonitor,
        VwapExtensionGuard,
        TickCredibilityFilter,
    )
    from simple_trade.services.scalping.persistence import ScalpingPersistence
    from simple_trade.services.scalping.calculators.ofi_calculator import OFICalculator
    from simple_trade.services.scalping.detectors.pattern_detector import PatternDetector
    from simple_trade.services.scalping.detectors.action_scorer import ActionScorer

    try:
        from simple_trade.services.scalping import StopLossMonitor
    except ImportError:
        StopLossMonitor = None

    # 加载配置
    config = ConfigManager.load_config("simple_trade/config.json")

    # 独立数据库连接（不需要 init_database，主进程已创建表结构）
    logger.info("[Scalping子进程] 正在初始化数据库连接...")
    db_manager = DatabaseManager(config.database_path)
    logger.info("[Scalping子进程] 数据库连接完成")

    # 独立富途连接
    logger.info("[Scalping子进程] 正在连接 FutuClient...")
    futu_client = FutuClient(
        host=config.futu_host,
        port=config.futu_port,
    )
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        if futu_client.connect():
            logger.info(f"[Scalping子进程] FutuClient 连接成功")
            break
        logger.warning(f"[Scalping子进程] FutuClient 连接失败 ({attempt}/{max_retries})")
        time.sleep(5)
    else:
        raise RuntimeError("Scalping子进程无法连接 FutuOpenD")

    # 订阅管理器
    subscription_manager = SubscriptionManager(
        futu_client, db_manager=db_manager, config=config
    )

    # 持久化
    persistence = ScalpingPersistence(db_manager=db_manager)

    # 计算器（全部使用 socket_proxy 替代真实 SocketManager）
    delta_calculator = DeltaCalculator(socket_manager=socket_proxy, persistence=persistence)
    tape_velocity = TapeVelocityMonitor(socket_manager=socket_proxy)
    spoofing_filter = SpoofingFilter(socket_manager=socket_proxy, persistence=persistence)
    poc_calculator = POCCalculator(socket_manager=socket_proxy, persistence=persistence)
    logger.info("[Scalping子进程] 计算器创建完成: DeltaCalculator, TapeVelocityMonitor, SpoofingFilter, POCCalculator")

    # 检测器
    tick_credibility_filter = TickCredibilityFilter(socket_manager=socket_proxy)
    divergence_detector = OrderFlowDivergenceDetector(
        socket_manager=socket_proxy, delta_calculator=delta_calculator,
    )
    breakout_monitor = BreakoutSurvivalMonitor(
        socket_manager=socket_proxy, tape_velocity=tape_velocity,
        spoofing_filter=spoofing_filter,
    )
    vwap_guard = VwapExtensionGuard(socket_manager=socket_proxy)
    logger.info("[Scalping子进程] 检测器创建完成: TickCredibilityFilter, OrderFlowDivergenceDetector, BreakoutSurvivalMonitor, VwapExtensionGuard")

    # 注入持久化
    tape_velocity._persistence = persistence
    tick_credibility_filter._persistence = persistence
    divergence_detector._persistence = persistence
    breakout_monitor._persistence = persistence
    vwap_guard._persistence = persistence

    # OFI + 信号引擎
    ofi_calculator = OFICalculator()
    signal_engine = SignalEngine(
        socket_manager=socket_proxy,
        delta_calculator=delta_calculator,
        tape_velocity=tape_velocity,
        spoofing_filter=spoofing_filter,
        poc_calculator=poc_calculator,
        vwap_guard=vwap_guard,
        ofi_calculator=ofi_calculator,
        persistence=persistence,
    )
    logger.info("[Scalping子进程] SignalEngine 创建完成")

    stop_loss_monitor = StopLossMonitor(socket_manager=socket_proxy) if StopLossMonitor else None
    logger.info(f"[Scalping子进程] StopLossMonitor: {'已创建' if stop_loss_monitor else '未加载'}")

    # 不需要 subscription_helper（子进程通过 CentralScheduler 自行轮询）
    # 使用 None 占位，lifecycle_manager 中的订阅逻辑由主进程管理
    from simple_trade.services.realtime.realtime_query import RealtimeQuery
    realtime_query = RealtimeQuery(futu_client=futu_client, db_manager=db_manager)

    engine = ScalpingEngine(
        subscription_helper=None,  # 子进程不管理订阅
        realtime_query=realtime_query,
        socket_manager=socket_proxy,
        delta_calculator=delta_calculator,
        tape_velocity=tape_velocity,
        spoofing_filter=spoofing_filter,
        poc_calculator=poc_calculator,
        signal_engine=signal_engine,
        tick_credibility_filter=tick_credibility_filter,
        divergence_detector=divergence_detector,
        breakout_monitor=breakout_monitor,
        vwap_guard=vwap_guard,
        stop_loss_monitor=stop_loss_monitor,
        futu_client=futu_client,
        persistence=persistence,
        state_manager=None,  # 子进程不需要 StateManager
        subscription_manager=subscription_manager,
    )

    # 注入额外组件
    engine._pattern_detector = PatternDetector()
    engine._action_scorer = ActionScorer()
    engine._ofi_calculator = ofi_calculator

    return engine, futu_client, subscription_manager


async def _run_worker(cmd_queue: Queue, event_queue: Queue, config_dict: dict):
    """子进程的异步主循环"""
    logger.info("[Scalping子进程] 启动中...")

    engine, futu_client, subscription_manager = _init_scalping_engine(
        config_dict, QueueSocketProxy(event_queue), event_queue
    )

    # 通知主进程初始化完成
    event_queue.put({"type": "worker_ready"})
    logger.info("[Scalping子进程] 初始化完成，等待命令...")

    _HEARTBEAT_INTERVAL = 30.0  # 每 30 秒发送一次心跳

    # 用独立守护线程发送心跳，与命令处理完全解耦
    # 避免同步阻塞调用（如 subscribe_multi_types）冻结事件循环导致心跳中断
    _heartbeat_stop = threading.Event()

    def _heartbeat_sender(eq: Queue, interval: float, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                eq.put_nowait({"type": "heartbeat"})
            except Exception:
                pass
            stop_event.wait(timeout=interval)

    _hb_thread = threading.Thread(
        target=_heartbeat_sender,
        args=(event_queue, _HEARTBEAT_INTERVAL, _heartbeat_stop),
        daemon=True,
        name="scalping-heartbeat",
    )
    _hb_thread.start()

    try:
        while True:
            # 非阻塞检查命令队列
            try:
                cmd = cmd_queue.get_nowait()
            except Exception:
                cmd = None

            if cmd is not None:
                cmd_type = cmd.get("cmd")
                logger.info(f"[Scalping子进程] 收到命令: {cmd_type}")

                if cmd_type == "start":
                    stocks = cmd.get("stocks", [])
                    turnover_rates = cmd.get("turnover_rates")
                    cmd_id = cmd.get("cmd_id")  # ✅ 获取 cmd_id

                    # 子进程通过自己的 FutuClient 连接订阅 TICKER + ORDER_BOOK
                    # 频率控制由 SubscriptionManager._subscribe_by_type() 内置处理
                    if stocks and subscription_manager:
                        try:
                            from futu import SubType
                            sub_result = subscription_manager.subscribe_multi_types(
                                stocks, [SubType.TICKER, SubType.ORDER_BOOK]
                            )
                            ticker_ok = len(sub_result['by_type'].get('TICKER', {}).get('success', []))
                            ob_ok = len(sub_result['by_type'].get('ORDER_BOOK', {}).get('success', []))
                            logger.info(
                                f"[Scalping子进程] 订阅完成: TICKER {ticker_ok} 只, ORDER_BOOK {ob_ok} 只"
                            )
                        except Exception as sub_err:
                            logger.error(f"[Scalping子进程] 订阅失败: {sub_err}")

                    try:
                        result = await engine.start(stocks, turnover_rates)
                        logger.info(f"[Scalping子进程] start 执行完成: added={len(result.added)}, filtered={len(result.filtered)}")
                        event_queue.put({
                            "type": "cmd_result",
                            "cmd": "start",
                            "cmd_id": cmd_id,  # ✅ 回传 cmd_id
                            "result": {
                                "added": result.added,
                                "existing": result.existing,
                                "filtered": result.filtered,
                            },
                        })
                    except Exception as e:
                        logger.error(f"[Scalping子进程] start 执行失败: {e}", exc_info=True)
                        event_queue.put({
                            "type": "cmd_result",
                            "cmd": "start",
                            "cmd_id": cmd_id,  # ✅ 回传 cmd_id
                            "error": str(e),
                        })

                elif cmd_type == "stop":
                    stocks = cmd.get("stocks")
                    cmd_id = cmd.get("cmd_id")  # ✅ 获取 cmd_id
                    logger.info(f"[Scalping子进程] 执行 stop: {stocks or '全部'}")
                    await engine.stop(stocks)
                    logger.info(f"[Scalping子进程] stop 执行完成")
                    event_queue.put({
                        "type": "cmd_result",
                        "cmd": "stop",
                        "cmd_id": cmd_id  # ✅ 回传 cmd_id
                    })

                elif cmd_type == "snapshot":
                    stock = cmd.get("stock")
                    reply_id = cmd.get("reply_id")
                    logger.info(f"[Scalping子进程] 执行 snapshot: stock={stock}, reply_id={reply_id}")
                    snapshot = await engine.get_snapshot(stock)
                    event_queue.put({
                        "type": "snapshot_reply",
                        "reply_id": reply_id,
                        "data": snapshot,
                    })
                    logger.info(f"[Scalping子进程] snapshot 执行完成: stock={stock}")

                elif cmd_type == "status":
                    logger.info("[Scalping子进程] 执行 status 查询")
                    status = engine.get_status()
                    event_queue.put({
                        "type": "cmd_result",
                        "cmd": "status",
                        "result": status,
                    })
                    logger.info(f"[Scalping子进程] status 执行完成: {len(status) if isinstance(status, dict) else 'N/A'} 项")

                elif cmd_type == "shutdown":
                    logger.info("[Scalping子进程] 收到 shutdown 命令")
                    await engine.stop()
                    break

            await asyncio.sleep(0.1)  # 100ms 命令轮询间隔

    except KeyboardInterrupt:
        logger.info("[Scalping子进程] KeyboardInterrupt")
    except Exception as e:
        import traceback
        logger.error(f"[Scalping子进程] 异常: {e}", exc_info=True)
        event_queue.put({
            "type": "worker_error",
            "error": str(e),
            "traceback": traceback.format_exc()  # ✅ 完整堆栈
        })
    finally:
        _heartbeat_stop.set()  # 通知心跳线程退出
        try:
            await engine.stop()
        except Exception:
            pass
        try:
            futu_client.disconnect()
        except Exception:
            pass
        logger.info("[Scalping子进程] 已退出")


def scalping_worker_main(cmd_queue: Queue, event_queue: Queue, config_dict: dict):
    """子进程入口函数（由 multiprocessing.Process 调用）

    Args:
        cmd_queue: 命令队列（主进程 → 子进程）
        event_queue: 事件队列（子进程 → 主进程）
        config_dict: 配置字典
    """
    # 设置子进程的项目路径
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 加载环境变量
    from dotenv import load_dotenv
    load_dotenv(os.path.join(project_root, '.env'))

    # 配置日志（复用项目的 setup_logging，确保 UTF-8 编码）
    from simple_trade.utils.logger import setup_logging
    log_dir = os.path.join(project_root, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    setup_logging(
        log_file=os.path.join(log_dir, 'scalping_worker.log'),
        log_level='INFO',
        console_level='WARNING',
    )

    # 运行异步主循环
    asyncio.run(_run_worker(cmd_queue, event_queue, config_dict))
