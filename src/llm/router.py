"""LiteLLM 路由封装。

对外只暴露 ``stream_reply()``，签名与 docs/contracts.md 第 4 节一致：
产出纯文本增量，不带任何 Provider 特有字段。

litellm 的异常全部在这里翻译成本层的异常（见 ``llm.schemas``），不外泄。

测试接缝：模块级 ``_completion`` 引用。测试里把它换成假函数即可，不需要联网。
之所以用模块级引用而不是公开参数，是为了让 ``stream_reply`` 的签名保持干净。
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from contracts import LLMError, LLMProviderError, LLMTimeoutError, Message

CompletionFn = Callable[..., Any]

#: 测试替换点。生产路径上是 None，第一次真正调用时才去碰 litellm。
#: 故意不在模块顶层 import litellm：它导入时会联网拉模型价格表（失败还会重试三次），
#: 还可能触发 tiktoken 下载词表。测试不该被这种副作用拖慢，更不该因此失败。
_completion: CompletionFn | None = None

OPENAI_COMPATIBLE_PREFIX = "openai/"

#: LiteLLM 认识的 provider 前缀。模型名的第一段命中这里，才认为调用方已经指定好了路由。
#: 这份名单不必覆盖 LiteLLM 支持的全部 provider：没命中时的后果是给模型名多补一层前缀，
#: 而误判的后果是路由到一个不存在的 provider、抛出难懂的报错。所以宁可保守，遇到再加。
KNOWN_PROVIDER_PREFIXES = frozenset(
    {
        "ai21", "anthropic", "azure", "bedrock", "cerebras", "cohere", "dashscope",
        "databricks", "deepseek", "fireworks_ai", "gemini", "google", "groq",
        "huggingface", "mistral", "moonshot", "nvidia_nim", "ollama", "openai",
        "openrouter", "perplexity", "replicate", "sagemaker", "sambanova",
        "together_ai", "vertex_ai", "vllm", "watsonx", "xai", "zhipu",
    }
)


def _default_completion(**payload: Any) -> Any:
    """生产路径：第一次调用时才导入 litellm。"""
    # 用本地打包的价格表，省掉启动时那次联网（以及失败后的重试等待）。
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

    import litellm

    return litellm.completion(**payload)


def normalize_model_name(provider: str, model: str) -> str:
    """把配置里的模型名补成 LiteLLM 认识的形式。

    - 第一段是已知 provider（``openai/gpt-4o``、``deepseek/deepseek-chat``）→ 原样返回
    - ``provider="deepseek"`` + ``deepseek-chat`` → ``deepseek/deepseek-chat``
    - ``provider="openai_compatible"`` + ``Qwen/Qwen2.5-7B`` → ``openai/Qwen/Qwen2.5-7B``

    最后一条要留意：厂商自己的命名空间（``Qwen/``、``deepseek-ai/``）长得和 provider
    前缀一模一样，但它不是前缀。原样放行的话，LiteLLM 会去找一个名叫 ``Qwen`` 的
    provider。未识别的名字统一挂到 ``openai/`` 下面，配合 api_base 使用。

    Args:
        provider: ``"deepseek"`` 或 ``"openai_compatible"``。
        model: 配置里写的模型名。

    Returns:
        补好前缀的模型名。

    Raises:
        ValueError: 模型名是空的。

    Example:
        ```python
        normalize_model_name("deepseek", "deepseek-chat")
        # 'deepseek/deepseek-chat'
        normalize_model_name("openai_compatible", "Qwen/Qwen2.5-7B")
        # 'openai/Qwen/Qwen2.5-7B'
        ```
    """
    name = model.strip()
    if not name:
        raise ValueError("模型名不能为空")
    head, separator, _ = name.partition("/")
    if separator and head in KNOWN_PROVIDER_PREFIXES:
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

    Args:
        messages: 完整上下文（含 system），调用方负责拼接与裁剪。
        model: 模型名，可以带也可以不带 provider 前缀。
        provider: ``"deepseek"`` 或 ``"openai_compatible"``。
        api_key: API Key；``None`` 表示交给底层库从环境变量读。
        base_url: 自建端点的地址；``None`` 表示用官方地址。
        temperature: 采样温度。
        timeout: 单次请求超时（秒）。

    Yields:
        文本增量。空 delta 或只有统计信息的帧被跳过。

    Raises:
        LLMTimeoutError: 请求超时（错误码 llm_timeout）。
        LLMProviderError: Provider 报错或连不上（错误码 llm_error）。
        ValueError: 模型名为空。

    Example:
        ```python
        messages = [Message(role="user", content="在吗")]
        reply = "".join(stream_reply(messages, "deepseek-chat", api_key="sk-..."))
        ```
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

    response: Any = None
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
    finally:
        _close_quietly(response)


def _close_quietly(response: Any) -> None:
    """尽力关闭响应对象。

    消费方中途放弃时（用户打断、上层取消），这里是唯一的释放点：不关的话，
    底层 HTTP 连接要等垃圾回收才释放。关不掉不是致命问题，所以把异常吞掉，
    免得它盖掉真正的错误；没有 close 方法的响应（比如生成器）走的是同一条路径。
    """
    if response is None:
        return
    with contextlib.suppress(Exception):
        response.close()


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


class RouterLlmClient:
    """``contracts.LlmClient`` 的默认实现：转交 :func:`stream_reply`。

    单独成类是为了让 runtime 依赖端口而不是模块函数；测试里换掉这个类
    或替换 ``llm.router.stream_reply`` 都可以。

    Example:
        ```python
        client = RouterLlmClient()
        deltas = list(client.stream(history, model="deepseek-chat",
                                    provider="deepseek", api_key="sk-...",
                                    base_url=None, temperature=1.0, timeout=30.0))
        ```
    """

    def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        provider: str,
        api_key: str | None,
        base_url: str | None,
        temperature: float,
        timeout: float,
    ) -> Iterator[str]:
        """见 ``contracts.LlmClient.stream``。

        Args:
            messages: 完整上下文。
            model: 模型名。
            provider: Provider 名。
            api_key: API Key。
            base_url: 自建端点地址。
            temperature: 采样温度。
            timeout: 单次请求超时（秒）。

        Returns:
            文本增量的迭代器（惰性）。

        Raises:
            LLMTimeoutError: 请求超时。
            LLMProviderError: Provider 报错或连不上。
        """
        return stream_reply(
            messages,
            model,
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            timeout=timeout,
        )
