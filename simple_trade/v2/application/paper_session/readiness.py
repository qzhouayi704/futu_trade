"""Preflight checks cannot start capture, mutate configuration or grant live execution."""

from datetime import datetime
import math
from pathlib import Path

from ...domain.capture import BookCaptureConfig
from ...domain.paper_readiness import (
    CapacityAssumptions, CapacityProjection, PaperReadinessReport, ReadinessIssue,
    ReviewAcknowledgements, StorageFacts,
)
from ...domain.paper_session import PaperSessionConfig
from ...domain.serialization import require_aware


def evaluate_readiness(
    paper: PaperSessionConfig, capture: BookCaptureConfig, *, when: datetime,
    expected_strategy_version: str, reviews: ReviewAcknowledgements,
    assumptions: CapacityAssumptions | None, storage: tuple[StorageFacts, StorageFacts],
    isolated_paths: bool, system_free_bytes: int | None,
    protected_stock_count: int = 0,
) -> PaperReadinessReport:
    require_aware(when, "when")
    if type(protected_stock_count) is not int or protected_stock_count < 0:
        raise ValueError("protected stock count must be a nonnegative integer")
    issues: list[ReadinessIssue] = []

    def block(code: str, message: str) -> None:
        issues.append(ReadinessIssue(code, "BLOCKER", message))

    if not isolated_paths:
        block("DATABASE_PATHS_NOT_ISOLATED", "盘口归档、模拟账本和交易主库必须是不同文件，包括软链接和硬链接。")
    if (Path(storage[0].path).resolve() != capture.path.resolve()
            or Path(storage[1].path).resolve() != paper.path.resolve()):
        block("STORAGE_FACTS_MISMATCH", "磁盘探测结果不属于本次配置路径。")
    if not expected_strategy_version.strip() or paper.experiment.strategy_version != expected_strategy_version:
        block("STRATEGY_VERSION_MISMATCH", "实验策略版本与目标运行版本不一致。")
    for key, label in (("schedule", "交易时段"), ("securities", "普通股名单"),
                       ("costs", "费用假设"), ("parameters", "实验参数")):
        if not getattr(reviews, key):
            block(f"REVIEW_REQUIRED_{key.upper()}", f"{label}尚未明确审核，不能把示例当作已确认配置。")
    if system_free_bytes is None or system_free_bytes < 2 * 1024 ** 3:
        block("SYSTEM_DISK_RESERVE_LOW", "系统盘可用空间未知或不足 2 GiB，先确认日志与服务运行空间。")
    if len(paper.experiment.stock_codes) + protected_stock_count > capture.max_stocks:
        block("CAPTURE_TARGET_BUDGET_INSUFFICIENT", "实验名单加真实持仓保护席位超过采集上限；当前按不重叠保守估算。")
    if paper.experiment.policy.max_positions > capture.max_stocks:
        block("PAPER_POSITION_CAPTURE_BUDGET_MISMATCH", "模拟最大持仓数超过盘口采集上限。")

    intervals = [item for item in paper.experiment.intervals if item.closes_at > when]
    if not intervals:
        block("SCHEDULE_EXPIRED", "配置内没有尚未结束的交易时段。")
    elif not any((min(item.closes_at, paper.experiment.exit_at(item.opens_at)) - max(item.opens_at, when)).total_seconds()
                 > paper.experiment.policy.latency_seconds for item in intervals):
        block("NO_VALID_ENTRY_WINDOW", "所配退出提前量或当前时间使剩余时段没有有效入场窗口。")
    if any(item.opens_at < when < item.closes_at for item in intervals):
        issues.append(ReadinessIssue("PARTIAL_SESSION", "WARNING", "当前时段已经开始，只能验收后续覆盖，不能当作完整交易日。"))
    remaining = [(item.closes_at - max(item.opens_at, when)).total_seconds() for item in intervals]
    samples = sum(math.ceil(seconds / capture.sample_interval_seconds) + 1 for seconds in remaining)
    records = samples * capture.max_stocks
    commands = samples * min(len(paper.experiment.stock_codes), capture.max_stocks)
    capture_growth = paper_growth = None
    if assumptions is None:
        block("CAPACITY_ASSUMPTIONS_MISSING", "缺少每条盘口和模拟命令的空间估算，需先完成有界容量测试。")
    else:
        commands += assumptions.extra_commands
        capture_growth = records * assumptions.capture_bytes_per_record
        paper_growth = commands * assumptions.paper_bytes_per_command
    projection = CapacityProjection(sum(remaining), records, commands, capture_growth, paper_growth,
                                    assumptions.source if assumptions else None)

    for facts, label, cap, count_limit, new_records, growth in (
        (storage[0], "盘口归档", capture, capture.max_records, records, capture_growth),
        (storage[1], "模拟账本", paper, paper.max_commands, commands, paper_growth),
    ):
        if facts.blocked_reason or not facts.parent_ready:
            block(facts.blocked_reason or "STORAGE_UNAVAILABLE", f"{label}路径或已有数据库未通过只读检查：{facts.path}")
        if facts.records + new_records > count_limit:
            block("RECORD_BUDGET_INSUFFICIENT", f"{label}预计记录/命令数超过上限，可能在计划时段结束前停止。")
        if facts.file_bytes > cap.max_bytes or (growth is not None and facts.file_bytes + growth > cap.max_bytes):
            block("FILE_BUDGET_INSUFFICIENT", f"{label}预计文件大小超过配置上限；估算并非真实行情体积保证。")

    # Shared filesystem free space is counted once, with full file and journal headroom.
    groups: dict[str, list[tuple[StorageFacts, BookCaptureConfig | PaperSessionConfig]]] = {}
    for facts, cap in zip(storage, (capture, paper)):
        if facts.device is None or facts.free_bytes is None:
            block("DISK_SPACE_UNKNOWN", "无法确定目标文件系统剩余空间。")
        else:
            groups.setdefault(facts.device, []).append((facts, cap))
    for entries in groups.values():
        required = max(cap.min_free_bytes for _, cap in entries) + sum(
            max(0, cap.max_bytes - facts.file_bytes) + cap.max_bytes for facts, cap in entries
        )
        if min(facts.free_bytes for facts, _ in entries) < required:
            block("SHARED_DISK_BUDGET_INSUFFICIENT", "同一文件系统需同时容纳两份数据库、临时日志和保留空间，剩余空间不足。")
    issues.append(ReadinessIssue("LIVE_FEED_NOT_VERIFIED", "WARNING", "预检不验证真实订阅额度、整日负载或盈利能力；人工审核项是声明，不是外部资料核验。"))
    return PaperReadinessReport(when, paper.account_id, paper.experiment.experiment_id,
                               expected_strategy_version, not any(item.level == "BLOCKER" for item in issues),
                               False, projection, storage, tuple(issues))
