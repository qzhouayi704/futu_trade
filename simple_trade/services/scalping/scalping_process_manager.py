"""
Scalping 进程管理器 - 主进程侧的代理

提供与 ScalpingEngine 完全兼容的接口，内部通过 multiprocessing.Queue
与 Scalping 子进程通信。路由层代码零修改。

用法:
    manager = ScalpingProcessManager(config)
    await manager.spawn()        # 启动子进程
    await manager.start(stocks)  # 发送 start 命令
    snapshot = await manager.get_snapshot("HK.00700")
    await manager.shutdown()     # 终止子进程
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from multiprocessing import Process, Queue
from typing import Any, Optional

logger = logging.getLogger("scalping.process_manager")


@dataclass
class StartResult:
    """start() 方法的结构化返回结果（兼容 ScalpingEngine.StartResult）"""
    added: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    filtered: list[str] = field(default_factory=list)
    rejected_reason: str | None = None


class ScalpingProcessManager:
    """主进程中的 Scalping 代理，管理子进程生命周期并转发事件"""

    def __init__(self, config_dict: dict | None = None, process_config=None):
        """初始化进程管理器

        Args:
            config_dict: 传递给子进程的配置字典（可选）
            process_config: ScalpingProcessConfig 实例（可选，用于超时配置）
        """
        self._config_dict = config_dict or {}
        self._process: Optional[Process] = None
        self._cmd_queue: Optional[Queue] = None
        self._event_queue: Optional[Queue] = None
        self._relay_task: Optional[asyncio.Task] = None
        self._socket_manager = None  # 由 app.py 注入
        self._ready = asyncio.Event()
        self._pending_snapshots: dict[str, asyncio.Future] = {}
        self._pending_commands: dict[str, asyncio.Future] = {}

        # 兼容 ScalpingEngine 的状态属性
        self._active_stocks: set[str] = set()
        self._day_highs: dict[str, float] = {}

        # 从配置读取超时和心跳参数（有默认值）
        cfg = process_config
        self._spawn_timeout: float = cfg.spawn_timeout if cfg else 60.0
        self._start_timeout: float = cfg.start_timeout if cfg else 30.0
        self._stop_timeout: float = cfg.stop_timeout if cfg else 5.0
        self._snapshot_timeout: float = cfg.snapshot_timeout if cfg else 5.0
        self._heartbeat_interval: float = cfg.heartbeat_interval if cfg else 30.0
        self._heartbeat_timeout: float = cfg.heartbeat_timeout if cfg else 60.0
        self._max_restarts: int = cfg.max_restarts if cfg else 3

        # 心跳和自动重启运行时状态
        self._last_heartbeat: float = 0
        self._restart_count: int = 0

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def spawn(self, socket_manager=None):
        """启动 Scalping 子进程

        Args:
            socket_manager: 真实的 SocketManager，用于转发子进程事件
        """
        if self._process and self._process.is_alive():
            logger.warning("Scalping 子进程已在运行")
            return

        self._socket_manager = socket_manager
        self._cmd_queue = Queue()
        self._event_queue = Queue()
        self._ready.clear()

        from simple_trade.services.scalping.scalping_worker import scalping_worker_main

        self._process = Process(
            target=scalping_worker_main,
            args=(self._cmd_queue, self._event_queue, self._config_dict),
            name="ScalpingWorker",
            daemon=True,
        )
        self._process.start()
        import time
        self._last_heartbeat = time.time()  # 启动时记录心跳基准
        logger.info(f"Scalping 子进程已启动 (PID: {self._process.pid})")

        # 启动事件中继循环（含心跳检测）
        self._relay_task = asyncio.create_task(
            self._event_relay_loop(), name="scalping_relay"
        )

        # 等待子进程就绪（使用配置的超时）
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self._spawn_timeout)
            logger.info("Scalping 子进程初始化完成")
        except asyncio.TimeoutError:
            logger.error(f"Scalping 子进程初始化超时({self._spawn_timeout}s)")

    async def shutdown(self):
        """终止 Scalping 子进程"""
        if not self._process:
            return

        # 发送 shutdown 命令
        try:
            self._cmd_queue.put({"cmd": "shutdown"})
        except Exception:
            pass

        # 等待子进程退出（最多 5 秒）
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._process.join, 5.0
            )
        except Exception:
            pass

        if self._process.is_alive():
            logger.warning("Scalping 子进程未响应 shutdown，强制终止")
            self._process.terminate()
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._process.join, 2.0
                )
            except Exception:
                pass

        # 取消中继任务
        if self._relay_task and not self._relay_task.done():
            self._relay_task.cancel()
            try:
                await self._relay_task
            except (asyncio.CancelledError, Exception):
                pass

        self._process = None
        logger.info("Scalping 子进程已终止")

    # ------------------------------------------------------------------
    # 兼容 ScalpingEngine 的接口
    # ------------------------------------------------------------------

    async def start(
        self,
        stock_codes: list[str],
        turnover_rates: dict[str, float] | None = None,
    ) -> StartResult:
        """启动指定股票的 Scalping 数据流"""
        if not self._process or not self._process.is_alive():
            return StartResult(rejected_reason="Scalping 子进程未运行")

        cmd_id = f"start_{uuid.uuid4().hex[:8]}"
        self._cmd_queue.put({
            "cmd": "start",
            "cmd_id": cmd_id,  # ✅ 添加 cmd_id
            "stocks": stock_codes,
            "turnover_rates": turnover_rates,
        })

        # 等待结果（分批订阅约需 5s + 引擎启动，使用配置的超时）
        result = await self._wait_cmd_result(cmd_id, timeout=self._start_timeout)
        if result:
            sr = StartResult(
                added=result.get("added", []),
                existing=result.get("existing", []),
                filtered=result.get("filtered", []),
            )
            # 根据实际结果更新 active_stocks（而非乐观更新）
            self._active_stocks.update(sr.added)
            self._active_stocks.update(sr.existing)
            return sr
        # 超时时回退到乐观更新
        self._active_stocks.update(stock_codes)
        return StartResult(added=stock_codes)

    async def stop(self, stock_codes: list[str] | None = None) -> None:
        """停止指定股票（或全部）的 Scalping 数据流"""
        if not self._process or not self._process.is_alive():
            return

        cmd_id = f"stop_{uuid.uuid4().hex[:8]}"
        self._cmd_queue.put({
            "cmd": "stop",
            "cmd_id": cmd_id,  # ✅ 添加 cmd_id
            "stocks": stock_codes
        })
        if stock_codes:
            self._active_stocks -= set(stock_codes)
        else:
            self._active_stocks.clear()

        await self._wait_cmd_result(cmd_id, timeout=self._stop_timeout)

    async def get_snapshot(self, stock_code: str) -> dict | None:
        """获取指定股票的 Scalping 数据快照"""
        if not self._process or not self._process.is_alive():
            return None

        reply_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending_snapshots[reply_id] = future

        self._cmd_queue.put({
            "cmd": "snapshot",
            "stock": stock_code,
            "reply_id": reply_id,
        })

        try:
            return await asyncio.wait_for(future, timeout=self._snapshot_timeout)
        except asyncio.TimeoutError:
            logger.warning(f"快照请求超时: {stock_code} ({self._snapshot_timeout}s)")
            return None
        finally:
            self._pending_snapshots.pop(reply_id, None)

    def get_status(self) -> dict:
        """返回引擎状态（含心跳、重启次数）"""
        import time
        alive = self._process.is_alive() if self._process else False
        heartbeat_age = round(time.time() - self._last_heartbeat, 1) if self._last_heartbeat else None
        return {
            "mode": "process",
            "process_alive": alive,
            "process_pid": self._process.pid if self._process else None,
            "active_stocks": list(self._active_stocks),
            "active_count": len(self._active_stocks),
            "restart_count": self._restart_count,
            "max_restarts": self._max_restarts,
            "last_heartbeat_secs_ago": heartbeat_age,
            "heartbeat_timeout": self._heartbeat_timeout,
        }

    @property
    def active_stocks(self) -> set[str]:
        return self._active_stocks

    @property
    def day_highs(self) -> dict[str, float]:
        return self._day_highs

    # ------------------------------------------------------------------
    # 内部：事件中继
    # ------------------------------------------------------------------

    async def _event_relay_loop(self):
        """后台任务：从 event_queue 读取事件，转发到真实 SocketManager，含心跳检测"""
        import time
        loop = asyncio.get_running_loop()

        while True:
            try:
                # 在线程池中阻塞读取 Queue（避免阻塞事件循环）
                msg = await loop.run_in_executor(
                    None, self._event_queue_get_with_timeout
                )

                # 心跳超时检测（每次 Queue 读取后检查）
                if self._process and self._process.is_alive():
                    elapsed = time.time() - self._last_heartbeat
                    if elapsed > self._heartbeat_timeout:
                        logger.warning(
                            f"Scalping 子进程心跳超时 ({elapsed:.0f}s > {self._heartbeat_timeout}s)，尝试重启"
                        )
                        await self._restart_worker()
                        continue
                elif self._process and not self._process.is_alive():
                    logger.error(f"Scalping 子进程意外退出 (exitcode={self._process.exitcode})")
                    await self._restart_worker()
                    continue

                if msg is None:
                    continue

                msg_type = msg.get("type")

                if msg_type == "worker_ready":
                    self._last_heartbeat = time.time()
                    self._ready.set()

                elif msg_type == "heartbeat":
                    self._last_heartbeat = time.time()
                    logger.debug("Scalping 子进程心跳")

                elif msg_type == "socket_event":
                    # 转发到真实 SocketManager
                    if self._socket_manager:
                        try:
                            await self._socket_manager.emit_to_all(
                                msg["event"], msg["data"]
                            )
                        except Exception as e:
                            logger.debug(f"事件转发失败: {e}")

                elif msg_type == "cmd_result":
                    cmd = msg.get("cmd", "")
                    cmd_id = msg.get("cmd_id", cmd)
                    future = self._pending_commands.get(cmd_id)
                    if future and not future.done():
                        future.set_result(msg.get("result"))

                elif msg_type == "snapshot_reply":
                    reply_id = msg.get("reply_id")
                    future = self._pending_snapshots.get(reply_id)
                    if future and not future.done():
                        future.set_result(msg.get("data"))

                elif msg_type == "worker_error":
                    error_msg = msg.get('error')
                    traceback_info = msg.get('traceback', '')
                    if traceback_info:
                        logger.error(f"Scalping 子进程错误: {error_msg}\n{traceback_info}")
                    else:
                        logger.error(f"Scalping 子进程错误: {error_msg}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"事件中继异常: {e}")
                await asyncio.sleep(0.5)

    async def _restart_worker(self):
        """重启子进程并恢复监控股票"""
        if self._restart_count >= self._max_restarts:
            logger.error(
                f"Scalping 子进程已重启 {self._restart_count} 次，超过上限 {self._max_restarts}，停止重启"
            )
            # 尝试发送企业微信告警
            try:
                from simple_trade.services.alert.wechat_alert import WeChatAlertService
                wechat = WeChatAlertService()
                asyncio.create_task(wechat.send_text(
                    f"【Scalping告警】子进程已重启 {self._restart_count} 次，超过上限，请手动检查！"
                ))
            except Exception:
                pass
            return

        stocks_to_restore = list(self._active_stocks)
        self._restart_count += 1
        logger.warning(
            f"正在重启 Scalping 子进程（第 {self._restart_count}/{self._max_restarts} 次）"
            f"，将恢复 {len(stocks_to_restore)} 只股票"
        )

        # 清理旧进程
        if self._process and self._process.is_alive():
            self._process.terminate()
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self._process.join, 3.0
                )
            except Exception:
                pass

        self._process = None
        self._active_stocks.clear()

        # 重新 spawn
        await self.spawn(self._socket_manager)

        # 恢复监控股票
        if stocks_to_restore:
            logger.info(f"恢复监控股票: {stocks_to_restore}")
            await self.start(stocks_to_restore)

    def _event_queue_get_with_timeout(self) -> Optional[dict]:
        """带超时的 Queue.get（在线程池中调用）"""
        try:
            return self._event_queue.get(timeout=0.5)
        except Exception:
            return None

    async def _wait_cmd_result(self, cmd_id: str, timeout: float = 5) -> Optional[Any]:
        """等待命令执行结果（使用 cmd_id 精确匹配）"""
        future = asyncio.get_running_loop().create_future()
        self._pending_commands[cmd_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"等待命令结果超时 (cmd_id={cmd_id}, timeout={timeout}s)")
            return None
        finally:
            self._pending_commands.pop(cmd_id, None)
