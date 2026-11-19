"""分层异常。上层只需要捕获每一层的基类，不接触底层库的异常类型。

每个异常带一个 ``code`` 类属性，runtime 把它原样写进 ``ErrorEvent.code``。
"""

from __future__ import annotations


class LLMError(Exception):
    """LLM 层所有异常的基类。

    Attributes:
        code: 错误码，写进 ``ErrorEvent.code``。

    Example:
        ```python
        try:
            list(stream_reply([], "deepseek-chat"))
        except LLMError as exc:
            print(exc.code)
        ```
    """

    code: str = "llm_error"


class LLMTimeoutError(LLMError):
    """请求超时。

    Attributes:
        code: 恒为 ``"llm_timeout"``。
    """

    code = "llm_timeout"


class LLMProviderError(LLMError):
    """Provider 报错，或者根本连不上。

    Attributes:
        code: 恒为 ``"llm_error"``。
    """

    code = "llm_error"


class TtsError(Exception):
    """语音合成失败或超时。

    Attributes:
        code: 恒为 ``"tts_error"``。

    Example:
        ```python
        raise TtsError("合成失败")
        ```
    """

    code = "tts_error"
