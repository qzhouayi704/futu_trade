"""官方 anthropic SDK 封装：统一 Claude 结构化分析入口。

替代散落的两个 Gemini wrapper 和 gemini_analyst 里的 urllib OpenAI-shim。
经第三方 Anthropic 兼容代理(默认 ctok.ai)接入，使用官方 anthropic SDK + base_url + auth_token。

集成特性（均已对代理实测穿透）：
- 结构化输出：output_config.format(json_schema) 强约束返回合法 JSON，消除手工剥 markdown 解析。
- Prompt 缓存：静态 system + 规则知识库作为带 cache_control 的可缓存前缀，命中后输入约 0.1x 价。
- 自适应思考：thinking=adaptive，分析类任务按需深度推理。
- usage 日志：记录输入/缓存读/输出 token，成本可观测。

注：output_config / adaptive thinking 走 extra_body，规避不同 SDK 版本的 typing 差异。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖缺失时优雅降级
    ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_BASE_URL = "https://api.ctok.ai"


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出稳健提取 JSON。

    第三方代理对 output_config.format 仅作软提示（prompt 含围栏指令时模型仍会输出
    ```json 围栏），故需像 Gemini 那条路一样剥围栏；再不行则截取最外层 {...}。
    """
    if not text:
        return None
    s = text.strip()
    if "```json" in s:
        s = s.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in s:
        s = s.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        pass
    # 兜底：截取最外层大括号
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(s[start:end + 1])
        except (json.JSONDecodeError, TypeError):
            return None
    return None


class ClaudeAnalystClient:
    """异步 Claude 分析客户端（官方 SDK）。

    单例复用即可：内部 AsyncAnthropic 线程安全，跨多次 analyze 共享连接与缓存。
    """

    def __init__(
        self,
        auth_token: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 90.0,
        max_retries: int = 3,
        effort: str = "medium",
        thinking: bool = True,
    ):
        self.model = model
        self.effort = effort
        self.thinking = thinking
        self._client = None

        if not ANTHROPIC_AVAILABLE:
            logger.warning("anthropic SDK 未安装，Claude 分析不可用（pip install anthropic）")
            return
        if not auth_token:
            logger.warning("ClaudeAnalystClient 跳过：未配置 auth_token")
            return

        try:
            self._client = anthropic.AsyncAnthropic(
                base_url=base_url or None,
                auth_token=auth_token,
                timeout=float(timeout),
                max_retries=max_retries,
            )
            logger.info(
                f"ClaudeAnalystClient 初始化成功，模型: {model}, base_url: {base_url}, "
                f"effort: {effort}, thinking: {thinking}"
            )
        except Exception as e:  # pragma: no cover
            logger.error(f"ClaudeAnalystClient 初始化失败: {e}")

    def is_available(self) -> bool:
        return self._client is not None

    async def analyze(
        self,
        *,
        system_prompt: str,
        user_content: str,
        schema: Dict[str, Any],
        cached_context: Optional[str] = None,
        label: str = "",
        max_tokens: int = 4096,
    ) -> Optional[Dict[str, Any]]:
        """执行一次结构化分析。

        Args:
            system_prompt: 角色/方法论（静态）。
            user_content: 本次分析的易变数据（行情/资金流等），不缓存。
            schema: JSON Schema，强约束返回结构。
            cached_context: 规则知识库等大块静态文本，与 system_prompt 合并为可缓存前缀。
            label: 日志标识（如股票代码）。
            max_tokens: 输出上限。

        Returns:
            校验过的 dict；失败/被拒绝返回 None。
        """
        if not self.is_available():
            return None

        # 可缓存前缀：静态 system + 规则库合并，打 cache_control 断点（易变数据在 user 消息里）
        system_text = system_prompt
        if cached_context:
            system_text = f"{system_prompt}\n\n{cached_context}"
        system_blocks = [
            {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
        ]

        extra: Dict[str, Any] = {
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            }
        }
        if self.thinking:
            extra["thinking"] = {"type": "adaptive"}

        start = time.time()
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_blocks,
                messages=[{"role": "user", "content": user_content}],
                extra_body=extra,
            )
        except anthropic.APIStatusError as e:
            logger.error(
                f"[Claude]{label} API 错误 {getattr(e, 'status_code', '?')}: "
                f"{getattr(e, 'message', str(e))[:200]}"
            )
            return None
        except anthropic.APIConnectionError as e:
            logger.error(f"[Claude]{label} 连接失败: {e}")
            return None
        except Exception as e:  # pragma: no cover
            logger.error(f"[Claude]{label} 调用异常: {e}", exc_info=True)
            return None

        elapsed = time.time() - start

        if resp.stop_reason == "refusal":
            logger.warning(f"[Claude]{label} 被安全分类器拒绝，耗时 {elapsed:.1f}s")
            return None

        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)

        # usage 日志（成本可观测）
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        logger.info(
            f"[Claude]{label} 完成 ✓ 耗时{elapsed:.1f}s | "
            f"输入{u.input_tokens}(缓存读{cache_read}) 输出{u.output_tokens} | "
            f"stop={resp.stop_reason}"
        )

        if not text:
            logger.error(f"[Claude]{label} 无文本输出（stop={resp.stop_reason}）")
            return None

        data = _extract_json(text)
        if data is None:
            logger.error(f"[Claude]{label} JSON 解析失败, text={text[:200]}")
        return data


def build_claude_client_from_env(
    model: str = DEFAULT_MODEL,
    effort: str = "medium",
    thinking: bool = True,
    timeout: float = 90.0,
    max_retries: int = 3,
) -> Optional[ClaudeAnalystClient]:
    """从环境变量构造客户端。

    读取 ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL（由 .env 经 dotenv 注入）。
    未配置 token 时返回 None（调用方据此回退到 Gemini）。
    """
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip()
    if not token:
        return None
    base_url = os.environ.get("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    client = ClaudeAnalystClient(
        auth_token=token,
        base_url=base_url,
        model=os.environ.get("ANTHROPIC_MODEL", model).strip() or model,
        timeout=timeout,
        max_retries=max_retries,
        effort=effort,
        thinking=thinking,
    )
    return client if client.is_available() else None
