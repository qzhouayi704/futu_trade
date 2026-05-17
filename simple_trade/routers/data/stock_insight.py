#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个股深度分析 API 路由

POST /api/stock-insight/analyze  → 技术面+资金面+信号整合（<1秒）
POST /api/stock-insight/news     → 消息面 Gemini 搜索（~7秒）
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...dependencies import get_container
from ...services.analysis.stock_insight_service import StockInsightService
from ...services.analysis.stock_news_search import StockNewsSearchService

logger = logging.getLogger("stock_insight_router")
router = APIRouter(prefix="/api/stock-insight", tags=["个股深度分析"])


class AnalyzeRequest(BaseModel):
    stock_code: str
    # 前端可传入已有的 QuickScan 和操盘规则数据，避免重复请求
    quick_scan_result: Optional[dict] = None
    flow_signals: Optional[list] = None


class NewsRequest(BaseModel):
    stock_code: str
    stock_name: str


@router.post("/analyze")
async def analyze_stock(req: AnalyzeRequest, container=Depends(get_container)):
    """技术面+资金面+信号整合分析（<1秒）"""
    db_manager = getattr(container, "db_manager", None)
    if not db_manager:
        return {"success": False, "message": "数据库不可用"}

    try:
        service = StockInsightService(db_manager)
        result = service.analyze(
            stock_code=req.stock_code,
            quick_scan_result=req.quick_scan_result,
            flow_signals=req.flow_signals,
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"深度分析失败 {req.stock_code}: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


@router.post("/news")
async def search_news(req: NewsRequest, container=Depends(get_container)):
    """消息面搜索（~7秒，Gemini + Google Search）"""
    config = getattr(container, "config", None)
    gemini_config = getattr(config, "gemini", None) if config else None

    api_key = getattr(gemini_config, "api_key", None) if gemini_config else None
    if not api_key:  # None 或空字符串
        import os
        api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        # 最终 fallback: 直接读 config.json
        try:
            import json, os
            cfg_path = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            api_key = cfg.get("gemini", {}).get("api_key", "")
            logger.info(f"从 config.json 直接读取 gemini api_key (len={len(api_key)})")
        except Exception:
            pass

    if not api_key:
        return {"success": False, "message": "Gemini API Key 未配置"}

    try:
        model = getattr(gemini_config, "model", None) if gemini_config else None
        if not model:
            model = "gemini-2.5-flash"
        use_vertexai = getattr(gemini_config, 'vertexai', False) if gemini_config else False

        # Vertex AI 模式：config 的 api_key 是 GCP 绑定 key，不能用于标准模式降级
        # 从环境变量获取标准 Gemini API Key 作为降级备选
        fallback_key = api_key
        if use_vertexai:
            import os
            std_key = os.environ.get("GEMINI_API_KEY", "")
            if std_key:
                fallback_key = std_key

        service = StockNewsSearchService(
            api_key=fallback_key,
            model=model,
            vertexai=use_vertexai,
            project=getattr(gemini_config, 'project', None) if gemini_config else None,
            location=getattr(gemini_config, 'location', None) if gemini_config else None,
        )
        result = await service.search(req.stock_code, req.stock_name)

        if result.get("error"):
            return {"success": False, "message": result["error"], "data": result}

        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"消息面搜索失败 {req.stock_code}: {e}", exc_info=True)
        return {"success": False, "message": str(e)}
