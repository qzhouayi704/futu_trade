"""LLM 客户端封装层。

统一 Claude 调用入口，替代散落在各处的 Gemini wrapper 与 urllib OpenAI-shim。
"""
from .claude_analyst import ClaudeAnalystClient, build_claude_client_from_env

__all__ = ["ClaudeAnalystClient", "build_claude_client_from_env"]
