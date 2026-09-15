"""llm.router 的测试。全程使用替身，不联网。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from llm import router
from llm.router import normalize_model_name, stream_reply
from llm.schemas import LLMProviderError, LLMTimeoutError, Message


@dataclass
class _Delta:
    content: str | None


@dataclass
class _Choice:
    delta: _Delta


@dataclass
class _Chunk:
    choices: list[_Choice]


def _object_chunk(text: str | None) -> _Chunk:
    """模仿 litellm 返回的对象形式。"""
    return _Chunk(choices=[_Choice(delta=_Delta(content=text))])


def _dict_chunk(text: str | None) -> dict[str, Any]:
    """模仿字典形式。"""
    return {"choices": [{"delta": {"content": text}}]}


class _Timeout(Exception):
    """类名里带 timeout，用来验证异常翻译。"""


class _FakeCompletion:
    """替身：记录调用参数，按预设产出分片或抛错。"""

    def __init__(
        self,
        chunks: list[Any],
        error: Exception | None = None,
        stream: Any = None,
    ) -> None:
        self._chunks = chunks
        self._error = error
        self._stream = stream
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._chunks if self._stream is None else self._stream


@pytest.fixture
def use_fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    def _install(fake: _FakeCompletion) -> _FakeCompletion:
        monkeypatch.setattr(router, "_completion", fake)
        return fake

    return _install


def test_tokens_are_forwarded_in_order(use_fake: Any) -> None:
    use_fake(_FakeCompletion([_object_chunk("我"), _object_chunk("是"), _object_chunk("谁")]))

    result = list(stream_reply([Message(role="user", content="你好")], "deepseek-chat"))

    assert result == ["我", "是", "谁"]


def test_empty_and_unknown_frames_are_skipped(use_fake: Any) -> None:
    use_fake(
        _FakeCompletion(
            [_object_chunk(""), _object_chunk(None), {"choices": []}, _object_chunk("答")]
        )
    )

    assert list(stream_reply([Message(role="user", content="hi")], "deepseek-chat")) == ["答"]


def test_dict_style_frames_are_supported(use_fake: Any) -> None:
    use_fake(_FakeCompletion([_dict_chunk("甲"), _dict_chunk("乙")]))

    assert list(stream_reply([Message(role="user", content="hi")], "deepseek-chat")) == ["甲", "乙"]


def test_payload_shape_for_deepseek(use_fake: Any) -> None:
    fake = use_fake(_FakeCompletion([_object_chunk("ok")]))

    list(
        stream_reply(
            [Message(role="system", content="你是角色"), Message(role="user", content="你好")],
            "deepseek-chat",
            provider="deepseek",
            api_key="sk-test",
            temperature=0.7,
        )
    )

    payload = fake.calls[0]
    assert payload["model"] == "deepseek/deepseek-chat"
    assert payload["stream"] is True
    assert payload["temperature"] == 0.7
    assert payload["api_key"] == "sk-test"
    assert payload["messages"] == [
        {"role": "system", "content": "你是角色"},
        {"role": "user", "content": "你好"},
    ]
    assert "api_base" not in payload


def test_payload_shape_for_openai_compatible(use_fake: Any) -> None:
    fake = use_fake(_FakeCompletion([_object_chunk("ok")]))

    list(
        stream_reply(
            [Message(role="user", content="你好")],
            "gpt-4o-mini",
            provider="openai_compatible",
            api_key="sk-test",
            base_url="https://example.invalid/v1",
        )
    )

    payload = fake.calls[0]
    assert payload["model"] == "openai/gpt-4o-mini"
    assert payload["api_base"] == "https://example.invalid/v1"


def test_timeout_is_translated(use_fake: Any) -> None:
    use_fake(_FakeCompletion([], error=_Timeout("too slow")))

    with pytest.raises(LLMTimeoutError) as excinfo:
        list(stream_reply([Message(role="user", content="hi")], "deepseek-chat"))

    assert excinfo.value.code == "llm_timeout"


def test_other_errors_are_translated(use_fake: Any) -> None:
    use_fake(_FakeCompletion([], error=RuntimeError("boom")))

    with pytest.raises(LLMProviderError) as excinfo:
        list(stream_reply([Message(role="user", content="hi")], "deepseek-chat"))

    assert excinfo.value.code == "llm_error"


def test_error_raised_while_streaming_is_translated(use_fake: Any) -> None:
    def _boom_stream() -> Any:
        yield _object_chunk("前半句")
        raise _Timeout("mid-stream")

    use_fake(_FakeCompletion([], stream=_boom_stream()))

    with pytest.raises(LLMTimeoutError):
        list(stream_reply([Message(role="user", content="hi")], "deepseek-chat"))


def test_normalize_model_name() -> None:
    assert normalize_model_name("deepseek", "deepseek-chat") == "deepseek/deepseek-chat"
    assert normalize_model_name("openai_compatible", "gpt-4o-mini") == "openai/gpt-4o-mini"
    assert normalize_model_name("deepseek", "openai/gpt-4o") == "openai/gpt-4o"
    assert normalize_model_name("deepseek", "  deepseek-chat  ") == "deepseek/deepseek-chat"


def test_normalize_empty_model_name_raises() -> None:
    with pytest.raises(ValueError):
        normalize_model_name("deepseek", "   ")
