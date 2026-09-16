"""config 模块的测试。不读真实 .env，不发网络请求。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

import config
from config import Settings


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """清掉外部环境里的同名变量。

    Settings 除了读 .env 还会读环境变量（pydantic-settings 的既定优先级）。
    开发时若在 shell 里导出过真实配置，这些测试会因为环境而不是代码变红。
    """
    for key in list(os.environ):
        upper = key.upper()
        if upper == "LOG_LEVEL" or upper.startswith(("LLM_", "TTS_", "LIVE2D_")):
            monkeypatch.delenv(key, raising=False)


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

def test_env_file_is_loaded(tmp_path: Path) -> None:
    """生产路径：配置从 .env 文件读进来。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_MODEL=from-dotenv\nTTS_EDGE_VOICE=zh-CN-YunxiNeural\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.llm_model == "from-dotenv"
    assert settings.tts_edge_voice == "zh-CN-YunxiNeural"


def test_environment_wins_over_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量优先于 .env。这是 pydantic-settings 的优先级，写死成契约。"""
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("LLM_MODEL", "from-environment")

    assert Settings(_env_file=env_file).llm_model == "from-environment"


def test_default_env_file_ignores_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归：env 文件曾经写成相对路径，换个工作目录就读不到配置。"""
    expected_root = Path(config.__file__).resolve().parents[1]
    expected_env_file = expected_root / ".env"

    assert expected_root == config.PROJECT_ROOT
    assert expected_env_file == config.ENV_FILE
    assert expected_env_file.is_absolute()

    monkeypatch.chdir(tmp_path)

    assert expected_env_file == Settings.model_config["env_file"]


def test_window_size_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE2D_WINDOW_WIDTH", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)