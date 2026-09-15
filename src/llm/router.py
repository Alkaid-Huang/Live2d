"""LiteLLM 路由封装。

对外只暴露 ``stream_reply()``，签名与 docs/contracts.md 第 4 节一致：
产出纯文本增量，不带任何 Provider 特有字段。

litellm 的异常全部在这里翻译成本层的异常（见 ``llm.schemas``），不外泄。

测试接缝：模块级 ``_completion`` 引用。测试里把它换成假函数即可，不需要联网。
之所以用模块级引用而不是公开参数，是为了让 ``stream_reply`` 的签名保持干净。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from llm.schemas import LLMError, LLMProviderError, LLMTimeoutError, Message

CompletionFn = Callable[..., Any]

#: 测试替换点。生产路径上是 None，第一次真正调用时才去碰 litellm。
#: 故意不在模块顶层 import litellm：它导入时会联网拉模型价格表（失败还会重试三次），
#: 还可能触发 tiktoken 下载词表。测试不该被这种副作用拖慢，更不该因此失败。
_completion: CompletionFn | None = None

OPENAI_COMPATIBLE_PREFIX = "openai/"


def _default_completion(**payload: Any) -> Any:
    """生产路径：第一次调用时才导入 litellm。"""
    # 用本地打包的价格表，省掉启动时那次联网（以及失败后的重试等待）。
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    import litellm

    return litellm.completion(**payload)


def normalize_model_name(provider: str, model: str) -> str:
    """把配置里的模型名补成 LiteLLM 认识的形式。

    - 已经带前缀的（``openai/gpt-4o``）原样返回
    - ``provider="deepseek"`` + ``deepseek-chat`` → ``deepseek/deepseek-chat``
    - ``provider="openai_compatible"`` → ``openai/<模型名>``（配合 api_base 使用）

    Raises:
        ValueError: 模型名是空的。
    """
    name = model.strip()
    if not name:
        raise ValueError("模型名不能为空")
    if "/" in name:
        return name
    if provider == "openai_compatible":
        return f"{OPENAI_COMPATIBLE_PREFIX}{name}"
    return f"{provider}/{name}"


def stream_reply(
    messages: Sequence[Message],
    model: str,
    *,
    provider: str = "deepseek",
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 1.0,
    timeout: float = 30.0,
) -> Iterator[str]:
    """流式产出回复的文本增量。

    只产出文本。拼 prompt、管上下文、判断该不该取消，都是上层（runtime）的事。

    Raises:
        LLMTimeoutError: 请求超时（错误码 llm_timeout）
        LLMProviderError: Provider 报错或连不上（错误码 llm_error）
        ValueError: 模型名为空
    """
    payload: dict[str, Any] = {
        "model": normalize_model_name(provider, model),
        "messages": [message.to_payload() for message in messages],
        "stream": True,
        "temperature": temperature,
        "timeout": timeout,
    }
    if api_key:
        payload["api_key"] = api_key
    if base_url:
        payload["api_base"] = base_url

    completion = _completion or _default_completion

    try:
        response = completion(**payload)
        for chunk in response:
            text = _extract_delta(chunk)
            if text:
                yield text
    except Exception as exc:
        if isinstance(exc, LLMError):
            raise
        raise _translate_error(exc) from exc


def _extract_delta(chunk: Any) -> str:
    """从一帧里取出文本增量。兼容对象形式和字典形式两种返回。

    取不到内容就返回空串（有些帧只有 role 或统计信息），而不是报错。
    """
    choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
    if not choices:
        return ""
    first = choices[0]
    if isinstance(first, dict):
        delta = first.get("delta") or {}
        content = delta.get("content") if isinstance(delta, dict) else None
    else:
        content = getattr(getattr(first, "delta", None), "content", None)
    return content if isinstance(content, str) else ""


def _translate_error(exc: Exception) -> LLMError:
    """把 litellm 的异常翻译成本层的异常。

    这里按类名判断而不是 isinstance：litellm 各版本的异常层级不太稳定，
    按名字匹配的代价是可能漏判，但不会因为版本升级就 AttributeError。
    """
    name = type(exc).__name__.lower()
    if "timeout" in name or "timedout" in name:
        return LLMTimeoutError(f"LLM 请求超时：{exc}")
    return LLMProviderError(f"LLM 调用失败：{exc}")
