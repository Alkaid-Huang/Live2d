"""config 模块的测试。不读真实 .env，不发网络请求。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import Settings


def test_defaults_without_env_file() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "deepseek"
    assert settings.llm_model == "deepseek-chat"
    assert settings.llm_api_key == ""
    assert settings.tts_backend == "edge"
    assert settings.live2d_window_width == 400
    assert settings.live2d_window_height == 600


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("TTS_EDGE_VOICE", "zh-CN-YunxiNeural")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.llm_base_url == "https://example.invalid/v1"
    assert settings.tts_edge_voice == "zh-CN-YunxiNeural"


def test_invalid_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "some_other_vendor")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_blank_model_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "   ")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_temperature_out_of_range_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TEMPERATURE", "9.9")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_api_key_does_not_break_construction() -> None:
    """缺 Key 时构造配置不应该失败，只有真正要用的时候才拦。"""
    settings = Settings(_env_file=None)
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        settings.require_llm_credentials()


def test_openai_compatible_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-not-a-real-key")

    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        settings.require_llm_credentials()
