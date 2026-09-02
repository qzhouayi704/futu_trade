"""Read-only V2 cockpit, decision and outcome endpoints."""

import logging

from fastapi import APIRouter, Depends, Query

from ...dependencies import get_container
from ...schemas.common import APIResponse
from ...v2.application.read_models import V2ReadModelService


router = APIRouter(prefix="/api/v2", tags=["V2交易工作台"])
logger = logging.getLogger("router.v2.read_models")


def _service(container) -> V2ReadModelService:
    return V2ReadModelService(
        container.db_manager,
        runtime=getattr(container, "v2_runtime", None),
    )


async def _respond(operation, success_message: str) -> APIResponse:
    try:
        return APIResponse(success=True, data=await operation(), message=success_message)
    except Exception as error:  # noqa: BLE001
        logger.exception("V2 read model failed: %s", success_message)
        return APIResponse(success=False, data=None, message=f"V2读取失败: {error}")


@router.get("/cockpit", response_model=APIResponse)
async def get_cockpit(container=Depends(get_container)):
    service = _service(container)
    return await _respond(service.cockpit, "V2驾驶舱读取成功")


@router.get("/candidates", response_model=APIResponse)
async def get_candidates(
    limit: int = Query(default=50, ge=1, le=200),
    container=Depends(get_container),
):
    service = _service(container)
    return await _respond(lambda: service.candidates(limit=limit), "V2候选池读取成功")


@router.get("/candidates/history", response_model=APIResponse)
async def get_candidate_history(
    trade_date: str | None = Query(default=None),
    scope: str = Query(default="entered", pattern="^(entered|all)$"),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    container=Depends(get_container),
):
    service = _service(container)
    return await _respond(
        lambda: service.candidate_history(
            trade_date=trade_date,
            scope=scope,
            status=status,
            search=search,
            page=page,
            page_size=page_size,
        ),
        "V2今日候选记录读取成功",
    )


@router.get("/candidates/{stock_code}/timeline", response_model=APIResponse)
async def get_candidate_timeline(
    stock_code: str,
    trade_date: str | None = Query(default=None),
    container=Depends(get_container),
):
    service = _service(container)
    return await _respond(
        lambda: service.candidate_timeline(stock_code, trade_date=trade_date),
        "V2候选轨迹读取成功",
    )


@router.get("/candidates/{stock_code}", response_model=APIResponse)
async def get_candidate(stock_code: str, container=Depends(get_container)):
    service = _service(container)
    return await _respond(
        lambda: service.candidates(limit=1, stock_code=stock_code),
        "V2候选明细读取成功",
    )


@router.get("/positions", response_model=APIResponse)
async def get_positions(container=Depends(get_container)):
    service = _service(container)
    return await _respond(service.positions, "V2持仓效率读取成功")


@router.get("/decisions", response_model=APIResponse)
async def get_decisions(
    limit: int = Query(default=100, ge=1, le=500),
    container=Depends(get_container),
):
    service = _service(container)
    return await _respond(lambda: service.decisions(limit=limit), "V2决策流读取成功")


@router.get("/decisions/{event_id}", response_model=APIResponse)
async def get_decision(event_id: str, container=Depends(get_container)):
    service = _service(container)
    return await _respond(
        lambda: service.decisions(limit=1, event_id=event_id),
        "V2决策明细读取成功",
    )


@router.get("/outcomes/distribution", response_model=APIResponse)
async def get_outcome_distribution(container=Depends(get_container)):
    service = _service(container)
    return await _respond(service.outcome_distribution, "V2收益分布读取成功")


@router.get("/outcomes/alert-performance", response_model=APIResponse)
async def get_alert_performance(
    trade_date: str | None = Query(default=None),
    scope: str = Query(default="candidates", pattern="^(candidates|watching|alerts)$"),
    container=Depends(get_container),
):
    service = _service(container)
    return await _respond(
        lambda: service.alert_performance(trade_date=trade_date, scope=scope),
        "V2预警后续表现读取成功",
    )


@router.get("/outcomes/shadow-acceptance", response_model=APIResponse)
async def get_shadow_acceptance(
    days: int = Query(default=10, ge=1, le=60),
    container=Depends(get_container),
):
    service = _service(container)
    return await _respond(
        lambda: service.shadow_acceptance(days=days),
        "V2影子验收读取成功",
    )


@router.get("/system/health", response_model=APIResponse)
async def get_health(container=Depends(get_container)):
    service = _service(container)
    return await _respond(service.health, "V2健康状态读取成功")


@router.get("/system/runtime", response_model=APIResponse)
async def get_runtime(container=Depends(get_container)):
    service = _service(container)
    return await _respond(service.runtime, "V2运行状态读取成功")
