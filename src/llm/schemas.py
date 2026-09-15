"""LLM 层的数据模型与异常。

异常与 docs/contracts.md 第 5 节的错误码对应：

===============  ===========
异常              错误码
===============  ===========
LLMTimeoutError   llm_timeout
LLMProviderError  llm_error
===============  ===========
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class Message:
    """一条对话消息。上层拼好之后交给 router，router 不关心上下文策略。"""

    role: Role
    content: str

    def to_payload(self) -> dict[str, str]:
        """转成 LiteLLM 接受的字典形式。"""
        return {"role": self.role, "content": self.content}


class LLMError(Exception):
    """LLM 层所有异常的基类。上层只需要捕获这一个。"""

    code: str = "llm_error"


class LLMTimeoutError(LLMError):
    """请求超时。对应的错误码是 llm_timeout。"""

    code = "llm_timeout"


class LLMProviderError(LLMError):
    """Provider 返回错误，或者根本连不上。对应的错误码是 llm_error。"""

    code = "llm_error"
